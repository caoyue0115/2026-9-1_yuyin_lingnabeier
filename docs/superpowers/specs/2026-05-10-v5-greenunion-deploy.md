# v5 Greenunion Independent Deployment

## Goal

在 `greenunion-sh` 上启动 v5 realtime Opus 独立实例，同时保持现有 v3 运行不动。

本轮不改 nginx 主入口，不停止 v3，不覆盖 v3 目录或配置，不提交 `.env`。

## v3 Baseline

探查结果：

- v3 compose 目录：`/home/ubuntu/religion_demo_v3_greenunion_app`
- v3 容器 project：`religion_demo_v3_greenunion_app`
- v3 API：`religion_demo_v3_greenunion_app-api-1`
- v3 端口：宿主 `0.0.0.0:80` -> 容器 `8010`
- v3 runtime data：`/home/ubuntu/religion_demo_v3_greenunion_app/data`
- v3 runtime indices：`/home/ubuntu/religion_demo_v3_greenunion_app/indices`
- v3 状态：API、worker、redis 均 `Up 2 weeks`

本轮没有执行 `docker compose down`、没有重启 v3、没有修改 v3 `.env` 或 v3 compose。

## v5 Layout

- v5 目录：`/app/religion_demo_v5_realtime_opus`
- v5 compose file：`deploy/greenunion/docker-compose.v5.yml`
- v5 compose project：`religion_demo_v5_realtime_opus`
- v5 host port：`8020`
- v5 API container port：`8010`
- v5 `.env`：`/app/religion_demo_v5_realtime_opus/.env`
- v5 data：`/app/religion_demo_v5_realtime_opus/data`
- v5 indices：`/app/religion_demo_v5_realtime_opus/indices`

`data/buddhism` 和 `indices` 是从 v3 当前目录复制出的独立副本：

- Buddhism docs：73 files
- index files：2
- index chunks：181
- indexed doc titles：65

## Runtime Config

v5 `.env` 从 v3 云端配置和本地 v5 授权信息合并生成，值不写入仓库、不打印。

已脱敏确认存在：

- `DASHSCOPE_API_KEY`
- `VOLCENGINE_SPEECH_APP_ID`
- `VOLCENGINE_SPEECH_ACCESS_TOKEN`
- `VOLCENGINE_ASR_RESOURCE_ID`
- `LLM_PROVIDER`
- `LLM_MODEL`
- `REALTIME_TTS_MODEL`
- `REALTIME_TTS_VOICE`

v5 覆盖项：

```text
ASR_PROVIDER=volcengine
ASR_FALLBACK_PROVIDER=dashscope
PUBLIC_BASE_URL=http://106.54.240.51:8020
REDIS_URL=redis://redis:6379/0
SQLITE_PATH=./data/tasks.db
REALTIME_ENABLED=true
REALTIME_AUDIO_ENABLE_OPUS=true
```

## Start And Stop

启动：

```bash
cd /app/religion_demo_v5_realtime_opus
docker compose -p religion_demo_v5_realtime_opus -f deploy/greenunion/docker-compose.v5.yml up -d --build
```

查看：

```bash
cd /app/religion_demo_v5_realtime_opus
docker compose -p religion_demo_v5_realtime_opus -f deploy/greenunion/docker-compose.v5.yml ps
docker compose -p religion_demo_v5_realtime_opus -f deploy/greenunion/docker-compose.v5.yml logs --tail=120 api
```

停止 v5：

```bash
cd /app/religion_demo_v5_realtime_opus
docker compose -p religion_demo_v5_realtime_opus -f deploy/greenunion/docker-compose.v5.yml down
```

该停止命令只作用于 v5 compose project，不作用于 v3。

## Verification

云端本机 healthz：

```bash
curl --max-time 5 -sS http://127.0.0.1:8020/healthz
```

结果：

```json
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

v3 主入口 healthz 仍正常：

```bash
curl --max-time 5 -sS http://127.0.0.1:80/healthz
```

结果：

```json
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

v5 full-chain smoke 在 v5 API 容器内执行：

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

结果摘要：

- stream result：`type=done`
- session status：`done`
- final reason：`completed_answer`
- uplink frames：79
- Opus bytes：13415
- PCM bytes：150156
- compression ratio：11.193
- reconstructed audio：4692 ms
- ASR primary：`volcengine`
- ASR fallback：`dashscope`
- provider used：`dashscope`
- fallback used：`true`
- primary error：`volcengine_asr_finish_failed` / connection lost
- ASR final：1222 ms
- first audio byte：2159 ms
- done：8998 ms

本次 smoke 说明 v5 framed-v1 Opus 上行、fallback ASR、RAG、LLM、TTS 和 session audio 生成链路可用。火山 ASR 首选连接中断后由 DashScope fallback 成功，属于 L0 正常行为。

## Public Port Note

宿主监听：

```text
0.0.0.0:8020 -> v5 api 8010
0.0.0.0:80   -> v3 api 8010
```

主机防火墙探查：

```text
ufw: inactive
iptables INPUT: ACCEPT
```

但本地直连 `http://106.54.240.51:8020/healthz` 和云端本机访问公网 IP `http://106.54.240.51:8020/healthz` 均 5 秒超时。当前判断是云厂商安全组或公网入口未放行 8020。

本轮按原则没有修改 nginx 主入口，也没有调整云安全组。板端如要直连当前 v5 端口，需先放行公网 `8020/tcp`，目标 base URL 为：

```text
http://106.54.240.51:8020
```

在放行前，云端本机 smoke 已通过，但公网板端不可直接访问该端口。

## Local Code Change

部署中发现 `/healthz` 的 legacy ASR 检查只接受 `ASR_PROVIDER=dashscope`，导致 v5 使用 `ASR_PROVIDER=volcengine` 时 healthz 显示 `asr=down`。本轮已最小修正 `src/providers/asr.py`，在 Volcengine provider 下检查：

- `VOLCENGINE_SPEECH_APP_ID`
- `VOLCENGINE_SPEECH_ACCESS_TOKEN`
- `VOLCENGINE_ASR_RESOURCE_ID`

对应测试：

```bash
python -m pytest tests/test_asr_provider.py::TranscribeWavTests::test_asr_health_accepts_volcengine_streaming_credentials -q
python -m pytest tests/test_asr_provider.py tests/test_app_healthz.py -q
```
