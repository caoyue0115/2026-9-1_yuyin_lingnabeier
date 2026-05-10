# v5 ESP32 Opus Uplink Design

日期：2026-05-10

## 目标

P3 将 ESP32-S3 / ESP-VoCat v1.2 板端的录音上行，从“录完整段 PCM 后提交 HTTP session”改为“开口后按 PCM frame 编码 Opus，并以 framed-v1 binary WebSocket frame 持续发送到 v5 云端”。云端入口固定为：

```text
WS /api/v5/realtime/opus-stream
```

板端只连接 v5 云端 API，不保存 DashScope 或火山凭据。默认 start config 显式选择火山 ASR：

```json
{"type":"start","run_asr":true,"run_full_chain":true,"asr_provider":"volcengine","answer_mode":"short"}
```

## 当前板端旧路径

当前 `run_trigger_pipeline()` 路径是：

```text
touch trigger
  -> play record_prompt_1.pcm
  -> audio_in_wait_for_speech_start()
  -> audio_in_record_after_speech_start()
  -> cloud_client_submit_realtime_session()
  -> cloud_client_stream_realtime_audio()
  -> audio_out buffered playback
```

`waiting_speech` 已满足现有产品口径：播放“请讲”，等待开口，首次超时播放重试提示并重等一次，二次超时退出。P3 不改这部分状态机。

旧上行问题是 `audio_in_record_after_speech_start()` 必须先将整段 PCM 放入 heap/PSRAM，再通过 `POST /api/v3/realtime/sessions` 提交。弱网上行尾部等待和整段 buffer 占用都会进入首响应路径。

## 新 WS 上行路径

P3 新路径：

```text
touch trigger
  -> play record_prompt_1.pcm
  -> audio_in_wait_for_speech_start()
  -> cloud_client_opus_uplink_begin()
  -> audio_in_stream_after_speech_start()
       -> PCM chunk callback
       -> Opus encode
       -> framed-v1 packet
       -> WebSocket binary send
  -> cloud_client_opus_uplink_finish()
  -> reuse cloud_client_stream_realtime_audio()
  -> audio_out buffered playback
```

WebSocket URL 由 `DEMO_SERVER_BASE_URL` 转换：`http://host` 变 `ws://host/api/v5/realtime/opus-stream`，`https://host` 变 `wss://host/api/v5/realtime/opus-stream`。握手和 payload 不包含云厂商凭据。

framed-v1 与 `src/providers/opus.py` 对齐：

```text
outer:
  4 bytes sequence, unsigned big-endian
  4 bytes payload length, unsigned big-endian
  N bytes payload

payload:
  2 bytes opus packet length, unsigned big-endian
  N bytes opus packet
```

## 不动下行链路的边界

本轮不修改以下已稳定参数和实现：

- `cloud_client_stream_realtime_audio()` 收流、framed-v1 下行解析、Opus decode、PCM queue、playback task。
- `DEMO_REALTIME_AUDIO_*` queue length、jitter buffer、prebuffer、read chunk、close wait、tail tolerance。
- intro 并行策略、audio gate、fake timeout/尾差收尾相关行为。
- touch 触发配置，不回退 GPIO6 button 触发。

新增上行只替换“用户开始说话后如何把音频送到云端”。云端 `done` 返回 `audio_stream_url` 后，仍复用原下行拉流/播放代码。

## 任务划分

第一版采用串行上行实现，但边界按任务模型拆清楚，便于后续改为 queue task。

- capture task：`audio_in_stream_after_speech_start()` 负责 microphone read、VAD stop、PCM chunk callback、保留 speech prefix。
- opus encode task：第一版在 callback 内同步编码，使用 `espressif/esp_audio_codec` 的 `esp_opus_enc_*`，输入固定 16 kHz / 16-bit / mono。
- ws uplink task：`cloud_client_opus_uplink_*` 负责连接、start JSON、framed-v1 binary、end JSON、ack/error/done 事件采集。
- response/downlink task：保持 `main.c` 中现有 realtime audio open、intro、parallel stream、playback 逻辑。

