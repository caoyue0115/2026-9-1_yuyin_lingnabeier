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

## 2026-05-09 P1.5：统一时间轴 + 9 条佛学词矩阵

新增/更新：

- `scripts/v5_streaming_latency_eval.py`
- `scripts/opus_uplink_stream_smoke.py`
- `src/api/realtime.py`
- `src/services/realtime_session.py`
- `src/models/realtime.py`
- `src/storage/realtime_store.py`
- `tests/test_opus_uplink.py`
- `docs/superpowers/specs/2026-05-09-v5-streaming-latency-matrix.md`

时间轴口径：

- WebSocket done payload 新增 `client_stream_start_ms`、`client_first_frame_sent_ms`、`client_last_frame_sent_ms`、`client_end_sent_ms`、`client_done_received_ms`。
- 服务端原始 `*_abs_ms` 以 stream accept 为零点。
- 矩阵脚本输出的 `*_abs_ms` 统一减去 `first_frame_server_abs_ms`，作为“从客户端发送第一帧附近起算”的对外比较口径。
- `retrieval_done_abs_ms`、`first_llm_chunk_abs_ms`、`first_tts_chunk_abs_ms`、`first_audio_byte_abs_ms`、`done_abs_ms` 由 `stream_to_session_start_abs_ms + session 内相对耗时` 得出。

单条回归：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --max-polls 120 --status-timeout 20 --timeout 30
```

| 指标 | 结果 |
| --- | ---: |
| client_first_frame_sent_ms | 8 |
| client_last_frame_sent_ms | 4783 |
| client_end_sent_ms | 4844 |
| client_done_received_ms | 5791 |
| first_frame_server_abs_ms | 6 |
| first_pcm_to_asr_abs_ms | 6 |
| first_asr_partial_abs_ms | 2768 |
| asr_final_abs_ms | 5529 |
| retrieval_done_abs_ms | 6503 |
| first_llm_chunk_abs_ms | 8668 |
| first_tts_chunk_abs_ms | 10048 |
| first_audio_byte_abs_ms | 10048 |
| done_abs_ms | 15854 |

ASR final：

```text
情解释阿弥陀佛是什么意思？
```

9 条矩阵：

```bash
python scripts/v5_streaming_latency_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --target streaming --output /tmp/v5_streaming_latency_eval.jsonl --markdown /tmp/v5_streaming_latency_eval.md
```

| 汇总指标 | 结果 |
| --- | ---: |
| cases | 9 |
| successful | 9 |
| term_hits | 7/9 |
| mean_first_asr_partial_abs_ms | 2724.7 |
| mean_asr_final_abs_ms | 4724.3 |
| mean_first_audio_byte_abs_ms | 8482.4 |
| mean_done_abs_ms | 12982.2 |
| mean_audio_duration_ms | 14524.4 |
| mean_answer_chars | 49.1 |

| term | hit | recognized_text | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms |
| --- | --- | --- | ---: | ---: | ---: |
| 阿弥陀佛 | Y | 情解释阿弥陀佛是什么意思？ | 5242 | 9176 | 13562 |
| 四十八愿 | N | 48愿和净土宗有什么关系？ | 5061 | 8193 | 13327 |
| 净土宗 | Y | 净土宗为什么重视信愿行？ | 5667 | 10584 | 15806 |
| 无量寿经 | Y | 无量寿经讲了什么？ | 4801 | 8150 | 12525 |
| 金刚经 | Y | 金刚经的核心意思是什么？ | 3392 | 6886 | 11295 |
| 般若 | Y | 佛教里般若是什么意思？ | 3671 | 7558 | 10932 |
| 慧远 | N | 慧云大师和东林寺有什么关系？ | 4163 | 8227 | 12882 |
| 善导 | Y | 善导大师如何解释念佛？ | 4049 | 7869 | 11925 |
| 东林寺 | Y | 东林寺和净土宗有什么关系？ | 6473 | 9699 | 14586 |

阶段判断：

- P1.5 证明同一时间轴可以稳定采集；9 条均完整进入 ASR/RAG/LLM/TTS。
- ASR 佛学词命中率为 7/9。错词为“四十八愿”数字化成“48愿”，以及“慧远”错为“慧云”。
- mean 首音频约 8.5 秒，mean total 约 13.0 秒；当前未做 partial 提前 LLM，因此不是最终优化上限。
- 下一步建议补 v5 HTTP body Opus 基线和 v3 原链路同 9 条对照，再讨论是否进入 ESP32-S3 端上行迁移。

## 2026-05-09 P2：火山 ASR Provider A/B

新增可选 ASR provider，默认仍是 DashScope，不替换现有链路：

```json
{"type":"start","run_asr":true,"run_full_chain":true,"asr_provider":"dashscope"}
{"type":"start","run_asr":true,"run_full_chain":true,"asr_provider":"volcengine"}
```

新增/更新：

- `src/providers/realtime_asr.py`
- `src/api/realtime.py`
- `src/models/realtime.py`
- `src/storage/realtime_store.py`
- `scripts/opus_uplink_stream_smoke.py`
- `scripts/v5_streaming_latency_eval.py`
- `tests/test_opus_uplink.py`
- `docs/superpowers/specs/2026-05-09-v5-asr-provider-ab.md`

火山实现口径：

- 只替换 ASR，RAG/LLM/TTS 仍复用 v5 现有链路。
- 火山 ASR 是 true streaming PCM：服务端每解出一个 Opus PCM chunk，就发送到火山 `bigmodel_async`。
- Full Request 对齐 v4 成功口径：`format=pcm`、`codec=raw`、`rate=16000`、`enable_nonstream=true`。
- 凭据从 v4 本地 `.env` 复制最小变量到 v5 本地 `.env`；`.env` 已忽略，未入库。

单条火山回归：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --asr-provider volcengine --max-polls 160 --status-timeout 30 --timeout 30
```

