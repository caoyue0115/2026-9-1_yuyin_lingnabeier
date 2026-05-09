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

## 2026-05-09 本地凭据联调结果

已按授权从 v3 本地 `.env` 复制最小必要变量到 v5 本地 `.env`。`.env` 仍由 `.gitignore` 忽略，未入库。复制范围：

- DashScope API Key 与 base URL
- ASR provider/model/timeout
- LLM provider/model/temperature/max tokens
- TTS 与 realtime TTS model/voice/language/instructions
- RAG top_k、BM25 权重、召回阈值、embedding 维度
- v5 本地 `PUBLIC_BASE_URL=http://127.0.0.1:8010`

未复制 v3 公网 `PUBLIC_BASE_URL`。v3 `.env` 中没有 `ASR_LANGUAGE_HINTS`、`ASR_VOCABULARY_ID`、`REALTIME_TTS_WARMUP_ENABLED`，v5 使用代码默认值。

本轮 smoke：

```bash
python scripts/opus_uplink_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --max-polls 100 --status-timeout 20 --submit-timeout 20
```

结果：完整跑通，session `64fb5f06-e831-448e-b68d-ed81b91600b9`，`status=done`，`final_reason=completed_answer`。

| 指标 | 结果 |
| --- | ---: |
| endpoint HTTP | 202 Accepted |
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

ASR 文本：

```text
情解释阿弥陀佛是什么意思？
```

回答文本：

```text
阿弥陀佛是西方极乐世界教主的名号，意为无量光寿。此佛号包含光明与寿命的圆满，指引众生往生净土。
```

RAG 回放结果（同一 ASR 文本，本地 retriever 复算）：

| rank | score | source_title |
| ---: | ---: | --- |
| 1 | 0.7802826136942801 | ZT02_阿弥陀佛是谁_大白话版.md |
| 2 | 0.55 | ZT03_阿弥陀佛名号与无量光寿.md |

注意：当前 session trace 只直接返回 `retrieval_ms`，top_score/top docs 是用同一 ASR 文本回放 retriever 得到的可复现补充证据。

验证：

- `python -m pytest -q`：104 passed, 1 warning
- 本地 uvicorn 已停止

## 2026-05-09 真流式 Opus 上行进展

已新增 v5 真流式上行实验链路：

- 设计文档：`docs/superpowers/specs/2026-05-09-v5-streaming-opus-uplink-design.md`
- 服务端接口：`WS /api/v5/realtime/opus-stream`
- PC 模拟脚本：`scripts/opus_uplink_stream_smoke.py`
- 测试更新：`tests/test_opus_uplink.py`

本轮只验证上行流式，不接 ASR partial，不接火山 ASR，不改 ASR provider。既有完整 body 基线 `POST /api/v5/realtime/opus-sessions` 行为保持不变。

WebSocket 协议：

- binary message 使用同一套 framed-v1：`4 bytes sequence + 4 bytes payload length + payload`
- payload 继续为 `2 bytes opus packet length + opus packet`
- PC 模拟器默认一帧一个 binary message，并按真实时间节奏发送
- 客户端最后发送 `{"type":"end"}`
- 服务端逐帧返回 `ack`，完成后返回 `done`

新增依赖：

- `websocket-client`：PC smoke 脚本使用
- `websockets`：uvicorn 本地 WebSocket server 支持

本地 smoke：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime
```

结果：流式上行通过，服务端 ack 从 frame 1 持续增长到 frame 79，end 后重建音频。本轮没有启动 ASR/RAG/LLM/TTS。

| 指标 | 结果 |
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

结论：v5 已从“完整 body 内部 framed-v1”推进到“真正 WebSocket 流式上行”。服务端可以边收边解码/聚合，Opus 压缩率与完整 body 基线一致，解码耗时仍很低。下一步建议跑 `--no-realtime` 快发、弱网模拟和 `--run-session-after-stream` 完整链路对照，再评估 ESP32-S3 上行迁移。

验证：

- `python -m pytest -q`：108 passed, 1 warning
- 本地 uvicorn 已停止

## 2026-05-09 P1：流式 Opus 接 DashScope Realtime ASR

已在 `WS /api/v5/realtime/opus-stream` 增加可选 ASR/full-chain 模式。默认 P0 行为保持不变；只有客户端先发：

```json
{"type":"start","run_asr":true,"run_full_chain":true}
```

才会启用 DashScope realtime ASR。仍不接火山 ASR，不做 ASR partial 提前 LLM，不做打断。

新增/更新：

- `src/providers/realtime_asr.py`
- `src/api/realtime.py`
- `src/services/realtime_session.py`
- `src/models/realtime.py`
- `src/storage/realtime_store.py`
- `scripts/opus_uplink_stream_smoke.py`
- `tests/test_opus_uplink.py`
- `tests/test_realtime_api.py`
- `docs/superpowers/specs/2026-05-09-v5-streaming-opus-uplink-design.md`

实现口径：

- `realtime_asr.py` 复用 DashScope SDK `Recognition.start/send_audio_frame/stop`，模型仍为 `paraformer-realtime-v2`。
- opus-stream 每解一个 Opus packet 就把 PCM chunk 送入 ASR adapter。
- ASR partial 只回传/记录，不触发 LLM。
- ASR final 后，使用 final text 启动既有 RAG/LLM/TTS session，并跳过旧文件 ASR。

P0 回归：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime
```

| 指标 | 结果 |
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

P1 smoke：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --max-polls 120 --status-timeout 20 --timeout 30
```

| 指标 | 结果 |
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

ASR partial：有。示例：`情`、`请`、`请解`、`请解释。阿`、`请解释。阿弥`、`请解释。阿弥陀`。

ASR request_id：`8ae9dc6f6473490b9a8bf5370be17455`。

ASR final：

```text
情解释阿弥陀佛是什么意思？
```

full-chain session：`eeacb3be-eeac-4762-b9a0-74efed6658dd`，`status=done`，`final_reason=completed_answer`。

| trace 指标 | 结果 |
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

- P1 已证明服务端可以边收 Opus、边解码 PCM、边送 DashScope realtime ASR，并在 ASR final 后复用既有 RAG/LLM/TTS。
- 现阶段的最大问题不是 Opus 解码，而是 DashScope realtime ASR final 仍约 6.9 秒，且最终文本首字仍有错词。
- 下一步建议跑 9 条同音频矩阵，对比旧完整 WAV ASR 与新 realtime ASR 的耗时和错词率，再决定是否进入 ESP32-S3 端上行迁移。

验证：

- `python -m pytest -q`：113 passed, 1 warning
- 本地 uvicorn 已停止
