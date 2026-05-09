# v5 Real Voice / Board Recording Eval

日期：2026-05-09

## 目标

P2.4 之后，Volcengine ASR 已具备默认 provider 候选资格，但当前证据主要来自合成或固定测试音频。下一步需要真实人声和板端录音矩阵，验证：

- 佛学词准确率是否在真实说话人、环境噪声、板端麦克风链路下保持。
- Volcengine 默认 + DashScope fallback 是否能稳定保障可用性。
- full-chain short 的首音频和 total 在真实音频上是否仍可接受。

本阶段不改 ESP32 固件、不部署生产、不访问旧公网。

## 录音目录

所有录音放在本地 `/tmp`，不入库：

```text
/tmp/v5_real_voice_eval/
  amitabha_01.wav
  amitabha_02.wav
  forty_eight_vows_01.wav
  forty_eight_vows_02.wav
  pure_land_01.wav
  pure_land_02.wav
  infinite_life_sutra_01.wav
  infinite_life_sutra_02.wav
  diamond_sutra_01.wav
  diamond_sutra_02.wav
  prajna_01.wav
  prajna_02.wav
  huiyuan_01.wav
  huiyuan_02.wav
  shandao_01.wav
  shandao_02.wav
  donglin_temple_01.wav
  donglin_temple_02.wav
```

`_01`、`_02` 表示不同说话人或不同录音来源。可以继续追加 `_03`、`_04`。

## 音频要求

- 优先 WAV：16 kHz、16-bit、mono。
- 每条只说一句，对应 9 个固定问题。
- 至少 2 个说话人，每词至少 2 条。
- 手机录音可先转 WAV；原始文件不提交。
- 板端录音优先保存到 `/tmp/v5_real_voice_eval/`，不要写入仓库。

固定问题：

| 文件前缀 | 词项 | 文本 |
| --- | --- | --- |
| `amitabha` | 阿弥陀佛 | 请解释阿弥陀佛是什么意思 |
| `forty_eight_vows` | 四十八愿 | 四十八愿和净土宗有什么关系 |
| `pure_land` | 净土宗 | 净土宗为什么重视信愿行 |
| `infinite_life_sutra` | 无量寿经 | 无量寿经讲了什么 |
| `diamond_sutra` | 金刚经 | 金刚经的核心意思是什么 |
| `prajna` | 般若 | 佛教里般若是什么意思 |
| `huiyuan` | 慧远 | 慧远大师和东林寺有什么关系 |
| `shandao` | 善导 | 善导大师如何解释念佛 |
| `donglin_temple` | 东林寺 | 东林寺和净土宗有什么关系 |

## 执行命令

真实录音矩阵脚本：

```bash
python scripts/v5_real_voice_eval.py \
  --audio-dir /tmp/v5_real_voice_eval \
  --base-url http://127.0.0.1:8010 \
  --providers dashscope,volcengine \
  --frame-ms 60 \
  --realtime \
  --answer-mode short \
  --asr-fallback-provider dashscope \
  --output /tmp/v5_real_voice_eval.jsonl \
  --markdown /tmp/v5_real_voice_eval.md
```

如只验证本地 `.env` 默认 provider：

```bash
python scripts/opus_uplink_stream_smoke.py /tmp/v5_real_voice_eval/amitabha_01.wav \
  --base-url http://127.0.0.1:8010 \
  --frame-ms 60 \
  --realtime \
  --run-asr \
  --run-full-chain \
  --answer-mode short
```

## 输出字段

JSONL 记录包含：

- `provider`
- `asr_primary_provider`
- `asr_fallback_provider`
- `asr_provider_used`
- `asr_fallback_used`
- `term`
- `speaker_index`
- `audio_path`
- `question_text`
- `term_hit`
- `asr_final_abs_ms`
- `first_audio_byte_abs_ms`
- `done_abs_ms`
- `answer_chars`
- `audio_duration_ms`
- `error_code`
- `provider_log_id`

## 判定口径

- 先看每个 provider 的 `term_hit`，再看 fallback 是否触发。
- 若 Volcengine 在真实录音上仍显著优于 DashScope，且 fallback 未频繁触发，可以进入本地灰度默认。
- 若 Volcengine 对某些说话人或板端录音失败，但 DashScope fallback 成功，则继续保留 fallback，不直接下线 DashScope。
- 若两个 provider 都对真实录音有明显错词，下一步优先补 ASR 热词/上下文，而不是改 LLM/TTS。
