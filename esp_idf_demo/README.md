# ESP-IDF Audio Client Demo

这个独立工程当前用于在喵伴 `ESP-VoCat v1.2` 上跑通设备端语音闭环。

当前默认路径：

`触摸 -> 板载录音 -> 上传 /api/v2/tasks -> 轮询任务 -> 下载 WAV -> 板载播放`

## 当前基线

- 目标板：`ESP-VoCat v1.2`
- 核心模组：`ESP32-S3-WROOM-1`
- 推荐工具链：`ESP-IDF 5.5.4`
- 当前默认触发源：`touch`
- 当前默认板型宏：`DEMO_BOARD_PROFILE_ESP_VOCAT_V1_2`

## 硬件规格补充

当前喵伴板卡基于 `ESP32-S3-WROOM-1`，这里补一份最常用的基础规格，方便硬件联调和板级判断：

- 核心芯片：`ESP32-S3`，`Xtensa` 双核 32 位 `LX7`
- 无线功能：`2.4GHz Wi-Fi (802.11b/g/n)`、`Bluetooth 5`
- 内存规格：当前板卡确认 `PSRAM=16MB`，`Flash` 按当前分区表使用
- GPIO：最多 `36` 个 `GPIO`
- 应用场景：适合 `AIoT`、智能家居、智能控制面板等

## 当前已经完成

- 主流程状态机
- 云端上传、轮询、下载
- WAV 解析和播放框架
- `trigger_input` 抽象
- `ESP-VoCat v1.2` 触摸接入
- `ESP-VoCat v1.2` 的板载录音接入
- `ESP-VoCat v1.2` 的板载播放接入
- 分阶段串口日志和联调参数入口

## 当前主要风险

- 触摸已经可编译接入，但还没有在真实 `ESP-VoCat v1.2` 实板上验证点击坐标和触发手感
- 板载录音和播放已经在 `ESP-IDF 5.5.4` 下编译通过，但还没有在真实 `ESP-VoCat v1.2` 实板上验证音量、增益和实际收放音路径
- 工程依赖完整 `espressif/esp_vocat` BSP，因此首次构建会拉取 `LVGL` 相关组件，构建时间和固件体积都会上升

## 刷机前必须确认的配置

至少要设置下面四项，否则设备不会进入可用的 `idle` 状态：

- `DEMO_WIFI_SSID`
- `DEMO_WIFI_PASSWORD`
- `DEMO_SERVER_BASE_URL`
- `DEMO_DEVICE_ID`

目前这些值定义在 [`main/config.h`](main/config.h) 里，或者通过编译参数覆盖。

另外要确认：

- 你使用的是 `ESP-IDF 5.5.4`
- 当前板型确实是 `ESP-VoCat v1.2`
- 首次构建允许 `idf.py` 下载 `esp_vocat`、`esp_lcd_touch_cst816s`、`lvgl` 等依赖

## 构建与串口

```bash
source /home/aitopia/esp/esp-idf-v5.5.4-full/export.sh
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

如果串口设备名不同，把 `/dev/ttyUSB0` 替换成实际端口。

## 典型串口输出

```text
I esp_idf_demo: ESP-IDF audio demo starting
I esp_idf_demo: Board: ESP-VoCat v1.2
I esp_idf_demo: Runtime config:
I esp_idf_demo:   trigger_source=touch
I esp_idf_demo:   audio_input_gain_db=42.0
I esp_idf_demo:   audio_output_volume=60
I esp_idf_demo:   cloud_poll_interval_ms=1000
I esp_idf_demo: Connecting to Wi-Fi SSID your-ssid
I esp_idf_demo: Wi-Fi connected, IP=...
I trigger_input: Initialized ESP-VoCat v1.2 touch trigger
I trigger_input: Touch trigger event: x=120 y=160
I esp_idf_demo: stage=record event=start
I audio_in: Captured 128000 bytes in 4.000 s
I esp_idf_demo: stage=upload task_id=...
I cloud_client: Poll attempt=1 task_id=... status=processing http_status=200 elapsed_ms=35.1
I cloud_client: Task ... finished with status=done question_text=什么是无相？ error_code=(empty)
I esp_idf_demo: stage=download event=done elapsed_ms=142.6
I audio_out: Playing WAV: rate=24000 Hz channels=1 bits=16 pcm_bytes=...
I esp_idf_demo: pipeline result=ok total_elapsed_ms=12980.4
```

## 实板联调时先看什么

先看启动阶段：

- `Runtime config` 是否打印出预期的 `server_base_url`、`device_id`、`audio_input_gain_db`、`audio_output_volume`
- Wi-Fi 是否拿到 IP
- `Initialized ESP-VoCat v1.2 touch trigger` 是否出现

再看闭环阶段：

- 没有触发：先确认是否有 `Touch trigger event: x=... y=...`
- 触发后无录音：看 `stage=record`
- 录音后无上传：看 `stage=upload`
- 上传后卡住：看 `Poll attempt=... status=...`
- 下载后无声：看 `Playing WAV: rate=... channels=... bits=... pcm_bytes=...`

## 常用调参项

在 [`main/config.h`](main/config.h) 里优先调整这些值：

- `DEMO_AUDIO_INPUT_GAIN_DB`
- `DEMO_AUDIO_OUTPUT_VOLUME`
- `DEMO_RECORD_DURATION_SEC`
- `DEMO_CLOUD_POLL_INTERVAL_MS`
- `DEMO_TRIGGER_POLL_INTERVAL_MS`