结果：火山 ASR、RAG、LLM、TTS 全链路跑通。

| 指标 | 结果 |
| --- | ---: |
| uplink_frame_count | 79 |
| uplink_opus_bytes | 13415 |
| uplink_pcm_bytes | 150156 |
| reconstructed_audio_ms | 4692 |
| first_pcm_to_asr_abs_ms | 1542 |
| first_asr_partial_abs_ms | 4880 |
| asr_final_abs_ms | 5454 |
| first_audio_byte_abs_ms | 11413 |
| done_abs_ms | 16366 |

ASR final：

```text
请解释阿弥陀佛是什么意思？
```

9 条 A/B 矩阵：

```bash
python scripts/v5_streaming_latency_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --target streaming --provider-matrix dashscope,volcengine --output /tmp/v5_asr_provider_ab.jsonl --markdown /tmp/v5_asr_provider_ab.md --max-polls 180 --status-timeout 30 --timeout 30
```

| provider | successful | term_hits | mean_first_asr_partial_abs_ms | mean_asr_final_abs_ms | mean_first_audio_byte_abs_ms | mean_done_abs_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| dashscope | 9/9 | 7/9 | 4466.7 | 6429.8 | 11680.2 | 17160.0 |
| volcengine | 9/9 | 9/9 | 1926.9 | 3146.2 | 13884.1 | 18329.1 |

逐词结论：

- 火山 9/9 命中：阿弥陀佛、四十八愿、净土宗、无量寿经、金刚经、般若、慧远、善导、东林寺。
- DashScope 7/9 命中，错词仍是 `四十八愿 -> 48愿`、`慧远 -> 慧云`，并且“请解释”仍可能识别为“情解释”。
- 火山 ASR final 均值明显更快，但 full-chain 首音频和 total 未同步领先，主要受后续 LLM/TTS 抖动影响；`金刚经`、`善导` 两条火山 full-chain 特别慢。
- 口径注意：A/B 矩阵沿用 P1.5 的 `first_frame_server_abs_ms` 归一化；火山 provider 建连造成的首帧服务端处理延迟未进入表内。单条火山回归中该值为 `1542ms`，后续应新增 `provider_start_ms` 或 raw first-frame 字段。

阶段判断：

- P2 已证明同一 v5 streaming Opus 上行链路可以可选切换火山 ASR provider。
- 火山 ASR 在佛学专有词准确率和 ASR final 延迟上明显值得继续评估。
- 现在不建议直接替换默认 ASR；下一步应跑 ASR-only 多轮稳定性矩阵，并固定 LLM/TTS 输出长度后再做 full-chain A/B。

验证：

- `python -m pytest -q`：118 passed, 1 warning
- 本地 uvicorn 已停止

## 2026-05-09 P2.1：ASR Provider 建连预热与计时拆账

目标：拆清 ASR provider lifecycle 时间，修正火山 ASR WebSocket 建连阻塞首帧处理的问题。默认 provider 仍是 `dashscope`。

新增/更新：

- `src/api/realtime.py`
- `src/providers/realtime_asr.py`
- `src/models/realtime.py`
- `src/storage/realtime_store.py`
- `scripts/v5_streaming_latency_eval.py`
- `tests/test_opus_uplink.py`
- `docs/superpowers/specs/2026-05-09-v5-streaming-opus-uplink-design.md`
- `docs/superpowers/specs/2026-05-09-v5-asr-provider-ab.md`

实现口径：

- 收到 start control 后，如果 `run_asr=true`，服务端创建 provider 并用后台线程异步执行 `provider.start()`。
- 不再等待 provider ready 才接收首个 binary Opus frame。
- provider 未 ready 期间，服务端继续解码 Opus 为 PCM，并把 PCM chunk 暂存在内存队列。
- provider ready 后按顺序 flush 缓存 PCM，再继续边收边送。
- 缓存队列设置上限；provider ready 超时返回 `asr_provider_ready_timeout`。
- P0 不启用 ASR 时不启动 provider。

新增 lifecycle 字段：

| 字段 | 含义 |
| --- | --- |
| `provider_start_abs_ms` | 服务端发起 provider start 的时间 |
| `provider_ready_abs_ms` | provider start 完成、可接收 PCM 的时间 |
| `provider_start_duration_ms` | provider 建连/启动耗时 |
| `first_pcm_decoded_abs_ms` | 服务端解出首个 PCM chunk 的时间 |
| `first_pcm_sent_to_provider_abs_ms` | 首个 PCM chunk 实际送入 provider 的时间 |
| `first_provider_result_abs_ms` | provider 首个非空识别事件/结果时间 |
| `provider_log_id` | provider request/log id |
| `provider_error_code` | provider 层错误码 |
| `provider_error_message` | provider 层错误摘要 |

重启本地 uvicorn 后的单条回归：

| case | first_frame_server_abs_ms | provider_start_duration_ms | provider_ready_abs_ms | first_pcm_sent_to_provider_abs_ms | first_provider_result_abs_ms | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P0 no ASR | 4 | N/A | N/A | N/A | N/A | N/A | N/A | 4848 |
| DashScope | 8 | 62 | 69 | 69 | 3649 | 5604 | 9807 | 15302 |
| Volcengine | 4 | 1900 | 1904 | 1904 | 4959 | 5585 | 11882 | 17143 |

