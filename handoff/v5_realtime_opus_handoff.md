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

## 2026-05-09 P0 实验接口进展

已新增 v5 第一阶段 PC 模拟器和云端实验接口：

- 设计文档：`docs/superpowers/specs/2026-05-08-v5-opus-uplink-design.md`
- 服务端接口：`POST /api/v5/realtime/opus-sessions`
- PC 模拟脚本：`scripts/opus_uplink_smoke.py`
- 测试：`tests/test_opus_uplink.py`

协议口径：

- 外层复用 framed-v1：`4 bytes sequence + 4 bytes payload length + payload`
- payload 复用现有 Opus provider 输出：`2 bytes opus packet length + opus packet`
- PC 模拟器要求输入 WAV 为 16 kHz / 16-bit / mono
- `X-Original-Pcm-Bytes` 用于裁剪 Opus 最后一帧补零产生的尾部静音

本地 smoke：

```bash
python scripts/opus_uplink_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --max-polls 80
```

关键结果：

| 指标 | 结果 |
| --- | ---: |
| endpoint HTTP | 202 Accepted |
| uplink_frame_count | 79 |
| uplink_opus_bytes | 13415 |
| uplink_pcm_bytes | 150156 |
| uplink_compression_ratio | 11.193 |
| reconstructed_audio_ms | 4692 |
| opus_decode_ms | 5 |

后续 realtime session 当前失败在 `asr_not_configured`，原因是 v5 本地环境未配置 DashScope ASR 凭据；Opus 上行接收、解析、解码和 WAV 重建已进入业务流程。

验证结果：

- `python -m pytest -q`：104 passed, 1 warning

下一步：

1. 在 v5 本地 `.env` 配置与 v3 同口径的 DashScope ASR/LLM/TTS 最小凭据后，重跑 `opus_uplink_smoke.py`，采集完整 ASR/RAG/LLM/TTS trace。
2. 若完整 session 成功，再跑 9 条佛学 WAV 对比原 PCM 上传与 Opus 上行的上传体积、解码耗时和端到端指标。
3. 仍不接板端；等 PC 模拟矩阵稳定后，再设计 ESP-VoCat v1.2 的上行迁移。
