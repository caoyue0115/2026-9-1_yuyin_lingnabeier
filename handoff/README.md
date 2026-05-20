# 交付入口

这组文档用于把当前 Demo 整理成可交接资产，给硬件同事、接手同事或后续维护者直接使用。

建议阅读顺序：

1. [`稳定交接包说明.md`](稳定交接包说明.md)
2. [`快速启动手册.md`](快速启动手册.md)
3. [`联调排障手册.md`](联调排障手册.md)
4. [`硬件compile-only打包手册.md`](硬件compile-only打包手册.md)
5. [`系统架构图.md`](系统架构图.md)
6. [`已知问题清单.md`](已知问题清单.md)

当前交接对象主要有两类：

- 硬件/固件联调同事
- 后续接手当前 Demo 的工程同事

## ESP/硬件交付口径

后续 ESP/硬件同事日常交付统一使用 compile-only 小包：

- 命名：`esp_compile_only_YYYY-MM-DD_vNN.tar.gz`
- 内容：只包含 `esp_idf_demo/` 工程源码、`CMakeLists.txt`、`sdkconfig`、`partitions.csv`、`spiffs/` 和 ESP-IDF 组件依赖声明
- 用途：同事解压后在本机 ESP-IDF 环境执行 `idf.py build` / `idf.py flash monitor`

具体打包结构、排除项、校验和 scp 模板见 [`硬件compile-only打包手册.md`](硬件compile-only打包手册.md)。P3d 002 canary 包以 `tmp/esp_compile_only_v36_p3d_002_20260520.tar.gz` 的结构为固定参考：包内根目录直接是 `esp_idf_demo/`，不能是 bin-only，也不能多包一层版本目录。

不要把 flash-only 包作为默认交付物。flash-only 只用于已经明确“不需要编译、只要快速烧录采日志”的临时场景。

不要把 `esp_hardware_handoff_YYYY-MM-DD_vNN.tar.gz` 大包作为日常硬件传输包。大包只保留为归档/完整源码交接用途。

当前默认设备端基线：

- 开发板：`ESP-VoCat v1.2`
- 核心模组：`ESP32-S3-WROOM-1`
- 工具链：`ESP-IDF 5.5.4`
- 触发方式：`触摸屏`
- 版本口径：`v35 OTA P3c 002 canary 已通过并 closeout + no-intro`
- 录音前提示音：保留 `record_prompt_1.pcm`
- 回答前开场提示音：默认关闭 `DEMO_REALTIME_INTRO_ENABLED=0`
- OTA：P3c 机制已在 002 canary 打通；设备写入 inactive OTA partition，显式设置下一次启动分区，重启后从 OTA 分区启动，并上报 `post_reboot_confirm ok=1`

P3b 不等于已经完成 OTA 启动切换。P3c 才允许 `esp_ota_set_boot_partition()` 和 `esp_restart()`。当前 P3c 仅按 002 单机 canary 收口，不代表全量 OTA 放开；后续扩展到 003 或更多设备必须单独授权、单独 release、单独验证。

当前 OTA 设备口径：

- `miaoban-v1p2-001` 不参与 OTA，继续作为非白名单/no_update 参考样机。
- `miaoban-v1p2-002` 已完成 P3c v35 单机 canary：成功写入 OTA 分区、切 boot、重启进入 `ota_1`，`App version=v35-p3c-canary`，Wi-Fi/server/device_id 配置正常，`partition_write` / `boot_switch_scheduled` / `post_reboot_confirm` 均 `ok=1`，release `2026-05-19-v35-002-p3c` 已 closeout 为 `enabled=0`。
- `miaoban-v1p2-003` 当前仍按 P3a/P3b 既有口径处理，不默认加入 P3c。

当前默认云端基线：

- 服务地址：`http://106.54.240.51`
- 上行接口：`/api/v5/realtime/opus-stream`
- 状态接口：`/api/v3/realtime/sessions/{session_id}`
- OTA manifest：`/api/v5/ota/manifest`
- OTA report：`/api/v5/ota/report`
- OTA report schema：greenunion-sh 当前支持 v34 P3c report 字段，包括 P3b `partition_write` 字段，以及 `boot_partition_before`、`boot_partition_after_set`、`running_partition_after_reboot`、`reboot_reason`
- OTA manifest 防重复：同一 `device_id + release_id` 已上报 `boot_switch_scheduled ok=1` 或 `post_reboot_confirm ok=1` 后，manifest 不应再返回同一个 release；不要把手动删除 002 白名单作为标准流程。

P3c formalization is semi-automatic: release creation must use strict P3c validation, successful canaries are protected by manifest suppress, and canary closeout disables the release instead of deleting whitelist rows. greenunion-sh v5 must stay published on port 80 because device firmware uses `http://106.54.240.51` without an explicit port.

002 发客户前必须通过 P3d rollback validation：先确认设备 bootloader 已启用 `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`，否则 app-only OTA 不能提供自动回滚，需要先刷受控 full package。随后使用 v36 / `2026-05-19-v36-002-p3d` 口径的 rollback-enabled artifact，确认 `partition_write`、`boot_switch_scheduled`、`post_reboot_confirm`、`app_validated` 四阶段均 `ok=1`，并使用 `scripts/ota_release_closeout.py --p3d` 收口。P3d 不包含 003。