火山 ASR final：

```text
请解释阿弥陀佛是什么意思？
```

P2.1 有效 A/B 矩阵：

```bash
python scripts/v5_streaming_latency_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --target streaming --provider-matrix dashscope,volcengine --output /tmp/v5_asr_provider_ab_p21.jsonl --markdown /tmp/v5_asr_provider_ab_p21.md --max-polls 180 --status-timeout 30 --timeout 30
```

| provider | successful | term_hits | mean_provider_start_duration_ms | mean_first_pcm_sent_to_provider_abs_ms | mean_first_provider_result_abs_ms | mean_asr_final_abs_ms | mean_first_audio_byte_abs_ms | mean_done_abs_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dashscope | 9/9 | 7/9 | 70.8 | 70.6 | 2980.7 | 5590.8 | 9875.0 | 14434.4 |
| volcengine | 9/9 | 9/9 | 1831.3 | 1831.3 | 4090.2 | 4740.7 | 8625.7 | 13397.7 |

错词：

- DashScope：`四十八愿 -> 48愿`、`慧远 -> 慧云`。
- Volcengine：9 条佛学词均命中。

阶段判断：

- 火山 `first_frame_server_abs_ms` 已从 P2 单条约 `1542ms` 降到 `4ms`，provider 建连不再阻塞首帧处理。
- 火山 provider 建连仍明显慢，P2.1 矩阵均值约 `1831.3ms`；这部分现在已单独拆账。
- 在包含 provider 建连耗时后，火山 ASR final 均值仍快于 DashScope：`4740.7ms` vs `5590.8ms`，并且专有词命中率为 `9/9`。
- 本轮 full-chain 中火山 mean 首音频和 total 也优于 DashScope，但差距较小且仍受 LLM/TTS 抖动影响；不建议仅凭一次矩阵替换默认 provider。

验证：

- `python -m pytest -q`：121 passed, 1 warning
- `.env` 已由 `.gitignore` 忽略，未入库
- 凭据扫描未命中真实凭据
- 本地 uvicorn 已停止

## 2026-05-09 P2.2：ASR-only 重复矩阵

目标：排除 RAG/LLM/TTS 抖动，只比较 DashScope 与 Volcengine 在同一批 9 条佛学词音频上的 ASR-only 稳定性。默认 provider 仍是 `dashscope`，火山仍是可选 provider。

新增：

- `scripts/v5_asr_only_repeat_eval.py`
- `tests/test_opus_uplink.py` 中新增脚本参数、失败不中断、Markdown 汇总和 ASR-only 不触发 full-chain 的测试。

ASR-only 口径：

```json
{"type":"start","run_asr":true,"run_full_chain":false,"asr_provider":"dashscope"}
{"type":"start","run_asr":true,"run_full_chain":false,"asr_provider":"volcengine"}
```

服务端返回 ASR final 和 done summary；`session_started=false`，不进入 RAG/LLM/TTS。

单条 smoke：

| provider | question_text | first_frame_server_abs_ms | provider_start_duration_ms | first_pcm_sent_to_provider_abs_ms | first_provider_result_abs_ms | asr_final_abs_ms | session_started |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| dashscope | 情解释阿弥陀佛是什么意思？ | 7 | 63 | 69 | 2469 | 5304 | false |
| volcengine | 请解释阿弥陀佛是什么意思？ | 3 | 1711 | 1714 | 4934 | 5751 | false |

5 轮重复矩阵：

```bash
python scripts/v5_asr_only_repeat_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --providers dashscope,volcengine --repeats 5 --frame-ms 60 --realtime --output /tmp/v5_asr_only_repeat_eval.jsonl --markdown /tmp/v5_asr_only_repeat_eval.md
```

结果：90 条记录，0 错误，结果文件只保存在 `/tmp`，不入库。

| provider | success_count / total | term_hits / total | mean_asr_final_abs_ms | median_asr_final_abs_ms | p95_asr_final_abs_ms | mean_provider_start_duration_ms | p95_provider_start_duration_ms | mean_first_provider_result_abs_ms | p95_first_provider_result_abs_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dashscope | 45/45 | 35/45 | 4851.8 | 4492.0 | 6424.0 | 63.2 | 63.0 | 2690.1 | 3709.0 |
| volcengine | 45/45 | 45/45 | 4694.7 | 4430.0 | 5643.0 | 1412.8 | 2512.0 | 4088.9 | 5084.0 |

逐词命中：

| term | dashscope | volcengine |
| --- | --- | --- |
| 阿弥陀佛 | 5/5，稳定识别为“情解释阿弥陀佛是什么意思？” | 5/5，稳定识别为“请解释阿弥陀佛是什么意思？” |
| 四十八愿 | 0/5，稳定错为“48愿和净土宗有什么关系？” | 5/5 |
| 净土宗 | 5/5 | 5/5 |
| 无量寿经 | 5/5 | 5/5 |
| 金刚经 | 5/5 | 5/5 |
| 般若 | 5/5 | 5/5 |
| 慧远 | 0/5，稳定错为“慧云大师和东林寺有什么关系？” | 5/5 |
| 善导 | 5/5 | 5/5 |
| 东林寺 | 5/5 | 5/5 |

阶段判断：

