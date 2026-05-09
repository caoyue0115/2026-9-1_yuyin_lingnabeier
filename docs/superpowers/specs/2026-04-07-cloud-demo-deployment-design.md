# 20260407 Cloud Demo Deployment Design

**Goal:** 在阿里云服务器 `OLD_PUBLIC_ENTRY_DISABLED` 上部署一个面向 ESP32-S3 Demo 的云端语音对话编排服务，先用假 ASR 打通 `上传 -> 入队 -> RAG -> LLM -> TTS -> 轮询 -> 播放` 全链路。

**Scope:** 本设计仅覆盖 Demo 首轮部署与运行边界，不包含 HTTPS、Nginx、真实 ASR、复杂鉴权、日志脱敏和生产级安全治理。

## 1. Deployment Target

- 服务器：`OLD_PUBLIC_ENTRY_DISABLED_SSH`
- 服务器角色：当前 Demo 部署目标，同时也是未来 ESP 对话产品服务器
- 项目目录：`/app/religion_demo_20260407`
- 对外访问方式：`IP + HTTP`
- 运行方式：`docker compose`

## 2. First-Round Architecture

首轮采用三组件结构：

- `api`：FastAPI 服务，对外提供上传、查询、音频下载、健康检查接口
- `worker`：RQ worker，异步执行任务流水线
- `redis`：任务队列与状态协作

设计原则：

- API 只负责接收请求、保存上传文件、创建任务并立即返回 `task_id`
- 长耗时步骤全部放入 worker，避免 ESP HTTP 长连接超时
- 任务与结果元数据使用 SQLite 持久化
- 生成音频与上传原始音频都保存在服务器本地磁盘

## 3. Audio Contract

ESP 上传音频的首轮规范冻结如下：

- Content-Type：`application/octet-stream`
- 原始格式：PCM
- 采样率：`16kHz`
- 位宽：`16-bit`
- 声道：`mono`
- 字节序：`little-endian`

服务端行为：

- 接收原始 PCM 字节流
- 从请求头或默认配置读取音频参数
- 将原始流封装为标准 WAV 文件后落盘
- 后续流水线统一消费封装后的 WAV

首轮目标是兼容 Seeed Studio 官方示例风格的上传方式，因此服务端以“接收原始 PCM，云端封装 WAV”为基线。

## 4. API Contract

### 4.1 `POST /api/v2/tasks`

职责：

- 接收 ESP 上传的原始 PCM 音频
- 保存输入文件
- 创建任务记录
- 推入 Redis 队列
- 立即返回 `accepted + task_id`

返回示例：

```json
{
  "status": "accepted",
  "task_id": "uuid",
  "received_at": "2026-04-07T12:00:00Z"
}
```

### 4.2 `GET /api/v2/tasks/{task_id}`

职责：

- 返回任务状态与结果

处理中示例：

```json
{
  "task_id": "uuid",
  "status": "running",
  "step": "tts",
  "progress": 0.8
}
```

完成态必须返回：

- `question_text`
- `answer_text`
- `audio_url`
- `references`
- `trace`

完成态示例：

```json
{
  "task_id": "uuid",
  "status": "done",
  "question_text": "什么是无相",
  "answer_text": "离执著诸相，观诸法性空。",
  "audio_url": "http://<CURRENT_BASE_URL>/api/v2/audio/uuid.wav",
  "references": [
    {
      "source_title": "金刚经.md",
      "snippet": "凡所有相，皆是虚妄。若见诸相非相，即见如来。",
      "score": 0.81
    }
  ],
  "trace": {
    "retrieval_ms": 180,
    "llm_ms": 1400,
    "tts_ms": 2100,
    "total_ms": 3900
  }
}
```

若 TTS 失败但文本已成功，完成态仍为：

```json
{
  "task_id": "uuid",
  "status": "done",
  "question_text": "什么是无相",
  "answer_text": "离执著诸相，观诸法性空。",
  "audio_url": null,
  "tts_status": "failed",
  "references": [],
  "trace": {
    "retrieval_ms": 180,
    "llm_ms": 1400,
    "tts_ms": 800,
    "total_ms": 2500
  }
}
```

### 4.3 `GET /api/v2/audio/{filename}`

职责：

- 提供音频下载
- `audio_url` 返回绝对地址，格式固定为：
  - `http://<CURRENT_BASE_URL>/api/v2/audio/<filename>.wav`

### 4.4 `GET /healthz`

职责：

- 返回 API 与依赖可用性

首轮至少覆盖：

- `api`
- `redis`
- `sqlite`
- `llm`
- `tts`

## 5. Pipeline Design

首轮任务流水线冻结为：

`Upload PCM -> Save WAV -> Enqueue -> Fake ASR -> RAG -> LLM -> TTS -> Save Audio -> Poll Result`

