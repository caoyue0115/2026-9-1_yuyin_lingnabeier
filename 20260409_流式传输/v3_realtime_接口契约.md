# v3 Realtime 接口契约

日期：`2026-04-09`

## 1. 目标

本契约用于把 `v3/realtime` 第一版实现边界固定下来，避免服务端、ESP 端、smoke 脚本在协议层反复返工。

第一版目标不是完整实时会话产品，而是：

- 保留现有 `v2` 异步链路不动
- 为 `ESP/喵伴` 新增一条独立 `v3` 低延迟输出链路
- 让设备尽量在 `3s` 内开始出声
- 首版允许“更早出声”，不要求 token 级连续说话体验
- `v3` 失败时直接报错，不自动回退到 `v2`

## 2. 第一版关键决策

### 2.1 音频输出格式

`GET /api/v3/realtime/sessions/{session_id}/audio` 返回：

- `16kHz`
- `16-bit`
- `mono`
- `little-endian`
- 裸 `PCM` 字节流

第一版明确不使用：

- 连续 `WAV` 流
- 多个独立小 `WAV` 段拼接
- 自描述音频容器

### 2.2 会话启动时机

`POST /api/v3/realtime/sessions` 返回成功后，服务端立即在后台启动 realtime session producer。

### 2.3 失败策略

第一版 `v3` 是独立实验线。

- `v3` 失败时直接返回失败状态
- ESP 本次请求直接报错
- 不自动回退到 `v2`

### 2.4 文本切分目标

第一版接受“句级切片 + 更早出声”，不追求完整实时对话体验。

建议策略：

- LLM 开启 `stream=True`
- 文本按句末标点优先切片
- 同时设置最小长度阈值，避免切得过碎
- 每个文本片段触发一次 TTS/VC 音频产出

## 3. HTTP 接口

### 3.1 创建会话

`POST /api/v3/realtime/sessions`

请求头：

- `X-Device-Id`
- `X-Sample-Rate`
- `X-Sample-Width`
- `X-Channels`
- `Content-Type: application/octet-stream`

请求体：

- 原始 `PCM` 字节
- 字节序固定为 `little-endian`

成功响应示例：

```json
{
  "status": "accepted",
  "session_id": "6df8f5d6-6d42-4ecf-a49a-7c1ff17d4257",
  "received_at": "2026-04-09T15:34:12.245000+00:00",
  "audio_stream_url": "http://<CURRENT_BASE_URL>/api/v3/realtime/sessions/6df8f5d6-6d42-4ecf-a49a-7c1ff17d4257/audio"
}
```

说明：

- `POST` 成功仅表示“已接收并开始后台处理”
- 不表示 ASR、LLM、TTS 已成功

HTTP 状态码：

- `202 Accepted`
  - 成功接收并进入后台处理
- `400 Bad Request`
  - `invalid_request`
  - `empty_audio_body`
  - `unsupported_audio_format`
- `413 Payload Too Large`
  - `audio_too_large`
- `500 Internal Server Error`
  - `internal_error`

请求约束：

- 请求必须显式带 `Content-Type: application/octet-stream`
- 请求体不允许包装 `WAV` 头或 JSON
- 请求体就是原始 `PCM`

### 3.2 查询会话状态

`GET /api/v3/realtime/sessions/{session_id}`

HTTP 状态码：

- `200 OK`
- `404 Not Found`
  - `session_not_found`

成功响应示例：

```json
{
  "session_id": "6df8f5d6-6d42-4ecf-a49a-7c1ff17d4257",
  "status": "running",
  "step": "tts",
  "final_reason": null,
  "created_at": "2026-04-09T15:34:12.245000+00:00",
  "updated_at": "2026-04-09T15:34:13.901000+00:00",
  "started_at": "2026-04-09T15:34:12.260000+00:00",
  "finished_at": null,
  "question_text": "什么是无相？",
  "answer_text": "无相并非否定万法，而是不执著于一切相。",
  "audio_stream_url": "http://<CURRENT_BASE_URL>/api/v3/realtime/sessions/6df8f5d6-6d42-4ecf-a49a-7c1ff17d4257/audio",
  "trace": {
    "asr_ms": 812,
    "retrieval_ms": 31,
    "first_llm_chunk_ms": 1160,
    "first_tts_chunk_ms": 1650,
    "first_audio_byte_ms": 1820,
    "done_ms": null
  },
  "error_code": null,
  "error_message": null
}
```

