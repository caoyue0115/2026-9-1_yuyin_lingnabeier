# v5 ASR Provider A/B

日期：2026-05-09

## 目标

P2 在 v5 真流式 Opus framed-v1 上行链路中新增可选 ASR provider：

- `dashscope`：默认 provider，继续使用 DashScope `paraformer-realtime-v2`
- `volcengine`：新增 provider，只替换 ASR，不替换 LLM/TTS/RAG

本轮不接火山 LLM/TTS，不做 ASR partial 提前 LLM，不做打断，不修改 v3。

## 接口口径

WebSocket endpoint 不变：

```text
WS /api/v5/realtime/opus-stream
```

默认仍是 DashScope：

```json
{"type":"start","run_asr":true,"run_full_chain":true}
```

显式切换火山 ASR：

```json
{"type":"start","run_asr":true,"run_full_chain":true,"asr_provider":"volcengine"}
```

`asr_provider` 只影响 ASR final 产生方式。ASR final 之后仍复用既有 RAG / LLM / TTS。

## 火山 ASR 实现

火山路径是真 streaming PCM，不是 end 后 WAV baseline：

```text
Opus frame -> 服务端解码 PCM chunk -> 火山 bigmodel_async Audio Only Request
```

协议来自 v4 已跑通 PoC：

- endpoint：`wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`
- headers：火山语音 App ID、Access Token、ASR Resource ID、Connect ID
- Full Request：gzip JSON，`format=pcm`、`codec=raw`、`rate=16000`、`bits=16`、`channel=1`
- request 字段：`model_name=bigmodel`、`enable_itn=true`、`enable_punc=true`、`enable_ddc=true`、`show_utterances=true`、`enable_nonstream=true`
- Audio Only：gzip PCM payload，最后一包使用负 sequence

凭据只读取本地 `.env` 或进程环境变量；`.env` 已被 `.gitignore` 忽略，未入库。

## 时间轴口径

矩阵输出继续使用 P1.5 口径：脚本将服务端 `*_abs_ms` 统一减去 `first_frame_server_abs_ms`，作为“从客户端发送第一帧附近起算”的对外比较时间。

注意：火山 provider 当前在处理首个 binary frame 前需要先建立火山 ASR WebSocket。单条回归中 `first_frame_server_abs_ms=1542`，这段 provider 建连等待没有进入下方归一化矩阵表。若严格计算客户端首帧发送后的端到端时间，后续应新增 `provider_start_ms` / raw `first_frame_server_abs_ms` 对比字段。

火山 ASR 当前不稳定透传 partial；表里的 `first_asr_partial_abs_ms` 对火山表示“首个非空识别结果时间”，不代表已用于触发 LLM。

## 命令