## 队列设计

第一版不新增 FreeRTOS queue，避免破坏 v24 下行稳定路径：

- capture 通过 callback 同步交给 uplink context。
- encoder 维护一个 frame-sized PCM buffer，凑满 60 ms 后编码。
- ws send 以“一帧一个 binary message”发送，和 PC smoke 一致。
- websocket event handler 只累计 ack/done/error 状态，不在 handler 内停止 client。

后续真机如发现 encode 或 send 阻塞 mic read，再拆成两个队列：

- PCM queue：capture -> encode，建议 4 到 8 个 60 ms frame。
- Opus queue：encode -> ws send，建议 8 到 16 个 packet。

## Frame-ms 建议

默认 `V5_OPUS_UPLINK_FRAME_MS=60`。原因：

- PC P0/P1/P2 smoke 已用 60 ms 验证。
- 16 kHz mono 16-bit 下每帧 PCM 为 `16000 * 0.06 * 2 = 1920 bytes`，小于当前 2048 byte mic chunk。
- 单包频率约 16.7 fps，降低 WebSocket send 调度压力。

若真机编码耗时或单帧延迟不可接受，再评估 40 ms 或 20 ms。第一版不在运行时自适应 frame duration。

## Buffer / PSRAM 策略

旧路径保留整段 `DEMO_AUDIO_BUFFER_BYTES` PSRAM buffer。新路径改为小 buffer：

- speech prefix 沿用现有 waiting_speech 返回的小 buffer。
- capture chunk 沿用 `DEMO_AUDIO_CHUNK_BYTES`。
- Opus encoder PCM frame buffer 优先 heap，大小约 1920 bytes。
- Opus output buffer 使用 encoder 推荐大小，通常远小于 PCM frame。
- framed-v1 send buffer 大小为 `8 + 2 + opus_packet_bytes`。

日志持续打印 `heap_free` 和 `psram_free` watermark，便于真机确认不会挤压下行 jitter buffer。

## 错误降级与 Fallback

P3.1 后 fallback 分层如下：

- L0 正常：火山 ASR 成功，或火山失败后 DashScope fallback 成功，继续 v5 full-chain，云端返回 `audio_stream_url`，板端复用现有下行播放链路。
- L1 云端 ASR 失败：火山和 DashScope 均失败、空文本或超时，云端返回 `type=error`，`error_code=asr_all_providers_failed` 或具体 ASR 错误码；板端播放本地“请重试/请重新按”提示并结束本轮，不跑旧 `/audio`。
- L2 极端失败：WebSocket 连接失败、握手失败、协议错包、send frame 失败、等待 `done` 超时、服务器不可达；板端播放本地“请重试”提示并结束本轮。
- L3 调试开关：只有开发者显式设置 `V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO=1` 时，才允许回旧整段 `/audio` 路径。默认构建为 `0`。

以下错误触发 L1/L2 行为降级：

- WebSocket URL 构造或连接失败。
- start control 发送失败。
- Opus encoder 初始化或编码失败。
- binary frame 发送失败。
- 云端返回 `type=error`。
- end 后未收到可用 `audio_stream_url`。

默认行为是播放本地错误提示并结束本轮，日志必须包含：

```text
v5_uplink_failed
error_code=<reason>
fallback_behavior=local_prompt
legacy_audio_fallback=false
```

若开发者显式启用 `V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO=1`，pipeline 打印：

```text
legacy_audio_fallback=true
fallback_reason=<reason>
```

然后才调用旧的 `audio_in_record_after_speech_start()` 或 `audio_in_record_fixed_duration()` + `cloud_client_submit_realtime_session()`。该路径仅用于开发调试，不是默认产品 fallback。

## 指标日志字段

板端至少打印：

