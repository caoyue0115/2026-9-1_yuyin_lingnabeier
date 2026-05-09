# DashScope ASR Integration Design

**Goal:** 将当前云端 Demo 的假 ASR 替换为 DashScope 文件识别 ASR，使上传的 PCM/WAV 真正参与 `ASR -> RAG -> LLM -> TTS` 链路。

**Scope:** 本设计仅覆盖现有 `20260407` 云端 Demo 服务内的 ASR 接入，不引入流式识别、多 ASR 提供方抽象或保留假 ASR 回退模式。

## 1. Current State

当前 worker 在 [pipeline.py](/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/workers/pipeline.py) 中直接将 `question_text` 固定为 `什么是无相`。这使得上传音频目前只验证了传输、入队和后续生成链路，没有参与真实语音识别。

## 2. Decision

本次采用单一路径：

- 直接接入 DashScope 文件 ASR
- 移除 `FAKE_ASR_TEXT` 驱动的假 ASR 逻辑
- 不保留 `fake/real` 双模式切换

这样做的理由：

- 当前设备上传模式是“一次性上传 5 秒 PCM”，天然适合文件识别
- 当前阶段目标是尽快形成真实闭环，而不是保留演示级回退分支
- 直接路径更利于问题暴露，后续排障更真实

## 3. Data Flow

新的任务流水线将变为：

`Upload PCM -> Save WAV -> Enqueue -> DashScope ASR -> RAG -> LLM -> TTS -> Save Audio -> Poll Result`

详细流程：

1. API 接收原始 PCM，按既定参数封装成 WAV 文件。
2. worker 读取本地 WAV 文件。
3. worker 调用 DashScope 文件 ASR。
4. ASR 返回识别文本，写入 `question_text`。
5. `question_text` 进入现有 RAG。
6. 若检索证据不足，返回 `佛说不可曰`。
7. 若证据足够，进入 LLM 与 TTS。

## 4. Interface Changes

现有 HTTP 接口保持不变：

- `POST /api/v2/tasks`
- `GET /api/v2/tasks/{task_id}`
- `GET /api/v2/audio/{filename}`
- `GET /healthz`

变化只体现在结果内容：

- `question_text` 不再固定，而是返回真实 ASR 文本
- `trace` 新增 `asr_ms`
- 失败场景将出现 `asr_*` 错误码

## 5. Provider Design

新增一个专门的 ASR 提供层文件：

- `src/providers/asr.py`

职责：

- 读取本地 WAV 文件
- 按 DashScope 文件识别接口组装请求
- 解析识别结果为纯文本
- 返回统一错误

不做的事：

- 不在本轮引入多 provider 抽象
- 不支持实时流式识别
- 不在本轮做长音频分段拼接

## 6. Configuration Changes

移除：

- `FAKE_ASR_TEXT`

新增建议配置：

```bash
ASR_PROVIDER=dashscope
ASR_MODEL=paraformer-realtime-v2
ASR_TIMEOUT_SECONDS=30
```

说明：

- `DASHSCOPE_API_KEY` 与 `DASHSCOPE_BASE_URL` 继续复用当前配置
- 若 DashScope 文件识别接口需要与 `ASR_MODEL` 不同的模型名，最终以实际可用模型为准

## 7. Error Handling

新增 ASR 错误码规范：

- `asr_request_failed`
- `asr_timeout`
- `asr_empty_text`
- `asr_http_<status>`
- `asr_invalid_response`

行为规则：

- ASR 失败时任务状态标记为 `failed`
- 不进入 RAG / LLM / TTS
- `trace` 中保留已完成阶段耗时

## 8. Health Check

`/healthz` 中的 `llm`、`tts` 之外，建议加入：

- `asr`

首轮以“配置存在且接口可调用”为最小健康标准，不额外做上传音频样本的主动探测。

## 9. Testing Strategy

验收采用真实音频：

1. 上传一段 5 秒左右中文佛学问题 PCM。
2. 轮询至完成态。
3. 验证：
   - `question_text` 为真实识别文本
   - `trace.asr_ms` 存在
   - `references` 存在
   - `answer_text` 存在
   - `audio_url` 可下载

失败验收：

1. 上传损坏或空音频。
2. 验证任务进入 `failed`。
3. 返回的 `error_code` 属于 `asr_*` 范围。

## 10. Risks

- DashScope 文件 ASR 的具体接口路径、模型名、返回结构需要以实测为准
- PCM 封装出的 WAV 若头部不符合 ASR 期望，可能导致识别失败
- 5 秒短音频在安静环境与嘈杂环境中的识别效果会有差异

## 11. Out of Scope

以下内容明确不纳入本轮：

- 多 ASR 提供方抽象
- 假 ASR 回退开关
- 实时流式识别
- 音频前处理降噪/增益
- 多段长音频切片识别
