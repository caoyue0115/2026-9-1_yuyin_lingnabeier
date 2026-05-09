# v5 真流式 Opus Framed-v1 上行设计

日期：2026-05-09

## 目标

本轮只验证真正流式上行，不接 ASR partial，不切换 ASR provider，不接火山 ASR。

链路：

```text
WAV 文件
  -> PC 模拟器按帧读取 PCM
  -> Opus 编码
  -> framed-v1 封包
  -> WebSocket 逐帧发送
  -> 服务端逐帧 ack、解码、聚合 PCM
  -> end 后重建 WAV
```

这一步的核心问题是：服务端能否在录音尚未结束时持续收到 Opus frame，并实时解码/统计，而不是等完整 HTTP body 才开始处理。

## 与完整 Body Endpoint 的区别

保留既有基线：

```text
POST /api/v5/realtime/opus-sessions
```

它继续接收完整 HTTP body，body 内部是连续 framed-v1 Opus 包，end 后直接复用 realtime session。

新增实验 endpoint：

```text
WS /api/v5/realtime/opus-stream
```

区别：

| 项 | 完整 body | 真流式 WebSocket |
| --- | --- | --- |
| 传输 | 一个 HTTP request body | 多个 WebSocket binary message |
| 服务端开始解码 | body 完整到达后 | 第一帧到达后 |
| 回传 | HTTP 202 | 逐帧 `ack` + 最终 `done` |
| ASR/RAG/LLM/TTS | 默认启动 | 默认不启动 |
| 当前目的 | 完整链路基线 | 上行实时性验证 |

## 协议

客户端连接后发送 binary message。每个 binary message 可以包含一个或多个 framed-v1 packet，第一版 PC 模拟器采用一帧一个 message。

外层 framed-v1：

```text
4 bytes: sequence, unsigned big-endian
4 bytes: payload length, unsigned big-endian
N bytes: payload
```

payload 保持现有 Opus 内层格式：

```text
2 bytes: opus packet length, unsigned big-endian
N bytes: opus packet
```

客户端完成发送后发送 JSON control：

```json
{"type":"end","client_stream_duration_ms":4841}
```

可选字段：

```json
{"run_session_after_stream":true}
```

第一版默认不启动 ASR/RAG/LLM/TTS；如果显式打开 `run_session_after_stream`，服务端会在重建 WAV 后复用现有 realtime session。

## Headers

WebSocket 握手使用下列 header：

```text
X-Device-Id: <device or simulator id>
X-Audio-Packetization: framed-v1
X-Audio-Format: opus
X-Opus-Sample-Rate: 16000
X-Opus-Channels: 1
X-Opus-Frame-Duration-Ms: 60
X-Original-Pcm-Bytes: <optional original PCM byte count>
```

本协议不包含云厂商凭据。

## 服务端回传

每解码一个 framed-v1 packet，服务端返回：

```json
{
  "type": "ack",
  "frame_count": 79,
  "received_opus_bytes": 13415,
  "decoded_pcm_bytes": 151680
}
```

收到 end 并重建完成后返回：

```json
{
  "type": "done",
  "stream_accept_ms": 0,
  "first_frame_server_ms": 4,
  "last_frame_server_ms": 4778,
  "client_stream_duration_ms": 4841,
  "server_receive_duration_ms": 4774,
  "uplink_frame_count": 79,
  "uplink_opus_bytes": 13415,
  "uplink_pcm_bytes": 150156,
  "uplink_compression_ratio": 11.193,
  "opus_decode_ms": 12,
  "reconstructed_audio_ms": 4692,
  "record_end_to_reconstruct_done_ms": 2,
  "error_code": null
}
```

## 错误处理

服务端在 WebSocket 已 accept 后返回 JSON error，并关闭连接：

| 场景 | error_code |
| --- | --- |
| 非 framed-v1 | `invalid_packetization` |
| 非 Opus | `invalid_audio_format` |
| 非法 frame size | `invalid_opus_frame_size` |
| sequence 不连续 | `framed_sequence_gap` |
| framed-v1 截断 | `framed_packet_truncated` |
| Opus payload 截断 | `opus_packet_truncated` |
| control JSON 非法 | `invalid_control_json` |
| control type 非 end | `invalid_control_type` |
| 解码后空音频 | `empty_decoded_audio` |
| 原始 PCM 字节数非法 | `invalid_original_pcm_bytes` |

错误返回不包含音频内容、payload 原文或凭据。

## PC 模拟器

脚本：

```text
scripts/opus_uplink_stream_smoke.py
```

命令：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime
```

脚本行为：

- 只接受 16 kHz / 16-bit / mono WAV
- 默认按真实时间节奏发送
- 支持 `--no-realtime` 快速发送
- 支持 `--run-session-after-stream` 在 end 后复用现有 realtime session
- 输出 JSONL：`start`、逐帧 `ack`、最终 `done`

## 2026-05-09 本地实测

输入音频：

```text
/tmp/volc_asr_eval/amitabha.wav
```

命令：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime
```

结果：流式上行通过。服务端收到第一帧后立即 ack，`frame_count` 从 1 持续增长到 79，end 后重建音频。

| 指标 | 值 |
| --- | ---: |
| stream_accept_ms | 0 |
| first_frame_server_ms | 4 |
| last_frame_server_ms | 4778 |
| client_stream_duration_ms | 4841 |
| server_receive_duration_ms | 4774 |
| uplink_frame_count | 79 |
| uplink_opus_bytes | 13415 |
| uplink_pcm_bytes | 150156 |
| uplink_compression_ratio | 11.193 |
| opus_decode_ms | 12 |
| reconstructed_audio_ms | 4692 |
| record_end_to_reconstruct_done_ms | 2 |
| error_code | null |

本轮没有跑 ASR/RAG/LLM/TTS。结论只覆盖上行流式接收、解码、聚合和重建能力。

## 阶段判断

WebSocket 流式上行第一版达成 P0 验收：

- 服务端能收到第一帧并立即 ack。
- 服务端能持续 ack `frame_count` 增长。
- end 后能重建完整音频。
- 重建音频时长与输入音频一致，约 4.692 秒。
- 压缩率 `11.193` 与完整 body 基线一致。
- Opus 解码开销仍很低，约 12 ms。

下一步应做弱网/快发矩阵和 `--run-session-after-stream` 完整链路对照，再决定是否进入 ESP32-S3 端上行迁移。

验证：

- `python -m pytest -q`：108 passed, 1 warning
- 本地 uvicorn 已停止