- ASR-only 稳定性上，Volcengine 的佛学词准确率明显优于 DashScope：`45/45` vs `35/45`。
- DashScope 错词稳定复现：`四十八愿 -> 48愿`、`慧远 -> 慧云`、`请解释 -> 情解释`。
- Volcengine provider start 明显慢，均值 `1412.8ms`，p95 `2512.0ms`；但建连仍不阻塞首帧 ack。
- 计入 provider start 后，Volcengine ASR final 分布仍略优于 DashScope：mean `4694.7ms` vs `4851.8ms`，median `4430.0ms` vs `4492.0ms`，p95 `5643.0ms` vs `6424.0ms`。
- 仅从 ASR-only 数据看，Volcengine 已具备切换默认 provider 的技术依据；但默认切换前仍建议再跑固定后段输出的 full-chain 重复矩阵，确认首音频和 total 不被后段抖动抵消。

## 2026-05-09 P2.3：固定短回答 full-chain 重复矩阵

目标：固定后段 RAG/LLM/TTS 输出口径，确认切换 Volcengine ASR 后，端到端首音频和 total 不会被后段抖动抵消。默认 provider 仍是 `dashscope`，Volcengine 仍是可选 provider。

本轮新增：

- `answer_mode=short` 传入 full-chain session。
- `scripts/v5_full_chain_repeat_eval.py` 用于 9 条音频 x 2 provider x N repeats 的 full-chain 重复矩阵。
- `tests/test_llm_provider.py` 覆盖 short answer prompt 和 max token。
- `tests/test_opus_uplink.py` 覆盖 start control、WebSocket full-chain 透传、脚本参数、失败不中断和 Markdown 汇总。

短回答口径：

```text
两句话内回答，总字数不超过70字。先给直接解释，再给一句修行/理解上的补充。不输出来源话术，不长篇解释。
```

服务端 short mode 使用固定更小 `max_tokens`，并在 realtime trace 中记录 `answer_mode=short`。未显式传入时仍走默认回答策略。

单条 smoke：

| provider | question_text | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms | answer_chars | audio_duration_ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| dashscope | 情解释阿弥陀佛是什么意思？ | 5345 | 9884 | 13965 | 43 | 12800 |
| volcengine | 请解释阿弥陀佛是什么意思？ | 5482 | 10476 | 14823 | 50 | 13440 |

3 轮重复矩阵命令：

```bash
python scripts/v5_full_chain_repeat_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --providers dashscope,volcengine --repeats 3 --frame-ms 60 --realtime --answer-mode short --output /tmp/v5_full_chain_repeat_eval.jsonl --markdown /tmp/v5_full_chain_repeat_eval.md
```

结果：54 条记录，0 错误。结果文件只保存在 `/tmp`，不入库。

| provider | success_count / total | term_hits / total | mean_asr_final_abs_ms | median_asr_final_abs_ms | p95_asr_final_abs_ms | mean_first_audio_byte_abs_ms | median_first_audio_byte_abs_ms | p95_first_audio_byte_abs_ms | mean_done_abs_ms | median_done_abs_ms | p95_done_abs_ms | mean_answer_chars | mean_audio_duration_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dashscope | 27/27 | 21/27 | 4690.9 | 4601.0 | 5752.0 | 8441.1 | 8219.0 | 10298.0 | 13185.4 | 13454.0 | 15734.0 | 48.0 | 15060.7 |
| volcengine | 27/27 | 27/27 | 4692.7 | 4388.0 | 5796.0 | 8740.3 | 8501.0 | 10361.0 | 13440.5 | 13580.0 | 15438.0 | 47.1 | 14829.6 |

逐词：

| term | dashscope hit_count / repeats | dashscope recognized_text | volcengine hit_count / repeats | volcengine recognized_text |
| --- | ---: | --- | ---: | --- |
| 阿弥陀佛 | 3/3 | 情解释阿弥陀佛是什么意思？ | 3/3 | 请解释阿弥陀佛是什么意思？ |
| 四十八愿 | 0/3 | 48愿和净土宗有什么关系？ | 3/3 | 四十八愿和净土宗有什么关系？ |
| 净土宗 | 3/3 | 净土宗为什么重视信愿行？ | 3/3 | 净土宗为什么重视信愿行？ |
| 无量寿经 | 3/3 | 无量寿经讲了什么？ | 3/3 | 无量寿经讲了什么？ |
| 金刚经 | 3/3 | 金刚经的核心意思是什么？ | 3/3 | 金刚经的核心意思是什么？ |
| 般若 | 3/3 | 佛教里般若是什么意思？ | 3/3 | 佛教里般若是什么意思？ |
| 慧远 | 0/3 | 慧云大师和东林寺有什么关系？ | 3/3 | 慧远大师和东林寺有什么关系？ |
| 善导 | 3/3 | 善导大师如何解释念佛？ | 3/3 | 善导大师如何解释念佛？ |
| 东林寺 | 3/3 | 东林寺和净土宗有什么关系？ | 3/3 | 东林寺和净土宗有什么关系？ |

P2.3 判断：

- short answer 口径已固定，两个 provider 的平均回答长度和输出音频时长接近：Volcengine 平均回答少 `0.9` 字，平均音频少 `231.1ms`。
- 准确率上，Volcengine 继续明显优于 DashScope：`27/27` vs `21/27`。
- DashScope 错词稳定复现：`四十八愿 -> 48愿`、`慧远 -> 慧云`，以及非词项但影响问题自然度的 `请解释 -> 情解释`。
- 延迟上，固定后段后 Volcengine 没有取得明确端到端均值优势：mean 首音频比 DashScope 慢约 `299.2ms`，mean total 慢约 `255.1ms`；但 p95 total 略优。
- 因为输出长度已接近，首音频/total 的小差异更可能来自 provider 连接、ASR final 分布和 LLM/TTS 抖动，而不是回答变长。
- 当前证据足以支持“Volcengine 是默认 ASR provider 候选，准确率明显更好”；但不应宣称“端到端明显更快”。建议下一步用配置开关灰度切换，并保留 DashScope fallback，再跑真实人声/板端录音矩阵。

