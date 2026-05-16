# v5 OTA 远程固件升级设计

日期：2026-05-15

## 背景

v5 当前已经完成 ESP32-S3 / ESP-VoCat v1.2 的 Opus framed-v1 流式上行、火山 ASR 优先、DashScope fallback、云端 v5 80 端口联调和 v26 板端交付包。下一阶段需要补齐远程 OTA，避免后续每次参数、链路或板端策略调整都依赖人工烧录。

当前板端分区表只有 `factory` 和 `storage`：

```text
nvs        data  nvs      0x9000   0x6000
phy_init   data  phy      0xf000   0x1000
factory    app   factory  0x10000  2M
storage    data  spiffs            4M
```

该布局不能做安全 A/B OTA。要支持远程升级和失败回滚，必须先引入 `otadata`、`ota_0`、`ota_1`。

领导提到后续可能增加一颗简单显示屏用的显示芯片。由于只有 ESP32-S3 联网，显示芯片 OTA 需要由 ESP32 下载固件后通过内部串口转发。因此 OTA 设计需要从一开始区分两类固件：

- ESP32-S3 主控固件：ESP-IDF 标准 A/B OTA。
- 显示芯片固件：ESP32 作为下载器和 UART 刷写代理。

## 目标

1. 支持 ESP32-S3 主控远程 OTA，具备断电保护和失败回滚。
2. 支持云端按设备、批次、版本做灰度发布。
3. OTA 不影响当前 v5 语音主链路稳定性；默认只在 idle 状态检查和执行。
4. 预留未来显示芯片 UART OTA 的协议边界，但不在第一版强行实现未知硬件协议。
5. OTA 包和 manifest 不包含任何云端密钥，板端不持有供应商 API key。

## 非目标

1. 第一版不做显示芯片真实刷写，除非显示芯片型号、bootloader 协议和引脚已经确定。
2. 第一版不做强制全量推送；先白名单样机灰度。
3. 第一版不做差分 OTA；直接整包升级，降低复杂度。
4. 第一版不改 v5 ASR / RAG / LLM / TTS / 下行播放逻辑。
5. 不通过覆盖 `factory` 分区实现升级。

## 推荐分区

ESP32-S3 当前配置为 16MB flash，建议改为 A/B 布局：

```text
# Name,     Type, SubType, Offset,   Size
nvs,        data, nvs,     0x9000,   0x6000   # ends at 0xF000
otadata,    data, ota,     0xF000,   0x2000   # ends at 0x11000
phy_init,   data, phy,     0x11000,  0x1000   # ends at 0x12000
ota_0,      app,  ota_0,   0x20000,  3M       # ends at 0x320000
ota_1,      app,  ota_1,            3M        # auto follows ota_0, ends at 0x620000
storage,    data, spiffs,          4M        # starts at 0x620000
```

说明：

- ESP-IDF 分区 offset 的结束地址按半开区间理解：`nvs` 占用 `[0x9000, 0xF000)`，`otadata` 从 `0xF000` 开始，不重叠。
- v26 app bin 约 `0x37c40`，当前远小于 3M。
- 3M app 分区给后续 OTA、显示芯片代理、更多日志和联网逻辑留余量。
- SPIFFS 当前用于本地提示音，保留 4M。
- 剩余 flash 可后续按需要分给 `ota_cache`、`display_fw_cache` 或扩大 SPIFFS。

如果后续显示芯片固件较大，建议新增独立 data 分区作为下载缓存：

```text
display_fw, data, undefined, , 2M
```

第一版可以先用 streaming download 直接写目标 OTA 分区，不需要额外缓存 ESP32 主控固件。

## 云端接口设计

新增 v5 OTA 接口，建议挂在现有 FastAPI 服务下：

```text
GET /api/v5/ota/manifest
GET /api/v5/ota/firmware/{artifact_name}
POST /api/v5/ota/report
```

### Manifest 请求参数

板端请求 manifest 时携带：

```text
device_id
board
hw_rev
app_version
idf_version
ota_slot
display_fw_version 可选
```

建议 HTTP header 或 query 均可，第一版优先 query，便于 curl 调试。

### Manifest 响应

响应支持多个 target，为显示芯片 OTA 预留：

```json
{
  "device_id": "esp32s3-demo-001",
  "poll_interval_sec": 3600,
  "updates": [
    {
      "target": "esp32s3",
      "version": "v27",
      "artifact": "esp32s3_v27.bin",
      "url": "http://106.54.240.51/api/v5/ota/firmware/esp32s3_v27.bin",
      "size": 245760,
      "sha256": "hex...",
      "force": false,
      "min_version": "v25",
      "release_id": "2026-05-15-v27",
      "notes": "v5 ota mvp"
    }
  ]
}
```