### 5.1 Fake ASR

为了最快打通首轮 Demo，全量上传音频都先映射为固定识别文本：

`什么是无相`

这意味着首轮不依赖真实 ASR，也不根据上传内容变化结果。上传动作主要用于验证 ESP 与云端的音频传输、任务流转和结果回放。

### 5.2 RAG

知识库来源：

- 仅上传本地目录 [data/buddhism](/home/aitopia/Engineering_Projects/20260404_宗教对话大模型/data/buddhism) 中现有佛学文档

云端知识库原则：

- 文档上传到服务器新项目目录下的 `data/buddhism/`
- 云端独立构建索引
- 不复用 WSL 侧索引文件

检索策略：

- 基于首轮本地 RAG 经验迁移
- 先使用现有的切块和检索逻辑作为默认实现
- 返回 Top 2 证据片段给调用方和 LLM

### 5.3 LLM

- 模型名正式冻结为：`qwen-max-latest`
- 用途：基于检索证据生成佛学回答

业务规则冻结为：

- 如果检索证据不足，固定回答：`佛说不可曰`
- 证据足够时，才进入正常生成

### 5.4 TTS

当前唯一已验证参数：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com`
- `DASHSCOPE_TTS_MODEL=qwen3-tts-vc-2026-01-22`
- `TTS_VOICE=qwen-tts-vc-rulaivc04060251-voice-20260406155234264-4a78`

首轮默认目标：

- 对 LLM 返回文本做语音合成
- 结果保存为可下载音频文件

## 6. Runtime and Storage Layout

服务器项目目录建议结构：

```text
/app/religion_demo_20260407/
  src/
  scripts/
  deploy/
  data/
    incoming/
    output/
    buddhism/
    logs/
  docker-compose.yml
  .env
```

说明：

- `data/incoming/`：保存上传后封装出的 WAV
- `data/output/`：保存 TTS 输出音频
- `data/buddhism/`：知识库原文
- `data/logs/`：应用日志
- `SQLite`：保存在项目 `data/` 目录中

## 7. Container Strategy

首轮部署镜像基线冻结为：

- `python:3.11-slim`

原因：

- 启动成本低
- 与当前 Python 技术栈兼容
- 适合快速构建 Demo

首轮不引入：

- `Nginx`
- `HTTPS`
- `Docker Swarm`
- `Kubernetes`

## 8. Environment Variables

首轮至少包含以下环境变量：

```bash
APP_ENV=prod
HOST=0.0.0.0
PORT=8010

REDIS_URL=redis://redis:6379/0
SQLITE_PATH=./data/tasks.db

LLM_PROVIDER=dashscope
LLM_MODEL=qwen-max-latest

DASHSCOPE_API_KEY=...
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com
DASHSCOPE_TTS_MODEL=qwen3-tts-vc-2026-01-22
TTS_VOICE=qwen-tts-vc-rulaivc04060251-voice-20260406155234264-4a78

MAX_AUDIO_SECONDS=8
MAX_UPLOAD_MB=3
FAKE_ASR_TEXT=什么是无相
PUBLIC_BASE_URL=http://<CURRENT_BASE_URL>
```

说明：

- 当前只确认过 TTS 参数可用
- LLM 与后续真实 ASR 的 DashScope 兼容性仍需上线后验证

## 9. Acceptance Criteria

首轮 Demo 验收以“链路打通”为主，标准如下：

- ESP 上传后快速获得 `task_id`
- API 不阻塞等待模型返回
- 轮询能看到完整状态变化：
  - `accepted -> running -> done`
  - 或 `accepted -> running -> failed`
- 假 ASR 文本固定为 `什么是无相`
- RAG 能完成检索
- LLM 能调用 `qwen-max-latest`
- TTS 能生成音频并返回绝对 `audio_url`
- 若 TTS 失败，仍能看到文本结果与 `tts_status=failed`

## 10. Explicitly Deferred

以下内容明确延后，不纳入本轮首发：

- 真实 ASR 接入
- HTTPS
- Nginx
- 鉴权和签名
- 日志脱敏
- 高并发压测
- 多节点部署
- 生产级监控告警

## 11. Risks and Follow-Up

当前已知风险：

- 仅 TTS 参数被实际尝试过，LLM 侧仍需实测
- `python:3.11-slim` 上安装 FAISS 及相关依赖可能需要额外系统包
- 服务器首次构建索引时耗时可能较高
- 首轮没有真实 ASR，语音输入质量问题会被暂时隐藏

后续顺序建议：

1. 先完成首轮假 ASR 闭环
2. 再接入真实 ASR
3. 再补 Nginx/HTTPS
4. 最后做压测与安全收口