- `v5_uplink_enabled`
- `v5_uplink_fallback_legacy_audio`
- `v5_uplink_behavior_fallback_enabled`
- `touch_trigger_ms`
- `prompt_play_start` / `prompt_play_end`
- `speech_start_ms`
- `ws_connect_start` / `ws_connect_done`
- `asr_provider`
- `first_pcm_frame_ms`
- `first_opus_frame_ms`
- `first_ws_frame_sent_ms`
- `last_ws_frame_sent_ms`
- `end_sent_ms`
- `first_ack_ms`
- `asr_final_received_ms`
- `done_received_ms`
- `first_audio_play_ms`
- `uplink_frame_count`
- `uplink_opus_bytes`
- `uplink_pcm_bytes`
- `compression_ratio`
- `heap_free` / `psram_free` watermark
- 失败时的 `fallback_behavior`、`legacy_audio_fallback`、`fallback_reason`

## P3.2 云端 ASR fallback 可观测性

板端 v25 真机验证显示 v5 Opus WS 上行和下行播放已打通，但多轮实际 ASR provider 为 DashScope。为了定位 Volcengine primary 失败原因，云端 v5 增加 primary/fallback 可观测字段，不修改 Volcengine 协议参数、不改 ASR provider 默认策略。

status API trace 必须保留：

- `asr_primary_provider`
- `asr_provider_used`
- `asr_fallback_provider`
- `asr_fallback_used`
- `asr_primary_error_code`
- `asr_primary_error_message`
- `asr_primary_provider_log_id`
- `provider_error_code`
- `provider_error_message`
- `provider_log_id`
- `fallback_reason`
- `fallback_started_abs_ms`
- `fallback_done_abs_ms`

fallback 触发时，云端 stdout 打一行可 grep 的结构化日志：

```text
event=v5_asr_fallback session_id=<pending-or-session-id> asr_primary_provider=volcengine asr_primary_error_code=<code> asr_primary_error_message=<message> asr_fallback_used=true asr_provider_used=dashscope asr_fallback_provider=dashscope asr_primary_provider_log_id=<primary_log_id> provider_log_id=<fallback_log_id> fallback_reason=<code> fallback_started_abs_ms=<ms> fallback_done_abs_ms=<ms>
```

说明：

- fallback 初次触发时 full-chain session 尚未创建，日志中的 `session_id=pending`。
- full-chain session 创建后再次记录同一事件，`session_id` 为可通过 status API 查询的 realtime session id。
- 如果本轮 Volcengine primary 成功，则 `asr_fallback_used=false`，上述 fallback 日志不会出现；status API 仍应返回全部字段且 primary error 字段为 `null`。

## 编译验证方式

云端回归：

```bash
python -m pytest -q
```

ESP-IDF 编译：

```bash
cd esp_idf_demo
source /home/aitopia/esp/esp-idf-v5.5.4-full/export.sh
idf.py build
```

若 component manager 需要下载 `esp_websocket_client`，编译环境必须可访问 Espressif component registry，或提前缓存该组件。

## 真机验证步骤

1. 启动 v5 本地云端并确认 `.env` 使用 `ASR_PROVIDER=volcengine` 或 start config 显式指定火山：

```bash
uvicorn src.app:app --host 0.0.0.0 --port 8010
```

2. PC smoke 先确认云端 WS 入口仍可用：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --asr-provider volcengine --max-polls 160 --status-timeout 30 --timeout 30
```

3. 编译、烧录、监控：

```bash
cd esp_idf_demo
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

4. 触摸触发后观察日志：

- 确认 `v5_uplink_enabled=1`。
- 确认 `first_ws_frame_sent_ms` 早于录音结束。
- 确认 `asr_provider=volcengine`。
- 确认 `done_received_ms` 后复用现有 `stream_audio` 下行日志。
- 若 v5 失败且未显式开启 legacy 调试开关，确认日志包含 `v5_uplink_failed`、`fallback_behavior=local_prompt`、`legacy_audio_fallback=false`。
- 只有显式构建 `V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO=1` 时，才确认 `legacy_audio_fallback=true` 和 `fallback_reason=<reason>`。