无升级时：

```json
{
  "device_id": "esp32s3-demo-001",
  "poll_interval_sec": 3600,
  "updates": []
}
```

多候选 release 选择规则：

- 云端按 `updates[]` 顺序返回候选版本，列表顺序就是推送优先级。
- 板端选择第一个 `target=esp32s3`、`enabled=true` 或未显式禁用、`min_version <= current_version`、且 board/hw_rev/白名单规则匹配的 release。
- 如果多个候选都匹配，板端不自行排序、不选最高版本，只取第一个，保证云端可通过列表顺序控制灰度。
- `force=true` 只允许在设备白名单命中时覆盖普通版本门槛，不能绕过 target、sha256、size 校验。

### Report 请求

板端上报 OTA 结果：

```json
{
  "device_id": "esp32s3-demo-001",
  "target": "esp32s3",
  "from_version": "v26",
  "to_version": "v27",
  "release_id": "2026-05-15-v27",
  "stage": "downloaded|verified|installed|boot_ok|failed|rolled_back",
  "ok": true,
  "error_code": null,
  "error_message": null,
  "free_heap": 123456,
  "rssi": -55
}
```

## 云端数据模型

第一版可以用 JSON 文件或 SQLite，优先沿用项目现有 SQLite 风格。需要三类记录：

1. 设备表
   - `device_id`
   - `board`
   - `hw_rev`
   - `app_version`
   - `ota_slot`
   - `display_fw_version`
   - `last_seen_at`

2. 发布表
   - `release_id`
   - `target`
   - `version`
   - `artifact_path`
   - `sha256`
   - `size`
   - `enabled`
   - `force`
   - `created_at`

3. 灰度规则表
   - `release_id`
   - `device_id` 白名单，可选
   - `batch` 可选
   - `percent` 可选
   - `min_version`
   - `max_version` 可选

第一版建议只做设备白名单，避免样机期误推。

## 板端 ESP32 OTA 流程

板端新增 `ota_manager`，只在 idle 状态执行，不抢录音、播放和 WebSocket 主链路。

`idle` 的代码判定必须显式收敛为：

```text
idle = !recording && !playing && !websocket_connected && !updating
```

WebSocket 刚断开后不应立刻启动 OTA。建议记录 `last_websocket_disconnected_at`，断开后至少延迟 5 秒再允许 manifest check 或下载，避免和云端会话清理、板端播放收尾、状态上报竞争。

启动流程：

1. 初始化 OTA 状态。
2. 如果当前 app 为 pending verify，先跑最小自检。
3. 自检通过后调用 `esp_ota_mark_app_valid_cancel_rollback()`。
4. 自检失败则让 bootloader 回滚。

检查流程：

1. Wi-Fi 已连接。
2. 当前不在录音、ASR、播放、升级中。
3. 请求 `/api/v5/ota/manifest`。
4. 如果无 `esp32s3` update，结束。
5. 校验 board/hw_rev/min_version/size。
6. 下载固件到 OTA 分区。
7. 流式计算 SHA256。
8. SHA256 匹配后 `esp_ota_set_boot_partition()`。
9. 上报 `installed`。
10. 延迟重启。

重启后：

1. 新固件启动。
2. Wi-Fi、NVS、SPIFFS、音频基础初始化通过。
3. 上报 `boot_ok`。
4. 标记 app valid。

失败处理：

- Manifest 请求失败：保持当前版本。
- 下载失败：保持当前版本，上报 failed。
- SHA256 不匹配：丢弃，上报 failed。
- 写分区失败：保持当前版本，上报 failed。
- 新固件启动失败：bootloader 回滚到旧版本。

## 显示芯片 UART OTA 预留

显示芯片 OTA 不应和 ESP32 主控 OTA 混在同一个执行器里。建议预留独立模块：

```text
ota_manager.c
ota_esp32.c
ota_display_uart.c
```

第一版 `ota_display_uart` 只允许做显式不可用实现：

- 初始化状态机和日志 tag。
- 对外入口直接返回 `ESP_ERR_NOT_SUPPORTED`。
- 串口日志必须打印：`display OTA not implemented, need hardware confirmation`。
- 不允许静默返回成功，也不允许下载显示芯片固件后丢弃。

Manifest 中显示芯片 target 示例：

```json
{
  "target": "display_mcu",
  "version": "d003",
  "artifact": "display_d003.bin",
  "url": "http://106.54.240.51/api/v5/ota/firmware/display_d003.bin",
  "size": 131072,
  "sha256": "hex...",
  "transport": "uart",
  "baudrate": 921600,
  "release_id": "2026-05-15-display-d003"
}
```

