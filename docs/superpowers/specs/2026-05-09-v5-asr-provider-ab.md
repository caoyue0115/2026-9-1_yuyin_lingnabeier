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