固定字段说明：

- `created_at`
- `updated_at`
- `started_at`
- `finished_at`
- `final_reason`
- `trace`

字段语义：

- `question_text`
  - `ASR` 成功后填充
  - `ASR` 失败时为 `null`
- `answer_text`
  - 在 `running` 阶段可为空，或为当前已累计文本
  - 在 `done` 阶段必须为最终完整文本
  - 第一版推荐：`running` 阶段允许为空，`done` 时返回最终文本

### 3.3 拉取音频流

`GET /api/v3/realtime/sessions/{session_id}/audio`

HTTP 状态码：

- `200 OK`
  - 开始流式输出
- `404 Not Found`
  - `session_not_found`
- `409 Conflict`
  - `audio_consumer_exists`
  - `session_not_ready`
- `500 Internal Server Error`
  - 流启动失败或内部流式异常

响应头要求：

- `Content-Type: application/octet-stream`
- `X-Audio-Sample-Rate: 16000`
- `X-Audio-Sample-Width: 16`
- `X-Audio-Channels: 1`
- `X-Audio-Endian: little`
- `Transfer-Encoding: chunked`

约束：

- 返回的是单个连续裸 `PCM` 流
- 第一版不在流内嵌入额外 framing
- 第一版不在流内放 JSON 事件
- 音频流结束表示本次音频产出结束

超时要求：

- `stream_first_chunk_timeout`
  - 建立 `/audio` 连接后，在规定时间内收不到首个 `PCM` 字节则失败
  - 建议初值：`3000` 到 `5000 ms`

- `stream_idle_timeout`
  - 已经收到过音频后，中间长时间没有新 chunk 则失败
  - 建议初值：`5000` 到 `8000 ms`

未就绪行为：

- 若 session 已存在，但 producer 还没准备好首个可消费音频块，第一版允许 `/audio` 阻塞等待首包
- 服务端不要求客户端轮询 `/audio`
- 客户端拿到 `audio_stream_url` 后可直接建立连接
- 服务端行为二选一：
  - 收到首个音频 chunk 后开始 `200 chunked` 输出
  - 命中 `stream_first_chunk_timeout` 后，本次失败

实现建议：

- 第一版尽量不要做“客户端反复请求 `/audio` 直到 ready”
- `session_not_ready` 保留为实现保护错误码，不作为主路径依赖

单消费者规则：

- 第一个成功连接 `/audio` 的客户端获得消费权
- 后续再连接同一 session 的 `/audio`，直接失败
- 若首个消费者断开，第一版直接结束该 session 的音频消费
- 第一版不支持断线重连续播

session 生命周期：

- `done` / `failed` 后，session 元数据至少保留 `15 min`
- 音频 buffer 在消费结束或失败后尽快释放
- 过期后统一返回 `session_not_found`
- 第一版不要求过期后继续保留可消费音频

## 4. Session 状态机

### 4.1 状态集合

- `accepted`
- `running`
- `done`
- `failed`

### 4.2 step 集合

- `accepted`
- `asr`
- `retrieval`
- `llm`
- `tts`
- `streaming`
- `done`
- `failed`

正常路径：

`accepted -> asr -> retrieval -> llm -> tts -> streaming -> done`

实现语义补充：

- `tts` 表示已开始产出首段音频
- `streaming` 表示首段音频已开始对外输出
- 第一版允许 `tts` 与 `streaming` 在实现层重叠进行
- 不能把它实现成“先完整做完全部 TTS，再统一开始 streaming”

`final_reason` 约定：

- `completed_answer`
- `completed_reject`
- `failed`

## 5. 错误码约定

通用错误：

- `invalid_request`
- `empty_audio_body`
- `audio_too_large`
- `unsupported_audio_format`
- `session_not_found`
- `session_not_ready`
- `audio_consumer_exists`
- `internal_error`

