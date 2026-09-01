# Disney Voice Assistant ESP32 Firmware

设备端沿用现有 v6 N16R8 low-cost 基线：ESP32-S3-WROOM-1、16 MB Flash、8 MB PSRAM、ESP-VoCat V1.0 音频走线与 360×360 圆形显示屏。

## 固定交互

- 唤醒词：`小明同学`
- 语音入口：仅唤醒词，不支持触摸开始录音
- 触摸：仅在背光关闭时点亮屏幕；亮屏时忽略
- 30 秒无操作：背光降到 20%
- 60 秒无操作：背光设为 0
- 唤醒词或熄屏触摸：背光恢复到 85%
- 状态界面：启动、待机、聆听、思考、说话、网络配置、错误

当前 UI 使用 LVGL 绘制可替换的动画占位层。正式玲娜贝儿动画到位后，应只替换显示资源与渲染函数，不修改触摸、语音或网络架构。

## 音频硬件绑定

- I2S DIN/DSIN：`GPIO15`
- PA：`GPIO4`
- GPIO48 speaker/mic enable：不使用
- 默认板型宏：`DEMO_BOARD_PROFILE_ESP_VOCAT_V1_0_AUDIO`
- 默认 profile：`sdkconfig.defaults.vocat_lowcost_16m8m`

## 构建

要求 ESP-IDF 5.5.4：

```bash
. /path/to/esp-idf-v5.5.4/export.sh
cd esp_idf_demo
idf.py set-target esp32s3
idf.py build
```

项目根 `CMakeLists.txt` 默认加载
`sdkconfig.defaults;sdkconfig.defaults.vocat_lowcost_16m8m`，沿用 002/003
验证过的 N16R8 与 ESP-VoCat V1.0 配置。受控 OTA/canary 构建仍可显式覆盖
`SDKCONFIG_DEFAULTS`。

首次构建会由组件管理器下载 `esp_vocat`、LVGL、CST816S 触摸和语音唤醒相关依赖。

## Windows COM7 刷机

```powershell
idf.py -p COM7 flash monitor
```

演示整机在 GMT 办公网内默认使用 `http://192.168.2.106:18124` 和设备 ID
`disney-vocat-demo-001`。

退出 monitor 使用 `Ctrl+]`。刷机前在 `main/config.h` 或编译参数中确认：

- `DEMO_WIFI_SSID`
- `DEMO_WIFI_PASSWORD`
- `DEMO_SERVER_BASE_URL`
- `DEMO_DEVICE_ID`

## 状态映射

| 固件状态 | 屏幕状态 |
|---|---|
| 等待唤醒 | `READY` |
| 提示、等待说话、录音 | `LISTENING` |
| ASR、RAG、LLM、拉取音频 | `THINKING` |
| 播放回答 | `SPEAKING` |
| 技术错误 | `OOPS` |

界面暂用英文短词，避免在未嵌入中文字库时出现方框。正式动画素材接入后可以不显示文本。

## 中性提示音

原仓库中的旧版角色语音提示已从当前产品分支移除。声音样本尚未提供时，启动、开始聆听、追问和错误统一使用中性铃声；云端回答仍由 TTS 生成。