## 2026-05-09 P2.4：配置开关与 DashScope fallback

目标：把 P2.3 的结论落成可灰度的配置，不在代码层硬切默认 provider。代码默认仍安全使用 `dashscope`；v5 本地 `.env` 已设置非密钥开关：

```text
ASR_PROVIDER=volcengine
ASR_FALLBACK_PROVIDER=dashscope
```

`.env` 已由 `.gitignore` 忽略，未入库。

### 配置规则

| 来源 | 规则 |
| --- | --- |
| 代码默认 | `ASR_PROVIDER=dashscope`，`ASR_FALLBACK_PROVIDER` 为空 |
| 本地/环境变量 | 可设置 `ASR_PROVIDER=volcengine`、`ASR_FALLBACK_PROVIDER=dashscope` |
| WebSocket start config | 显式 `asr_provider` 优先于环境变量 |
| WebSocket fallback config | 显式 `asr_fallback_provider` 优先；`none` 表示禁用 fallback |

`WS /api/v5/realtime/opus-stream` 未传 `asr_provider` 时会读取 `settings.asr_provider`。如果显式传入 `asr_provider`，则覆盖环境默认。

### fallback 口径

第一版 fallback 只在 end 后发生，目的是保证可用性，不宣称仍保持实时低延迟：

1. 主 provider 真 streaming 接收 PCM。
2. 若主 provider start 失败、ready 超时、finish 失败或返回空文本，记录 primary error。
3. 若配置了 fallback provider，则用服务端已缓存/重建的 PCM 重新送入 fallback provider。
4. fallback 成功后继续现有 RAG/LLM/TTS full-chain。
5. fallback 失败且无可用文本时返回明确 error。

summary/trace 新增字段：

| 字段 | 含义 |
| --- | --- |
| `asr_primary_provider` | 本次主 provider |
| `asr_fallback_provider` | 配置的 fallback provider |
| `asr_provider_used` | 最终提供 question_text 的 provider |
| `asr_fallback_used` | 是否实际触发 fallback |
| `asr_primary_error_code` | 主 provider 错误码 |
| `asr_primary_error_message` | 主 provider 错误摘要 |

### 脚本更新

- `scripts/opus_uplink_stream_smoke.py`
  - `--asr-provider` 改为可选；不传则走服务端环境默认。
  - 新增 `--asr-fallback-provider dashscope|volcengine|none`。
- `scripts/v5_asr_only_repeat_eval.py`
  - 新增 `--asr-fallback-provider`，JSONL 记录 fallback 字段。
- `scripts/v5_full_chain_repeat_eval.py`
  - 新增 `--asr-fallback-provider`，JSONL 记录 fallback 字段。
- `scripts/v5_real_voice_eval.py`
  - 新增真实人声/板端录音矩阵脚本，默认读取 `/tmp/v5_real_voice_eval/`。

真实人声/板端录音规范见：

```text
docs/superpowers/specs/2026-05-09-v5-real-voice-eval.md
```

### P2.4 单条 smoke

使用同一条输入：

```text
/tmp/volc_asr_eval/amitabha.wav
```

