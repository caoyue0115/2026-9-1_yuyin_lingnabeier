# 20260407_宗教大模型云服务器 Demo

本目录用于记录当前云服务器 Demo 的运行方式，以及喵伴设备端的联调入口。

> 2026-05-06 更新：旧公网生产入口 `OLD_PUBLIC_ENTRY_DISABLED` 已完全停用，所有联调和部署默认按公司上海云服务器 `greenunion-sh` 处理。不要再使用旧公网地址做健康检查、板端配置或部署判断。

## 当前设备端基线

仓库内已经提供独立设备端工程：

- [`esp_idf_demo/README.md`](esp_idf_demo/README.md)

当前默认基线为：

- 开发板：`ESP-VoCat v1.2`
- 触发方式：`触摸屏`
- 工具链：`ESP-IDF 5.5.4`

当前设备端闭环为：

`触摸 -> 录音 -> 上传 -> 轮询 -> 下载 -> 播放`

当前并行探索线还新增了：

`v3/realtime: 上传 PCM -> 创建 session -> /audio chunked 裸 PCM -> 边收边播`

开始刷机前请先确认：

- `esp_idf_demo/main/config.h` 中的 Wi-Fi、服务地址和 `device_id`
- 本机已安装 `ESP-IDF 5.5.4`
- 可执行 `idf.py build` 和 `idf.py flash monitor`

## 当前可用的模拟设备命令

在本地或云端项目目录中，可以用下面这条命令模拟设备端上传原始 PCM，并轮询任务结果：

```bash
BASE_URL=http://<CURRENT_BASE_URL> python3 scripts/esp_simulator.py /path/to/input.wav --download-audio --output-dir ./tmp
```

说明：

- 输入文件使用 `wav`，脚本会自动剥离出 PCM 帧并按 `application/octet-stream` 上传
- Header 会自动带上 `x-device-id`、`x-sample-rate`、`x-sample-width`、`x-channels`
- 成功后会打印 `task_id`、`question_text`、`answer_text`、`audio_url`、`trace`
- 加 `--download-audio` 后会把返回音频下载到 `--output-dir`

## 当前可用的 ASR 热词命令

如果你想提升“无相”“般若”等佛学术语的识别率，可以先创建 DashScope 热词表：

```bash
python3 scripts/create_asr_vocabulary.py
```

默认会读取：

```text
config/asr_hotwords.buddhism.json
```

脚本会输出两部分内容：

- 热词表摘要
- 可直接写入 `.env` 的 `ASR_VOCABULARY_ID=...`

如果已经有热词表 ID，也可以更新原有热词表而不是新建：

```bash
python3 scripts/create_asr_vocabulary.py --vocabulary-id vocab-xxxx
```

## 服务器信息

- SSH 地址：`ssh -p 22 ubuntu@106.54.240.51`
- SSH Host：`greenunion-sh`
- 旧公网入口：`OLD_PUBLIC_ENTRY_DISABLED`，已完全停用
- 项目目录：`/app/religion_demo_20260407`
- 推荐运行方式：`screen` 托管服务

## 常用运维命令

查看当前 screen 会话：

```bash
screen -ls
```

如果你仍使用 `screen` 托管其它进程，重新进入会话查看日志：

```bash
screen -r esp
```

从 screen 中退出但不停止服务：

```text
Ctrl+A，然后按 D
```

当前云端主服务实际由 `docker compose` 管理，更常用的是：

```bash
ssh -p 22 ubuntu@106.54.240.51
cd /app/religion_demo_20260407
docker compose ps
docker logs -f religion_demo_20260407-api-1
docker logs -f religion_demo_20260407-worker-1
```

## 建议阅读顺序

1. [`使用手册.md`](使用手册.md)
2. [`快速启动手册.md`](快速启动手册.md)
3. [`esp_idf_demo/README.md`](esp_idf_demo/README.md)
4. [`docs/superpowers/summaries/2026-04-08-hardware-handoff.md`](docs/superpowers/summaries/2026-04-08-hardware-handoff.md)
5. [`20260409_流式传输/板端联调清单.md`](20260409_流式传输/板端联调清单.md)
6. [`20260409_流式传输/安装建议.md`](20260409_流式传输/安装建议.md)

## 环境变量示例

仓库根目录已补：

- [`.env.example`](/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/.env.example)

其中已包含当前 `v3/realtime` 相关关键项：

- `REALTIME_TTS_MODEL`
- `REALTIME_TTS_VOICE`
- `REALTIME_TTS_WARMUP_ENABLED`
- `REALTIME_LLM_COMPACT_TOP_K`
- `REALTIME_LLM_COMPACT_SNIPPET_CHARS`

## 交付资产入口

如果目标是把当前项目整理成交接材料，优先看：

1. [`handoff/README.md`](handoff/README.md)
2. [`handoff/稳定交接包说明.md`](handoff/稳定交接包说明.md)
3. [`handoff/快速启动手册.md`](handoff/快速启动手册.md)
4. [`handoff/联调排障手册.md`](handoff/联调排障手册.md)
5. [`handoff/系统架构图.md`](handoff/系统架构图.md)
6. [`handoff/已知问题清单.md`](handoff/已知问题清单.md)
