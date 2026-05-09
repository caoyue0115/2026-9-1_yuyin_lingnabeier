# v5 Opus Framed-v1 上行 PoC 设计

日期：2026-05-08

## 目标

v5 第一阶段只验证 PC 模拟器到云端实验接口的 Opus 压缩上行链路，不修改 v3 原目录、不部署、不接 ESP32 固件。

链路：

```text
WAV 文件
  -> PC 脚本读取 16 kHz / 16-bit / mono PCM
  -> Opus 编码
  -> framed-v1 封包
  -> POST /api/v5/realtime/opus-sessions
  -> 云端解析 framed-v1
  -> Opus 解码为 PCM
  -> 保存重建 WAV
  -> 复用现有 realtime session 流程
```

## 上行包格式

复用 v3 下行外层 framed-v1：

```text
4 bytes: sequence, unsigned big-endian
4 bytes: payload length, unsigned big-endian
N bytes: payload
```

上行 payload 为现有 Opus provider 产出的单包格式：

```text
2 bytes: opus packet length, unsigned big-endian
N bytes: opus packet
```

第一阶段 HTTP body 是多个 framed-v1 packet 顺序拼接。后续阶段可把同一格式迁移到 chunked HTTP 或 WebSocket。

## Headers

实验接口要求：

```text
Content-Type: application/octet-stream
X-Device-Id: <device or simulator id>
X-Audio-Packetization: framed-v1
X-Audio-Format: opus
X-Opus-Sample-Rate: 16000
X-Opus-Channels: 1
X-Opus-Frame-Duration-Ms: 60
X-Original-Pcm-Bytes: <optional original PCM byte count>
```

第一阶段不在板端或脚本中放云厂商凭据。

`X-Original-Pcm-Bytes` 用于裁剪 Opus 最后一帧补零产生的尾部静音。PC 模拟器会发送该值；如果未来板端无法提供精确字节数，可省略并保留完整解码结果。

## 服务端流程

1. 校验 content type、packetization、format、Opus 参数和上传大小。
2. 按 framed-v1 解析外层包，校验 sequence 连续、长度完整。
3. 对每个 payload 解析 2 字节 Opus packet length。
4. 用 libopus 解码为 signed little-endian PCM。
5. 汇总 PCM 后保存 WAV。
6. 建立 realtime session，并把上行指标写入 session trace。
7. 启动现有 `start_realtime_session`，复用 ASR / RAG / LLM / TTS。

## 指标

第一阶段响应和 session trace 至少记录：

- `uplink_opus_bytes`
- `uplink_pcm_bytes`
- `uplink_compression_ratio`
- `uplink_frame_count`
- `opus_decode_ms`
- `reconstructed_audio_ms`
- `asr_ms`
- `first_llm_chunk_ms`
- `first_tts_chunk_ms`
- `first_audio_byte_ms`
- `done_ms`
- `question_text`
- `error_code`

其中 `reconstructed_audio_ms` 按 `pcm_bytes / (sample_rate * channels * 2)` 估算。

## 错误处理

- 空 body：`empty_opus_body`
- content type 不符：`invalid_request`
- 非 framed-v1：`invalid_packetization`
- 非 opus：`invalid_audio_format`
- sequence 不连续：`framed_sequence_gap`
- 截断包：`framed_packet_truncated`
- payload 内 Opus 长度不匹配：`opus_packet_truncated`
- libopus 不可用或解码失败：`opus_decode_failed`

错误响应不包含凭据、音频内容或 payload 原文。

## PC 模拟器

`scripts/opus_uplink_smoke.py` 读取 WAV 并要求输入为 16 kHz / 16-bit / mono。第一阶段不自动转码，避免把转码问题混入协议验证。

脚本输出 JSONL：

- `submit`
- `status`
- `audio`（可选，复用下行拉流口径）

## 阶段边界

阶段 1：完整 HTTP body 内部模拟 framed-v1 顺序上传，验证压缩率、解码稳定性和复用 v3 realtime 流程。

阶段 2：同一包格式迁移到真正流式上行，并把解码后的 PCM chunk 接入流式 ASR。

阶段 3：基于稳定 ASR partial 再评估 LLM 提前启动、Prefill、打断和多轮。

## 2026-05-09 本地完整链路实测

本轮使用 v5 本地 `.env` 配置与 v3 同口径的 DashScope ASR / LLM / TTS 最小变量；`.env` 未入库，文档不记录真实凭据。

命令：

```bash
python scripts/opus_uplink_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --max-polls 100 --status-timeout 20 --submit-timeout 20
```

结果：

| 字段 | 值 |
| --- | --- |
| session_id | `64fb5f06-e831-448e-b68d-ed81b91600b9` |
| status | `done` |
| final_reason | `completed_answer` |
| error_code | `null` |
| question_text | `情解释阿弥陀佛是什么意思？` |

关键 trace：

| 指标 | ms / bytes / ratio |
| --- | ---: |
| submit_ms | 84 |
| uplink_frame_count | 79 |
| uplink_opus_bytes | 13415 |
| uplink_pcm_bytes | 150156 |
| uplink_compression_ratio | 11.193 |
| reconstructed_audio_ms | 4692 |
| opus_decode_ms | 6 |
| asr_ms | 8256 |
| retrieval_ms | 689 |
| first_llm_chunk_ms | 12188 |
| first_tts_chunk_ms | 13240 |
| first_audio_byte_ms | 13240 |
| done_ms | 17763 |
| audio_bytes | 504320 |
| audio_duration_ms | 15760 |
| audio_stream_wall_ms | 4267 |
| production_ratio | 3.693 |

回答：

```text
阿弥陀佛是西方极乐世界教主的名号，意为无量光寿。此佛号包含光明与寿命的圆满，指引众生往生净土。
```

RAG 补充证据：当前 session trace 未直接存 top docs；用同一 ASR 文本回放 retriever 得到 top score `0.7802826136942801`，top docs 为 `ZT02_阿弥陀佛是谁_大白话版.md` 和 `ZT03_阿弥陀佛名号与无量光寿.md`。

结论：第一阶段 Opus framed-v1 上行已完成到 ASR/RAG/LLM/TTS 的本地完整链路验证。当前瓶颈不是 Opus 解码，`opus_decode_ms=6`；端到端主要耗时在 ASR 和 LLM/TTS 首包前。