需要跑两条：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --answer-mode short
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --asr-provider dashscope --answer-mode short
```

第一条不显式传 provider，用本地 `.env` 默认 `volcengine`；第二条验证 start config override 到 `dashscope`。

本轮实测结果：

| case | provider_used | fallback_used | question_text | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms | provider_start_duration_ms |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| env default | volcengine | false | 请解释阿弥陀佛是什么意思？ | 5487 | 10368 | 14993 | 1773 |
| start override | dashscope | false | 情解释阿弥陀佛是什么意思？ | 5494 | 10682 | 15959 | 61 |

补充修复：DashScope realtime adapter 以前复用了全局 `settings.asr_provider == "dashscope"` 作为配置判断。P2.4 后本地 `.env` 默认 provider 是 `volcengine`，这会导致显式 `--asr-provider dashscope` 被误判为 `asr_not_configured`。已改为 DashScope adapter 只检查 DashScope API key 与 ASR model，不再依赖全局默认 provider。

## 2026-05-10 P3：ESP32-S3 板端 Opus framed-v1 上行

本轮进入 ESP32-S3 / ESP-VoCat v1.2 板端改造。目标是把 touch 触发后的上行路径从“整段 PCM 录完后提交”改为“开口后按帧 Opus encode，再以 framed-v1 WebSocket binary frame 持续上行到 v5 云端”。

新增设计文档：

```text
docs/superpowers/specs/2026-05-10-v5-esp32-opus-uplink-design.md
```

板端配置宏：

```text
V5_OPUS_UPLINK_WS_ENABLED=1
V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO=0
V5_OPUS_UPLINK_BEHAVIOR_FALLBACK_ENABLED=1
V5_OPUS_UPLINK_FRAME_MS=60
V5_OPUS_UPLINK_ASR_PROVIDER="volcengine"
V5_OPUS_UPLINK_ANSWER_MODE="short"
V5_OPUS_UPLINK_BITRATE=24000
```

P3 初版曾默认启用旧 `/audio` fallback；P3.1 已修正为默认行为降级，本地提示后结束本轮。旧 `/audio` 路径仅保留为显式开发调试开关。

本轮代码边界：

- 保持 touch 触发，不改回 GPIO6。
- 保持 waiting_speech 原口径：播放“请讲”、等待开口、首次超时重等一次、二次超时退出。
- 新增 `audio_in_stream_after_speech_start()`，从已打开麦克风持续读取 PCM chunk 并通过 callback 推给上行 client，不再为 v5 主路径分配整段录音 buffer。
- 新增 `cloud_client_opus_uplink_*`，连接 `WS /api/v5/realtime/opus-stream`，发送 start config、framed-v1 Opus binary frame 和 end control。
- framed-v1 与 `src/providers/opus.py` 对齐：outer header 为 4-byte big-endian sequence + 4-byte big-endian payload length；payload 为 2-byte big-endian Opus packet length + Opus packet。
- Opus encoder 使用 `espressif/esp_audio_codec` 2.4.1 已提供的 `esp_opus_enc_*`，新增依赖 `espressif/esp_websocket_client` 1.7.0。
- 不修改 `cloud_client_stream_realtime_audio()` 下行收流/解码/播放队列，不调整 v24 下行 jitter/prebuffer/close/tail/intro 并行参数。

第一版任务模型是串行 capture -> encode -> WS send，日志保留阶段耗时和上行指标；后续若真机发现 send/encode 阻塞 mic read，再拆 PCM queue 和 Opus queue。

fallback 行为：

- WS URL/连接/start control、Opus encoder、binary send、云端 error/done 缺少 `audio_stream_url` 均记录 `error_code`。
- 默认 `V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO=0`，失败后打印 `v5_uplink_failed error_code=<reason> fallback_behavior=local_prompt legacy_audio_fallback=false`，播放本地错误提示并结束本轮。
- 只有显式设置 `V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO=1` 时，日志打印 `legacy_audio_fallback=true fallback_reason=<reason>` 并尝试旧整段录音提交路径。该路径仅用于开发调试。
- 云端 ASR 双 provider 均失败、空文本或超时时，`/api/v5/realtime/opus-stream` 返回 `type=error`，优先使用 `error_code=asr_all_providers_failed`，provider 细节保留在 `asr_primary_error_code` / `provider_error_code` 等字段。

新增板端指标日志包括：

```text
v5_uplink_enabled
touch_trigger_ms
prompt_play_start_ms
prompt_play_end_ms
speech_start_ms
ws_connect_start
ws_connect_done
asr_provider
first_pcm_frame_ms
first_opus_frame_ms
first_ws_frame_sent_ms
last_ws_frame_sent_ms
end_sent_ms
first_ack_ms
asr_final_received_ms
done_received_ms
first_audio_play_ms
uplink_frame_count
uplink_opus_bytes
uplink_pcm_bytes
compression_ratio
heap_free
psram_free
```

ESP-IDF 编译结果：

```bash
cd esp_idf_demo
source /home/aitopia/esp/esp-idf-v5.5.4-full/export.sh
idf.py build
```

结果：通过。构建产物 `build/esp_idf_demo.bin`，binary size `0x37bf0`，factory partition 剩余约 89%。

Python 回归：

```bash
python -m pytest -q
```

结果：通过，`143 passed, 1 warning`。为避免 ESP-IDF component manager 拉下来的 `esp_idf_demo/managed_components/lvgl__lvgl/tests` 被顶层 pytest 误收集，本轮新增 `pytest.ini`，限定 `testpaths = tests`。

安全检查：

- `.env`、`esp_idf_demo/build/`、`esp_idf_demo/managed_components/`、`data/incoming/`、`data/output/`、`tmp/` 均由 `.gitignore` 覆盖。
- 凭据扫描排除了 `.env`、build、managed components、data、indices；命中项均为代码变量名、测试 dummy token 或文档配置名，未发现真实凭据。
- 本轮未纳入运行音频、trace、payload 或 build 产物。

下一步真机验证：

```bash
cd esp_idf_demo
source /home/aitopia/esp/esp-idf-v5.5.4-full/export.sh
idf.py -p /dev/ttyACM0 flash monitor
```

真机日志优先确认：

- `v5_uplink_enabled=1`
- `ws_connect_done`
- `first_ws_frame_sent_ms` 出现在录音结束前
- `asr_provider=volcengine`
- `done_received_ms` 后进入现有 `stream_audio`
- 若 v5 失败且未显式启用 legacy 调试开关，确认 `v5_uplink_failed`、`fallback_behavior=local_prompt`、`legacy_audio_fallback=false` 和明确 `error_code`。
- 只有显式构建 `V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO=1` 时，才允许出现 `legacy_audio_fallback=true`。

## 2026-05-10 P3.1：修正 ESP32 fallback 口径

最新策略不是“v5 失败自动切旧协议”，而是“按错误层级切行为”：

- L0：火山 ASR 成功，或火山失败后 DashScope 成功，正常 v5 full-chain。
- L1：火山 + DashScope 均失败、空文本或超时，云端返回固定错误语义，板端播放本地“请重试/请重新按”并结束本轮。
- L2：WS 连接失败、连续超时、协议错包、服务器不可达等极端失败，板端播放本地错误提示并结束本轮。
- L3：legacy `/audio` fallback 只作为显式开发调试开关，默认关闭。

本轮代码修正：

- `V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO` 默认从 `1` 改为 `0`。
- 新增 `V5_OPUS_UPLINK_BEHAVIOR_FALLBACK_ENABLED=1`，默认启用本地提示行为降级。
- v5 上行失败默认日志为 `v5_uplink_failed error_code=<reason> fallback_behavior=local_prompt legacy_audio_fallback=false`，随后播放 `DEMO_RECORD_RETRY_ERROR_PROMPT_PATH` 并回到 idle。
- 显式启用 legacy fallback 时，日志为 `legacy_audio_fallback=true fallback_reason=<reason>`，再走旧整段录音提交路径。
- 云端双 ASR provider 都失败时，WS error 统一返回 `error_code=asr_all_providers_failed`，但保留 `asr_primary_error_code` 和 `provider_error_code` 便于排障。

本轮验证：

```bash
python -m pytest -q
```

结果：通过，`145 passed, 1 warning`。

```bash
cd esp_idf_demo
source /home/aitopia/esp/esp-idf-v5.5.4-full/export.sh
idf.py build
```

结果：通过。构建产物 `build/esp_idf_demo.bin`，binary size `0x37c40`，factory partition 剩余约 89%。本轮未做真机烧录，未部署云端。

## 2026-05-10 P4：greenunion-sh v5 独立实例

本轮在 `greenunion-sh` 上另起 v5 realtime Opus 独立实例，v3 保持运行不动。

新增部署文档：

```text
docs/superpowers/specs/2026-05-10-v5-greenunion-deploy.md
```

新增 v5 专用 compose：

```text
deploy/greenunion/docker-compose.v5.yml
```

云端布局：

- v3 目录：`/home/ubuntu/religion_demo_v3_greenunion_app`
- v3 端口：宿主 `0.0.0.0:80` -> 容器 `8010`
- v5 目录：`/app/religion_demo_v5_realtime_opus`
- v5 compose project：`religion_demo_v5_realtime_opus`
- v5 端口：宿主 `0.0.0.0:8020` -> 容器 `8010`
- v5 `.env`：`/app/religion_demo_v5_realtime_opus/.env`，未打印真实值，未入库
- v5 data/indices：`/app/religion_demo_v5_realtime_opus/data`、`/app/religion_demo_v5_realtime_opus/indices`

v5 启动命令：

```bash
cd /app/religion_demo_v5_realtime_opus
docker compose -p religion_demo_v5_realtime_opus -f deploy/greenunion/docker-compose.v5.yml up -d --build
```

v5 停止命令：

```bash
cd /app/religion_demo_v5_realtime_opus
docker compose -p religion_demo_v5_realtime_opus -f deploy/greenunion/docker-compose.v5.yml down
```

当前容器 PID：

```text
api    1786577
worker 1786587
redis  1784596
```

v5 配置脱敏确认：

- `ASR_PROVIDER=volcengine`
- `ASR_FALLBACK_PROVIDER=dashscope`
- DashScope key 存在
- Volcengine ASR app/token/resource 存在
- LLM/TTS 配置存在
- `PUBLIC_BASE_URL=http://106.54.240.51:8020`