显示芯片 OTA 需要硬件和 bootloader 确认以下信息后才能实现：

- UART 号和 ESP32 引脚。
- 显示芯片 reset / boot 控制脚。
- 是否支持进入 bootloader。
- 分包大小。
- ACK/NACK 格式。
- CRC 或 SHA 校验方式。
- 版本读取命令。
- 写入完成后的重启命令。
- 失败后是否有显示芯片自身回滚机制。

ESP32 对显示芯片 OTA 的职责：

1. 下载显示芯片固件。
2. 校验 size 和 SHA256。
3. 拉 reset/boot 让显示芯片进入升级模式。
4. 通过 UART 分包发送。
5. 等待 ACK/NACK。
6. 失败重试有限次数。
7. 完成后查询版本并上报。

如果显示芯片没有 A/B 或安全回滚，第一版必须只允许白名单样机升级，不能全量推送。

## 安全策略

第一版最低要求：

- 固件必须校验 SHA256。
- manifest 不允许降级，除非 `force=true` 且设备白名单命中。
- 固件 URL 只从 manifest 获取，不接受板端外部输入。
- OTA 只在 idle 状态执行。
- OTA 过程不打印 Wi-Fi 密码、token、云端密钥。
- 云端发布目录不放 `.env`。

后续量产建议：

- HTTPS。
- 固件签名校验。
- 设备级 token。
- 防重放版本号。
- 分批灰度和自动暂停规则。

## 可观测性

板端串口日志至少记录：

```text
ota_check_start device_id=... version=...
ota_manifest_result update_count=...
ota_download_start target=esp32s3 version=... size=...
ota_download_progress bytes=...
ota_verify_ok sha256=...
ota_install_ok next_slot=...
ota_boot_pending_verify version=...
ota_boot_mark_valid version=...
ota_failed stage=... error_code=...
```

云端 report 需要能查：

- 哪台设备升级了。
- 从哪个版本升级到哪个版本。
- 是否成功。
- 失败在哪个阶段。
- 是否发生回滚。

## 实施阶段

### P0：设计和分区验证

- 写本文档。
- 确认 16MB flash 分区布局。
- 确认当前 SPIFFS 提示音是否能放进新布局。
- 确认 OTA app 分区大小至少 3M。

### P1：ESP32 主控 OTA MVP

- 新增云端 manifest / firmware / report 接口。
- 新增板端 `ota_manager` / `ota_esp32`。
- 改分区表为 A/B OTA。
- 本地构建验证。
- 先通过 PC curl 下载验证 artifact。
- 再真机从 v26 升 v27。

### P2：灰度发布

- 增加设备白名单。
- 增加 release enabled 开关。
- 增加 report 查询脚本。
- 样机小范围验证。

### P3：显示芯片 UART OTA 预留

- 增加 manifest target 解析。
- 增加 `ota_display_uart` 状态机骨架，但入口必须返回 `ESP_ERR_NOT_SUPPORTED`，并打印 `display OTA not implemented, need hardware confirmation`。
- 等硬件和 bootloader 协议确定后再实现真实刷写。

### P4：量产安全增强

- HTTPS 和证书策略。
- 固件签名。
- 设备身份认证。
- 自动暂停灰度。
- OTA 压缩包或差分包评估。

## 验证计划

P1 必须验证：

1. `idf.py build` 通过。
2. `python -m pytest -q` 通过。
3. 新分区下 SPIFFS 能挂载，本地提示音能播放。
4. v5 Opus 上行真机链路不回退。
5. OTA manifest 无升级时不影响主流程。
6. OTA 下载中断后仍能启动旧版本。
7. SHA256 错误时拒绝升级。
8. v26 -> v27 升级成功后标记 app valid。
9. 人为制造新固件自检失败时能回滚。
10. OTA 下载过程中手动断电，上电后必须回到旧版本，不能卡在 bootloader 循环。

显示芯片 OTA 后续验证：

1. 显示芯片版本读取。
2. 串口进入 bootloader。
3. 分包 ACK/NACK。
4. CRC/SHA 错误拒绝。
5. 中断后可恢复或明确失败。
6. 升级后版本号正确。

## 当前推荐决策

先做 ESP32-S3 主控 A/B OTA MVP。显示芯片 OTA 只预留 manifest 和模块边界，不实现具体刷写协议。这样能最快解决样机远程升级问题，同时不会把未定型显示芯片硬件风险带入当前 v5 主链路。
