# Disney Voice Assistant Demo

基于 ESP32-S3 与 ESP-VoCat V1.0 圆屏整机的内部演示版兔朱迪语音助手。项目沿用原仓库已经验证过的录音、唤醒、WebSocket、OTA 和音频播放框架，只替换产品人设、知识库、问答路由、显示交互与部署方式。

> 本项目是内部技术 Demo，不是 Disney 官方产品，也不应对外发布角色声音或受版权保护的视觉素材。

## 首版行为

- 开机直接进入角色动画界面；当前代码内置可替换的动画占位层，正式素材收到后再替换。
- 语音交互只由唤醒词“小明同学”启动。
- 触摸只在熄屏时点亮屏幕；亮屏状态下触摸不执行任何动作，也不会开始录音。
- 无操作 30 秒降为 20% 亮度，60 秒背光关闭；触摸或唤醒词立即恢复亮度。
- 角色身份固定为兔朱迪（朱迪·霍普斯），不会切换或冒充玲娜贝儿、米奇等其他角色。
- 《疯狂动物城》人物、城市与案件按朱迪亲历的核心设定回答；尼克固定称为警察搭档，不扩写未经官方确认的关系。
- 其他迪士尼角色和故事走本地 RAG，并使用“我听说过”或“好像有这么个故事”等听闻语气介绍，不假装亲历。
- 普通静态闲聊由文本千问回答。
- 天气、实时票价、营业时间、排队和客流等动态问题在首版友好拒绝，并提示查看官方 App 或官网。
- 会话只保留当前连接内的短期上下文：最多 4 轮，重连或服务重启后清空。

## 架构

```text
“小明同学”
  -> ESP32 录音
  -> ASR
  -> 问题路由
       -> Disney 本地 RAG
       -> 普通静态文本 LLM
       -> 动态信息友好拒绝
  -> 文本千问流式生成
  -> Qwen Realtime TTS
  -> ESP32 边收边播
```

这里的 Realtime 只用于流式 TTS，不是端到端 Qwen Audio Realtime，因此 RAG 仍然位于 LLM 前并可独立验证。

## 目录

- `src/`：FastAPI、ASR、RAG、文本 LLM、TTS 与 v6 会话服务。
- `data/disney/crawled/`：从 Disney 官方允许抓取的页面保存的原始溯源资料，不直接进入线上索引。
- `data/disney/curated/`：核验后、带来源链接和人设范围标记的中文事实，是线上 RAG 的知识来源。
- `config/disney_sources.json`：官方来源白名单。
- `config/asr_hotwords.disney.json`：Disney 角色 ASR 热词。
- `esp_idf_demo/`：ESP32-S3 / ESP-VoCat V1.0 固件。
- `deploy/intern2/`：无管理员权限的开发机部署脚本。

## 本地后端

建议在 Linux 或 WSL 使用 Python 3.11：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/crawl_disney_knowledge.py
python -m src.rag.ingest
uvicorn src.app:app --host 0.0.0.0 --port 18124
```

没有 `DASHSCOPE_API_KEY` 时可以完成代码、爬虫、索引和接口结构验证，但不能完成真实 ASR/LLM/TTS 闭环。

## Disney 知识库

刷新知识库：

```bash
python scripts/crawl_disney_knowledge.py
python -m src.rag.ingest
```

爬虫仅允许访问 `config/disney_sources.json` 中配置的 Disney 官方域名并检查 robots.txt。动态渲染或禁止抓取的页面不会被绕过。抓取原文只用于溯源，不直接建立线上索引；核验后的中文事实保存在 `data/disney/curated/`，每条都保留官方来源 URL，并标记为 `zootopia_core` 或 `disney_hearsay`。

创建 ASR 热词表：

```bash
python scripts/create_asr_vocabulary.py
```

脚本会输出可写入 `.env` 的 `ASR_VOCABULARY_ID`。

## 声音样本

收到内部演示用的兔朱迪声音样本后，将至少 24 kHz 的 WAV 放到：

```text
data/voice_samples/judy_demo.wav
```

然后执行：

```bash
python scripts/create_realtime_tts_voice.py
```

把返回的 `REALTIME_TTS_VOICE` 写入服务端 `.env`。声音样本和生成的 voice ID 不提交到仓库。

## 设备端

设备端目标为 ESP32-S3、16 MB Flash、8 MB PSRAM、ESP-VoCat V1.0 音频与 360×360 圆屏。当前 Windows 串口为 `COM7`。构建和刷机说明见 [esp_idf_demo/README.md](esp_idf_demo/README.md)。

## 开发机部署

目标开发机：

```text
ssh -p 2223 intern2@210.22.71.130
```

部署目录默认为 `/home/intern2/projects/disney-voice-assistant`，服务端口默认为 `18124`，不需要 sudo 或 Docker 权限。详情见 [deploy/intern2/README.md](deploy/intern2/README.md)。