数据/索引：

- `data/buddhism` 从 v3 当前目录复制独立副本，73 files
- `indices` 从 v3 当前目录复制独立副本，2 files
- index chunks：181
- indexed doc titles：65

云端 healthz：

```bash
curl --max-time 5 -sS http://127.0.0.1:8020/healthz
```

结果：

```json
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

v3 主入口保持正常：

```bash
curl --max-time 5 -sS http://127.0.0.1:80/healthz
```

结果：

```json
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

v5 full-chain smoke：

```bash
docker exec religion_demo_v5_realtime_opus-api-1 \
  python scripts/opus_uplink_stream_smoke.py \
    /app/data/incoming/smoke_amitabha.wav \
    --base-url http://127.0.0.1:8010 \
    --frame-ms 60 \
    --realtime \
    --run-asr \
    --run-full-chain \
    --asr-provider volcengine \
    --asr-fallback-provider dashscope \
    --answer-mode short \
    --timeout 20 \
    --status-timeout 20 \
    --max-polls 120
```

结果：通过。`type=done`，session `status=done`，`final_reason=completed_answer`。本次火山 ASR 首选连接中断，随后 DashScope fallback 成功，属于 L0 正常流程。关键指标：79 frames，Opus 13415 bytes，PCM 150156 bytes，compression ratio 11.193，ASR final 1222 ms，first audio byte 2159 ms，done 8998 ms。

公网 8020 说明：

- 宿主 `ss` 确认 `0.0.0.0:8020` 已监听。
- 主机 `ufw inactive`，`iptables INPUT ACCEPT`。
- 但本地和云端本机访问 `http://106.54.240.51:8020/healthz` 均 5 秒超时，当前判断是云安全组或公网入口未放行 8020。
- 本轮未改 nginx 主入口、未改云安全组。板端目标 base URL 是 `http://106.54.240.51:8020`，但需先放行公网 `8020/tcp` 后才能直连。

部署中补充修正：`/healthz` 的旧 ASR 检查只接受 `ASR_PROVIDER=dashscope`。已最小修正为 Volcengine provider 下检查 Volcengine ASR app/token/resource，避免 v5 `.env` 正确但 healthz 误报 `asr=down`。

## 2026-05-10 P4.1：greenunion-sh 端口切换尝试与回滚

用户授权尝试让 v5 接管公网 80，并将 v3 改到 8020，目标是板端无需等待公网 8020 安全组放行即可访问 v5。

切换前端口表：

| service | before |
| --- | --- |
| v3 | `0.0.0.0:80 -> 8010` |
| v5 | `0.0.0.0:8020 -> 8010` |

切换前本机 healthz 均 ok：