ASR 阶段：

- `asr_not_configured`
- `asr_timeout`
- `asr_request_failed`
- `asr_empty_text`

LLM 阶段：

- `llm_not_configured`
- `llm_stream_timeout`
- `llm_stream_failed`
- `llm_empty_output`

TTS / 流式阶段：

- `tts_not_configured`
- `tts_stream_timeout`
- `tts_stream_failed`
- `tts_empty_audio`
- `stream_first_chunk_timeout`
- `stream_idle_timeout`
- `stream_write_failed`

## 6. 音频流消费约束

服务端：

- Producer 负责持续向 session buffer 投递 PCM chunk
- `GET /audio` 负责从 session buffer 读取并输出
- 第一版 session 只支持单消费者

session buffer 内部语义至少包含：

- 有数据可读
- 正常 `EOF`
- 失败 `EOF`

元数据与清理语义：

- `GET /sessions/{id}` 在 session 未过期前可继续查询
- `GET /audio` 在消费结束且资源已释放后，不保证可再次获取音频
- session 过期后，`GET /sessions/{id}` 与 `GET /audio` 都统一返回 `session_not_found`

ESP 端：

- 使用独立流式播放器，不复用现有整包 `WAV` 下载逻辑
- 播放器固定消费 `16000 Hz / 16-bit / mono`
- 字节序固定按 `little-endian` 解释
- 第一版不做流内格式探测
- 若响应头和预期不一致，直接失败

## 7. TTFT 与阶段性验收

第一版核心指标：

- `TTFT <= 3s` 作为目标值
- 能明显早于 `v2` 出声
- 能稳定输出完整一轮音频

建议记录：

- `asr_ms`
- `retrieval_ms`
- `first_llm_chunk_ms`
- `first_tts_chunk_ms`
- `first_audio_byte_ms`
- `done_ms`

建议固定 `trace` 字段名，不要按 provider 差异改名。

建议的最小 `trace` 字段：

- `asr_ms`
- `retrieval_ms`
- `first_llm_chunk_ms`
- `first_tts_chunk_ms`
- `first_audio_byte_ms`
- `done_ms`

## 8. 最小日志字段

服务端最小日志建议固定：

- `session_id`
- `device_id`
- `request_bytes`
- `audio_duration_ms`
- `status`
- `step`
- `final_reason`
- `error_code`
- `asr_ms`
- `retrieval_ms`
- `first_llm_chunk_ms`
- `first_tts_chunk_ms`
- `first_audio_byte_ms`
- `done_ms`

ESP 端最小日志建议固定：

- `session_id`
- `post_start_ms`
- `post_done_ms`
- `audio_connect_ms`
- `first_audio_byte_local_ms`
- `playback_start_ms`
- `playback_end_ms`
- `http_status`
- `error_code`

## 9. 第一版不做的内容

- 自动回退到 `v2`
- 浏览器或 PC 端协议适配
- 客户端上传参考音色
- 多音色切换
- 中断续说
- 真正双向实时会话
- token 级逐字合成

## 10. 文本切片与拒答约束

第一版建议把切片规则写死为“最短 + 最长”双阈值：

- 最短阈值：`8` 到 `12` 字才允许切
- 最长阈值：`30` 到 `40` 字必须强制切一次
- 若已经超过最长缓存长度，即使未遇到句末标点，也必须强制切片

原因：

- 避免 LLM 长时间不出句号导致 `TTS` 一直起不来
- 避免 `TTFT` 被单次长句拖垮

拒答约束：

- 第一版 `v3` 对拒答也必须走 `TTS`
- 若命中当前业务拒答逻辑，例如“佛说不可曰”，应作为正常完成处理
- 此时建议返回：
  - `status=done`
  - `final_reason=completed_reject`

## 11. 对实施方案的直接影响

1. `v3` 音频输出固定为裸 `PCM`，不要再以 `WAV` 为默认假设。
2. `v3` 第一版失败直接报错，不做自动回退。
3. `Stage 0` 必须先验证 provider 是否真的支持“文本流入 + 音频流出”的最小闭环。
