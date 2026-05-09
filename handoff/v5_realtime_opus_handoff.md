# v5 Realtime Opus Handoff

日期：2026-05-08

## 项目定位

本目录是 v5 独立开发线，目标是在 v3 稳定基线上验证：

- Opus 压缩上行
- framed-v1 流式上传
- 云端接收、解码、聚合音频
- 后续接入真正流式 ASR

v5 的目的不是替换 v3，而是解决 v3 当前体感首字延迟中“录完整段 PCM 后再上传”的结构性问题。

## 路径

```text
/home/aitopia/Engineering_Projects/repos/20260508_v5_realtime_opus
```

远端仓库：

```text
git@github.com:675401943/20260508_v5_realtime_opus.git
```

## 来源

v5 由 v3 当前稳定目录复制必要内容而来：

```text
/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
```

复制时已排除：

- `.env`
- `.venv`
- `.pytest_cache`
- `__pycache__`
- `esp_idf_demo/build`
- `esp_idf_demo/managed_components`
- `tmp`
- `data/incoming`
- `data/output`
- `data/logs`
- 历史交付包
- 大音频素材

## 当前基线

保留的核心内容：

- 云端：`src/`
- 测试：`tests/`
- 脚本：`scripts/`
- 配置：`config/`
- 知识库：`data/buddhism/`
- 索引：`indices/`
- 板端最小工程：`esp_idf_demo/main`、`esp_idf_demo/spiffs`
- 文档：`20260409_流式传输/`、`docs/`、`handoff/`

当前 v3 已知事实：

- v3 不是从头流式上行。
- v3 当前链路是板端录完整段 PCM 后上传，云端再走 ASR + LLM + TTS 流式下行。
- 下行 Opus + framed-v1 已打通过。
- v3 体感首字延迟约 4 到 6 秒。

当前 v4 已知事实：

- 火山 ASR 在同音频时长测试中更快。
- v4 short 在同音频时长下首音频和 total 已优于 v3。
- 但 v4 引入新云端代理、凭据、TTS 和板端适配风险。
- v4 暂作为备选 provider，不作为当前主线替换 v3。

## v5 第一阶段目标

先做 v3 输入链路升级 PoC，不碰线上服务。

阶段 1：

```text
板端/模拟器 Opus framed-v1 上行
    -> 云端接收 framed Opus
    -> 云端解码为 PCM/WAV
    -> 聚合完整音频
    -> 复用现有 transcribe_wav_result
    -> 复用现有 LLM/TTS 下行
```

阶段 1 不要求真正 ASR partial，不要求 Prefill，不要求用户打断。

阶段 2：

```text
上行 chunk
    -> 云端 DashScope paraformer-realtime-v2 websocket
    -> ASR partial/final
    -> final text 启动 LLM
```

阶段 3：

在 ASR partial 稳定后，再讨论 LLM 提前启动、Prefill、打断和多轮。

## 关键指标

v5 必须新增或采集以下指标：

- `touch_to_first_uplink_chunk_ms`
- `uplink_first_chunk_to_server_ms`
- `record_end_to_upload_done_ms`
- `uplink_audio_bytes`
- `uplink_opus_bytes`
- `uplink_compression_ratio`
- `asr_start_ms`
- `asr_final_ms`
- `first_llm_chunk_ms`
- `first_tts_chunk_ms`
- `first_audio_byte_ms`
- `first_audio_byte_local_ms`

第一阶段重点判断：

- 上行数据量是否显著下降。
- 弱网下上传尾部等待是否下降。
- 云端是否能稳定还原音频。
- 不破坏 v3 现有下行播放稳定性。

## 开发边界

- 不改 v3 原目录。
- 不部署 greenunion-sh。
- 不访问旧公网生产入口。
- 不提交 `.env`、真实凭据、音频运行产物、trace、payload。
- 不直接让板端持有云端供应商凭据。
- 破坏性操作、线上部署、容器重建必须先确认。

## 下一步建议

1. 初始化 v5 独立 git 仓库并推送。
2. 跑现有 v3 测试，确认复制基线可用。
3. 新增上行 framed-v1 协议设计文档。
4. 先写 PC 模拟器：读取 WAV，编码/封包/上传 Opus framed-v1。
5. 云端新增实验接口，接收并解码上行 Opus。
6. 成功后再迁移到 ESP-VoCat 板端。