```text
v3_80={"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
v5_8020={"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

备份文件：

```text
/home/ubuntu/religion_demo_v3_greenunion_app/docker-compose.yml.bak.20260510_102825
/app/religion_demo_v5_realtime_opus/deploy/greenunion/docker-compose.v5.yml.bak.20260510_102825
```

注：第一次备份命令因远端 `date` 变量被本地 shell 展开，额外生成了两个 `.bak.` 文件，也保留在云端作为冗余备份。

已执行切换：

- 停止 v3/v5 compose project。
- v3 compose 改为 `8020:8010`。
- v5 compose 改为 `${V5_PUBLIC_PORT:-80}:8010`。
- 启动 v5，再启动 v3。

切换后初次验证：

```text
v5 public healthz http://106.54.240.51/healthz:
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}

v5_80_local:
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}

v3_8020_local:
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

公网 80 full-chain Opus smoke：

```bash
python scripts/opus_uplink_stream_smoke.py \
  /tmp/volc_asr_eval/amitabha.wav \
  --base-url http://106.54.240.51 \
  --frame-ms 60 \
  --realtime \
  --run-asr \
  --run-full-chain \
  --answer-mode short \
  --timeout 20 \
  --status-timeout 20 \
  --max-polls 120
```

结果：stream `type=done`，session `status=done`，`final_reason=completed_answer`。关键指标：79 frames，Opus 13415 bytes，PCM 150156 bytes，compression ratio 11.193。火山 ASR 首选连接中断后 DashScope fallback 成功。

发现问题：smoke 返回的 `audio_stream_url` 仍指向 `http://106.54.240.51:8020/...`，原因是 v5 `.env` 的 `PUBLIC_BASE_URL` 仍是切换前的 `http://106.54.240.51:8020`。

为避免板端后续拉音频误走 8020，已将 v5 `.env` 脱敏更新为 `PUBLIC_BASE_URL=http://106.54.240.51` 并只重启 v5 API/worker。重启后 `http://106.54.240.51/healthz` 8 秒超时，本机 v5 healthz 也未及时返回，因此触发回滚。

回滚动作：

- v3 compose 恢复为 `80:8010`。
- v5 compose 恢复为 `${V5_PUBLIC_PORT:-8020}:8010`。
- v5 `.env` 的 `PUBLIC_BASE_URL` 恢复为 `http://106.54.240.51:8020`。
- 重新创建 v3/v5 API 容器；未删除 `.env`、data、indices、SQLite 或索引文件。

回滚后端口表：

| service | current |
| --- | --- |
| v3 | `0.0.0.0:80 -> 8010` |
| v5 | `0.0.0.0:8020 -> 8010` |

回滚后验证：

```text
v3_80_local={"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
v5_8020_local={"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
public_80=http://106.54.240.51/healthz -> ok
```

当前 v5 容器：

```text
api    1799503 running
worker 1797952 running
redis  1797839 running
```

结论：本次端口切换已尝试但已回滚。当前 80 仍是 v3，8020 仍是 v5；是否继续 v5 接管 80，需要先定位 v5 在 `PUBLIC_BASE_URL=http://106.54.240.51` 后重启 healthz 超时的原因，或改为放行公网 8020。

## 2026-05-10 P4.2：greenunion-sh v5 长驻公网 80

用户确认 v3 暂时不需要作为公网入口，授权停用 v3 并让 v5 长驻 80 做持续测试。本轮不删除 v3 数据、配置、volume、代码或 `.env`，也不改 nginx。

执行前状态：

| service | before |
| --- | --- |
| v3 | `0.0.0.0:80 -> 8010` |
| v5 | `0.0.0.0:8020 -> 8010` |

执行动作：

- `cd /home/ubuntu/religion_demo_v3_greenunion_app && docker compose stop`
- v5 compose 改为 `${V5_PUBLIC_PORT:-80}:8010`
- v5 `.env` 脱敏确认 `PUBLIC_BASE_URL=http://106.54.240.51`
- `cd /app/religion_demo_v5_realtime_opus && docker compose -p religion_demo_v5_realtime_opus -f deploy/greenunion/docker-compose.v5.yml up -d --force-recreate api worker`

本轮云端 v5 备份：

```text
/app/religion_demo_v5_realtime_opus/deploy/greenunion/docker-compose.v5.yml.bak.20260510_104439
/app/religion_demo_v5_realtime_opus/.env.bak.20260510_104439
```

当前端口表：

| service | current |
| --- | --- |
| v3 | stopped |
| v5 | `0.0.0.0:80 -> 8010` |

v5 healthz 验证：

```text
http://127.0.0.1/healthz -> {"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
http://106.54.240.51/healthz -> {"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

公网 80 full-chain Opus smoke：

```bash
python scripts/opus_uplink_stream_smoke.py \
  /tmp/volc_asr_eval/amitabha.wav \
  --base-url http://106.54.240.51 \
  --frame-ms 60 \
  --realtime \
  --run-asr \
  --run-full-chain \
  --answer-mode short
```

结果：通过。stream `type=done`，session `status=done`，`final_reason=completed_answer`。关键指标：79 frames，Opus 13415 bytes，PCM 150156 bytes，compression ratio 11.193。火山 ASR 首选返回 `volcengine_asr_finish_failed` 后 DashScope fallback 成功，属于 L0 正常流程。返回的 `audio_stream_url` 为 `http://106.54.240.51/api/v3/realtime/sessions/<session_id>/audio`，不再包含 `:8020`。

v3 恢复命令：

```bash
cd /home/ubuntu/religion_demo_v3_greenunion_app
docker compose up -d
```

如果需要让 v3 恢复公网 80，需先停止或改走 v5 端口，避免 80 端口冲突。
