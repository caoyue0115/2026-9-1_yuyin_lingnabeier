# v5 Streaming Latency Matrix

日期：2026-05-09

## 口径

本轮是 P1.5：统一绝对时间轴，并用 9 条佛学词音频跑 `WS /api/v5/realtime/opus-stream` + DashScope realtime ASR + RAG/LLM/TTS full-chain。未接火山 ASR，未做 ASR partial 提前 LLM，未改 v3。

服务端原始 `*_abs_ms` 以 WebSocket accept 为零点。矩阵输出为了对外比较，统一减去 `first_frame_server_abs_ms`，因此 Markdown/JSONL 中的 `*_abs_ms` 字段均表示“从客户端发送第一帧”附近起算的链路时间。客户端脚本同时记录 `client_stream_start_ms`、`client_first_frame_sent_ms`、`client_last_frame_sent_ms`、`client_end_sent_ms`、`client_done_received_ms`，这些字段只用于判断脚本侧发送节奏，不与服务端时钟直接相减。

full-chain 的 RAG/LLM/TTS 指标通过 `stream_to_session_start_abs_ms + session 内相对耗时` 计算，再按第一帧归一化。原有阶段耗时如 `retrieval_ms`、`first_llm_chunk_ms`、`first_tts_chunk_ms`、`done_ms` 仍保留，但不再直接当作端到端指标。

## 单条回归

命令：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/volc_asr_eval/amitabha.wav --base-url http://127.0.0.1:8010 --frame-ms 60 --realtime --run-asr --run-full-chain --max-polls 120 --status-timeout 20 --timeout 30
```

关键结果：

| 指标 | 值 |
| --- | ---: |
| first_frame_server_abs_ms | 6 |
| first_pcm_to_asr_abs_ms | 6 |
| first_asr_partial_abs_ms | 2768 |
| asr_final_abs_ms | 5529 |
| client_first_frame_sent_ms | 8 |
| client_last_frame_sent_ms | 4783 |
| client_end_sent_ms | 4844 |
| client_done_received_ms | 5791 |
| retrieval_done_abs_ms | 6503 |
| first_llm_chunk_abs_ms | 8668 |
| first_tts_chunk_abs_ms | 10048 |
| first_audio_byte_abs_ms | 10048 |
| done_abs_ms | 15854 |

ASR final：

```text
情解释阿弥陀佛是什么意思？
```

说明：命中“阿弥陀佛”，但首字仍将“请”错为“情”。

## 9 条矩阵

命令：

```bash
python scripts/v5_streaming_latency_eval.py --audio-dir /tmp/volc_asr_eval --base-url http://127.0.0.1:8010 --target streaming --output /tmp/v5_streaming_latency_eval.jsonl --markdown /tmp/v5_streaming_latency_eval.md
```

汇总：

| 指标 | 值 |
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

明细：

| term | hit | recognized_text | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms | audio_duration_ms | answer_chars |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 阿弥陀佛 | Y | 情解释阿弥陀佛是什么意思？ | 5242 | 9176 | 13562 | 15040 | 50 |
| 四十八愿 | N | 48愿和净土宗有什么关系？ | 5061 | 8193 | 13327 | 16480 | 63 |
| 净土宗 | Y | 净土宗为什么重视信愿行？ | 5667 | 10584 | 15806 | 16720 | 52 |
| 无量寿经 | Y | 无量寿经讲了什么？ | 4801 | 8150 | 12525 | 14400 | 53 |
| 金刚经 | Y | 金刚经的核心意思是什么？ | 3392 | 6886 | 11295 | 14480 | 48 |
| 般若 | Y | 佛教里般若是什么意思？ | 3671 | 7558 | 10932 | 10560 | 36 |
| 慧远 | N | 慧云大师和东林寺有什么关系？ | 4163 | 8227 | 12882 | 15360 | 50 |
| 善导 | Y | 善导大师如何解释念佛？ | 4049 | 7869 | 11925 | 14800 | 46 |
| 东林寺 | Y | 东林寺和净土宗有什么关系？ | 6473 | 9699 | 14586 | 12880 | 44 |

## 观察

- 9 条全部完整进入 ASR/RAG/LLM/TTS，无接口失败。
- 佛学词命中率为 7/9。错词为“四十八愿”被数字化为“48愿”，以及“慧远”被识别为“慧云”。
- mean ASR final 约 4.7 秒，mean 首音频约 8.5 秒。当前瓶颈仍主要在 ASR final 之后到首音频这段链路，且输出音频均值约 14.5 秒，会影响 total。
- P1.5 仍未做 partial 提前 LLM，因此这些结果是保守口径，不代表未来 partial/prefill 优化后的极限。

## 下一步

建议先做两件事：

1. 用同 9 条音频跑 v5 HTTP body Opus 完整上传基线和 v3 原链路，形成同时间轴对比。
2. 评估 DashScope realtime ASR 的热词/词表或文本归一化策略，重点处理“四十八愿”和“慧远”。