单条火山回归：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --asr-provider volcengine --max-polls 160 --status-timeout 30 --timeout 30
```

9 条 A/B 矩阵：

```bash
python scripts/v5_streaming_latency_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --target streaming --provider-matrix dashscope,volcengine --output /tmp/v5_asr_provider_ab.jsonl --markdown /tmp/v5_asr_provider_ab.md --max-polls 180 --status-timeout 30 --timeout 30
```

## 单条火山回归

输入：

```text
/tmp/volc_asr_eval/amitabha.wav
```

结果：火山 ASR、RAG、LLM、TTS 全链路跑通。

| 指标 | 值 |
| --- | ---: |
| provider | volcengine |
| uplink_frame_count | 79 |
| uplink_opus_bytes | 13415 |
| uplink_pcm_bytes | 150156 |
| uplink_compression_ratio | 11.193 |
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

该条识别修正了 DashScope 在同音频上常见的 `情解释` 错字。

## 9 条 A/B 汇总

| provider | cases | successful | term_hits | mean_first_asr_partial_abs_ms | mean_asr_final_abs_ms | mean_first_audio_byte_abs_ms | mean_done_abs_ms | mean_audio_duration_ms | mean_answer_chars |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dashscope | 9 | 9 | 7/9 | 4466.7 | 6429.8 | 11680.2 | 17160.0 | 14488.9 | 48.2 |
| volcengine | 9 | 9 | 9/9 | 1926.9 | 3146.2 | 13884.1 | 18329.1 | 14302.2 | 47.0 |

## 逐词结果

| term | provider | hit | recognized_text | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms |
| --- | --- | --- | --- | ---: | ---: | ---: |
| 阿弥陀佛 | dashscope | Y | 情解释阿弥陀佛是什么意思？ | 5991 | 10661 | 15370 |
| 阿弥陀佛 | volcengine | Y | 请解释阿弥陀佛是什么意思？ | 3174 | 9697 | 15410 |
| 四十八愿 | dashscope | N | 48愿和净土宗有什么关系？ | 7648 | 13091 | 18890 |
| 四十八愿 | volcengine | Y | 四十八愿和净土宗有什么关系？ | 3262 | 10282 | 14999 |
| 净土宗 | dashscope | Y | 净土宗为什么重视信愿行？ | 5599 | 9825 | 14602 |
| 净土宗 | volcengine | Y | 净土宗为什么重视信愿行？ | 4035 | 9944 | 14390 |
| 无量寿经 | dashscope | Y | 无量寿经讲了什么？ | 6541 | 10897 | 16685 |
| 无量寿经 | volcengine | Y | 无量寿经讲了什么？ | 1959 | 9909 | 14133 |
| 金刚经 | dashscope | Y | 金刚经的核心意思是什么？ | 13458 | 24099 | 30267 |
| 金刚经 | volcengine | Y | 金刚经的核心意思是什么？ | 3626 | 36715 | 42091 |
| 般若 | dashscope | Y | 佛教里般若是什么意思？ | 4047 | 9360 | 12433 |
| 般若 | volcengine | Y | 佛教里般若是什么意思？ | 2161 | 6768 | 9858 |
| 慧远 | dashscope | N | 慧云大师和东林寺有什么关系？ | 5011 | 9110 | 14173 |
| 慧远 | volcengine | Y | 慧远大师和东林寺有什么关系？ | 2964 | 8204 | 11822 |
| 善导 | dashscope | Y | 善导大师如何解释念佛？ | 4084 | 8066 | 14867 |
| 善导 | volcengine | Y | 善导大师如何解释念佛？ | 4123 | 22092 | 25909 |
| 东林寺 | dashscope | Y | 东林寺和净土宗有什么关系？ | 5489 | 10013 | 17153 |
| 东林寺 | volcengine | Y | 东林寺和净土宗有什么关系？ | 3012 | 11346 | 16350 |

## 观察

- 火山 ASR 在佛学词精确命中上优于 DashScope：`9/9` vs `7/9`。
- 火山 ASR final 在当前归一化口径下明显更快：均值约 `3.15s`，DashScope 约 `6.43s`。考虑单条约 `1.5s` 的火山建连等待后，火山 ASR 仍有优势，但优势幅度需要 ASR-only 重复矩阵确认。
- full-chain 首音频和 total 没有随 ASR 优势同步领先：火山 mean 首音频约 `13.88s`，DashScope 约 `11.68s`。
- 火山 full-chain 被个别后续链路拖慢，尤其 `金刚经` 和 `善导` 的 LLM/TTS 阶段出现明显抖动；这不是 ASR 层失败。
- DashScope 的主要错词仍是 `四十八愿 -> 48愿`、`慧远 -> 慧云`、`请解释 -> 情解释`。

## 阶段判断

P2 证明 v5 可以在同一个 streaming Opus 上行链路中通过配置切换 ASR provider。火山 ASR 值得继续作为可选 provider 深入评估，尤其适合佛学专有词准确率方向。

但当前还不能直接判定“切火山整体更快”：本轮只替换 ASR，后续 RAG/LLM/TTS 仍复用 v5 现有链路，且个别 full-chain 样本存在明显抖动。下一步应固定 LLM/TTS 输出长度与并发状态，重复 A/B，并单独拆出 ASR-only 稳定性矩阵。

## P2.1 Provider Lifecycle 复测

P2.1 解决 P2 发现的火山 ASR 建连阻塞首帧问题。实现后，provider start 在后台线程中执行；首帧到达时服务端立即解码和 ack，provider 未 ready 期间只缓存 PCM，ready 后按序 flush。

新增字段：

| 字段 | 说明 |
| --- | --- |
| `provider_start_abs_ms` | provider start 发起时间 |
| `provider_ready_abs_ms` | provider 可接收 PCM 时间 |
| `provider_start_duration_ms` | provider 建连/启动耗时 |
| `first_pcm_decoded_abs_ms` | 服务端首个 PCM 解码时间 |
| `first_pcm_sent_to_provider_abs_ms` | 首个 PCM 实际送入 provider 时间 |
| `first_provider_result_abs_ms` | 首个非空 provider 结果时间 |
| `provider_log_id` | provider log/request id |
| `provider_error_code` | provider 层错误码 |
| `provider_error_message` | provider 层错误摘要 |

### 单条复测

输入：`/tmp/volc_asr_eval/amitabha.wav`

| case | first_frame_server_abs_ms | provider_start_duration_ms | provider_ready_abs_ms | first_pcm_sent_to_provider_abs_ms | first_provider_result_abs_ms | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P0 no ASR | 4 | N/A | N/A | N/A | N/A | N/A | N/A | 4848 |
| DashScope | 8 | 62 | 69 | 69 | 3649 | 5604 | 9807 | 15302 |
| Volcengine | 4 | 1900 | 1904 | 1904 | 4959 | 5585 | 11882 | 17143 |

火山单条 ASR final：

```text
请解释阿弥陀佛是什么意思？
```

结论：火山 `first_frame_server_abs_ms` 从 P2 的约 `1542ms` 降到 `4ms`，说明建连已不再阻塞首帧处理。provider 建连耗时仍存在，本条为 `1900ms`。

### P2.1 9 条 A/B 汇总

命令：

```bash
python scripts/v5_streaming_latency_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --target streaming --provider-matrix dashscope,volcengine --output /tmp/v5_asr_provider_ab_p21.jsonl --markdown /tmp/v5_asr_provider_ab_p21.md --max-polls 180 --status-timeout 30 --timeout 30
```

结果文件只保存在 `/tmp`，不入库。

| provider | cases | successful | term_hits | mean_provider_start_duration_ms | mean_first_pcm_sent_to_provider_abs_ms | mean_first_provider_result_abs_ms | mean_asr_final_abs_ms | mean_first_audio_byte_abs_ms | mean_done_abs_ms | mean_audio_duration_ms | mean_answer_chars |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dashscope | 9 | 9 | 7/9 | 70.8 | 70.6 | 2980.7 | 5590.8 | 9875.0 | 14434.4 | 14471.1 | 48.3 |
| volcengine | 9 | 9 | 9/9 | 1831.3 | 1831.3 | 4090.2 | 4740.7 | 8625.7 | 13397.7 | 14266.7 | 46.7 |

逐词：

| term | dashscope hit/text | volcengine hit/text |
| --- | --- | --- |
| 阿弥陀佛 | Y / 阿弥陀佛命中，但仍有“情解释”错字 | Y / 请解释阿弥陀佛是什么意思？ |
| 四十八愿 | N / 48愿和净土宗有什么关系？ | Y / 四十八愿和净土宗有什么关系？ |
| 净土宗 | Y / 净土宗为什么重视信愿行？ | Y / 净土宗为什么重视信愿行？ |
| 无量寿经 | Y / 无量寿经讲了什么？ | Y / 无量寿经讲了什么？ |
| 金刚经 | Y / 金刚经的核心意思是什么？ | Y / 金刚经的核心意思是什么？ |
| 般若 | Y / 佛教里般若是什么意思？ | Y / 佛教里般若是什么意思？ |
| 慧远 | N / 慧云大师和东林寺有什么关系？ | Y / 慧远大师和东林寺有什么关系？ |
| 善导 | Y / 善导大师如何解释念佛？ | Y / 善导大师如何解释念佛？ |
| 东林寺 | Y / 东林寺和净土宗有什么关系？ | Y / 东林寺和净土宗有什么关系？ |

P2.1 判断：

- 火山 ASR 建连已被单独拆账，且不再阻塞首帧 ack。
- 火山 provider start 均值约 `1831.3ms`，明显慢于 DashScope 的 `70.8ms`。
- 即便计入建连，火山 ASR final 均值仍优于 DashScope：`4740.7ms` vs `5590.8ms`。
- 火山佛学词精确命中保持 `9/9`，DashScope 仍为 `7/9`。
- 本轮 full-chain 火山 mean 首音频和 total 也优于 DashScope，但这不是 ASR-only 结论；后段仍可能受 LLM/TTS 抖动影响。

## P2.2 ASR-only 重复矩阵

目标：只比较 ASR provider，不跑 RAG/LLM/TTS，排除后段抖动。默认 provider 仍为 `dashscope`，火山仍为可选 provider。

新增脚本：

```bash
python scripts/v5_asr_only_repeat_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --providers dashscope,volcengine --repeats 5 --frame-ms 60 --realtime --output /tmp/v5_asr_only_repeat_eval.jsonl --markdown /tmp/v5_asr_only_repeat_eval.md
```

WebSocket start control：

```json
{"type":"start","run_asr":true,"run_full_chain":false,"asr_provider":"dashscope"}
{"type":"start","run_asr":true,"run_full_chain":false,"asr_provider":"volcengine"}
```

该模式只返回 ASR final 和 done summary；服务端 `session_started=false`，不会创建 realtime session，也不会触发 RAG/LLM/TTS。

### 单条 smoke

输入：`/tmp/volc_asr_eval/amitabha.wav`

| provider | question_text | first_frame_server_abs_ms | provider_start_duration_ms | first_pcm_sent_to_provider_abs_ms | first_provider_result_abs_ms | asr_final_abs_ms | session_started |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| dashscope | 情解释阿弥陀佛是什么意思？ | 7 | 63 | 69 | 2469 | 5304 | false |
| volcengine | 请解释阿弥陀佛是什么意思？ | 3 | 1711 | 1714 | 4934 | 5751 | false |

### 5 轮重复矩阵汇总

90 条记录全部成功，错误数为 0。结果文件只保存在 `/tmp`，不入库。

| provider | success_count / total | term_hits / total | mean_asr_final_abs_ms | median_asr_final_abs_ms | p95_asr_final_abs_ms | mean_provider_start_duration_ms | p95_provider_start_duration_ms | mean_first_provider_result_abs_ms | p95_first_provider_result_abs_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dashscope | 45/45 | 35/45 | 4851.8 | 4492.0 | 6424.0 | 63.2 | 63.0 | 2690.1 | 3709.0 |
| volcengine | 45/45 | 45/45 | 4694.7 | 4430.0 | 5643.0 | 1412.8 | 2512.0 | 4088.9 | 5084.0 |

### 逐词稳定性

| term | dashscope hit_count / repeats | dashscope recognized_text | volcengine hit_count / repeats | volcengine recognized_text |
| --- | ---: | --- | ---: | --- |
| 阿弥陀佛 | 5/5 | 情解释阿弥陀佛是什么意思？ | 5/5 | 请解释阿弥陀佛是什么意思？ |
| 四十八愿 | 0/5 | 48愿和净土宗有什么关系？ | 5/5 | 四十八愿和净土宗有什么关系？ |
| 净土宗 | 5/5 | 净土宗为什么重视信愿行？ | 5/5 | 净土宗为什么重视信愿行？ |
| 无量寿经 | 5/5 | 无量寿经讲了什么？ | 5/5 | 无量寿经讲了什么？ |
| 金刚经 | 5/5 | 金刚经的核心意思是什么？ | 5/5 | 金刚经的核心意思是什么？ |
| 般若 | 5/5 | 佛教里般若是什么意思？ | 5/5 | 佛教里般若是什么意思？ |
| 慧远 | 0/5 | 慧云大师和东林寺有什么关系？ | 5/5 | 慧远大师和东林寺有什么关系？ |
| 善导 | 5/5 | 善导大师如何解释念佛？ | 5/5 | 善导大师如何解释念佛？ |
| 东林寺 | 5/5 | 东林寺和净土宗有什么关系？ | 5/5 | 东林寺和净土宗有什么关系？ |

### P2.2 判断

- ASR-only 重复矩阵中，Volcengine 准确率为 `45/45`，DashScope 为 `35/45`。
- DashScope 错词稳定复现：`四十八愿 -> 48愿`、`慧远 -> 慧云`，以及非词项但会影响问题自然度的 `请解释 -> 情解释`。
- Volcengine provider start 仍慢：mean `1412.8ms`，p95 `2512.0ms`；这部分已被单独拆账，且不阻塞首帧。
- 计入 provider start 后，Volcengine ASR final 仍略优于 DashScope：mean `4694.7ms` vs `4851.8ms`，median `4430.0ms` vs `4492.0ms`，p95 `5643.0ms` vs `6424.0ms`。
- 仅 ASR 层看，Volcengine 已有较强证据成为默认 provider 候选；但默认切换前仍应跑固定回答长度和固定 TTS 输出的 full-chain 重复矩阵，避免 ASR 优势被后段抖动抵消。
