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

## 2026-05-09 P1：接入 DashScope Realtime ASR

P1 在 `WS /api/v5/realtime/opus-stream` 上增加可选 ASR/full-chain 模式。默认行为仍保持 P0：不发 `start` config 或不启用 ASR 时，只做上行流式 smoke。

启用方式：

```json
{"type":"start","run_asr":true,"run_full_chain":true}
```

随后继续发送 binary framed-v1 Opus frame，最后发送：

```json
{"type":"end"}
```

服务端行为：

- 每个 Opus frame 解码出 PCM 后，立即送入 DashScope `paraformer-realtime-v2` realtime websocket。
- ASR partial 只作为事件回传和记录，不触发 LLM。
- ASR final 出来后，才使用 final text 启动既有 RAG / LLM / TTS session。
- 不接火山 ASR，不做 partial 提前 LLM，不做打断。

新增关键指标：

| 指标 | 含义 |
| --- | --- |
| `first_pcm_to_asr_ms` | 服务端收到首个 decoded PCM 后送入 ASR 的时间 |
| `first_asr_partial_ms` | DashScope realtime ASR 首个非空 partial 时间 |
| `asr_final_ms` | DashScope realtime ASR final 时间 |
| `realtime_asr_request_id` | DashScope realtime ASR request id |
| `retrieval_top_score` | final text 进入 RAG 后的 top score |

P0 回归命令：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime
```

P0 回归结果：

| 指标 | 值 |
| --- | ---: |
| first_frame_server_ms | 3 |
| server_receive_duration_ms | 4781 |
| client_stream_duration_ms | 4848 |
| uplink_frame_count | 79 |
| uplink_opus_bytes | 13415 |
| uplink_pcm_bytes | 150156 |
| uplink_compression_ratio | 11.193 |
| opus_decode_ms | 12 |
| reconstructed_audio_ms | 4692 |
| record_end_to_reconstruct_done_ms | 1 |
| error_code | null |

P1 命令：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --max-polls 120 --status-timeout 20 --timeout 30
```

P1 上行 + ASR 结果：

| 指标 | 值 |
| --- | ---: |
| first_frame_server_ms | 4 |
| first_pcm_to_asr_ms | 4 |
| first_asr_partial_ms | 2823 |
| asr_final_ms | 5675 |
| server_receive_duration_ms | 4776 |
| client_stream_duration_ms | 4843 |
| uplink_frame_count | 79 |
| uplink_opus_bytes | 13415 |
| uplink_pcm_bytes | 150156 |
| uplink_compression_ratio | 11.193 |
| opus_decode_ms | 12 |
| reconstructed_audio_ms | 4692 |
| record_end_to_reconstruct_done_ms | 1 |
| error_code | null |

ASR partial：有。示例 partial 包括 `情`、`请`、`请解`、`请解释。阿`、`请解释。阿弥`、`请解释。阿弥陀`。

ASR request_id：`8ae9dc6f6473490b9a8bf5370be17455`。

ASR final：

```text
情解释阿弥陀佛是什么意思？
```

该 final text 已启动后续 session `eeacb3be-eeac-4762-b9a0-74efed6658dd`，状态 `done`，`final_reason=completed_answer`。

full-chain session trace：

| 指标 | 值 |
| --- | ---: |
| asr_ms | 5675 |
| retrieval_ms | 667 |
| retrieval_top_score | 0.7802826136942801 |
| first_llm_chunk_ms | 2913 |
| first_tts_chunk_ms | 4505 |
| first_audio_byte_ms | 4505 |
| done_ms | 8239 |
| audio_bytes | 453120 |
| audio_duration_ms | 14160 |
| audio_stream_wall_ms | 3463 |
| production_ratio | 4.089 |

回答：

```text
阿弥陀佛是西方极乐世界教主的名号，代表无量光明与寿命。此佛号蕴含着救度众生的大愿，令念佛者得生净土。
```

阶段判断：

- P1 已证明：v5 服务端可以边收 Opus、边解码 PCM、边喂 DashScope realtime ASR，并在 ASR final 后复用既有 RAG/LLM/TTS。
- P1 没有做 partial 提前 LLM，符合当前边界。
- 当前主要问题是 DashScope realtime ASR final 仍约 6.9 秒，并且 ASR final 首字仍有错词：`情解释` 应为 `请解释`。
- 下一步应优先做 9 条同音频矩阵，对比旧完整 WAV ASR 与新 realtime ASR 的 `asr_ms/asr_final_ms`、错词率和稳定性，再决定是否进入板端迁移。

验证：

- `python -m pytest -q`：113 passed, 1 warning
- 本地 uvicorn 已停止
