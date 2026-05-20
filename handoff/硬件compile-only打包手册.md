# 硬件 compile-only 打包手册

## 目标

硬件同事日常交付统一使用 compile-only 源码包，不交付 bin-only 包作为默认物料。

compile-only 包用于让硬件同事在本机 ESP-IDF 环境里自行执行 `idf.py build`、`idf.py flash monitor`，并保留完整串口日志。

P3d canary 包必须带一键构建/烧录入口，避免硬件同事用 VSCode 默认构建导致 `App version: 1`。

## 固定参考

当前打包结构以 v36 包为参考：

```text
tmp/esp_compile_only_v36_p3d_002_20260520.tar.gz
```

新版本包必须保持同一类结构：压缩包根目录只有 `esp_idf_demo/` 工程源码目录，不要额外包一层版本目录，也不要只放 `.bin`。

## 命名

P3d 002 canary 包命名格式：

```text
tmp/esp_compile_only_vNN_p3d_002_YYYYMMDD.tar.gz
```

示例：

```text
tmp/esp_compile_only_v37_p3d_002_20260520.tar.gz
```

## 必须包含

包内应包含这些路径：

```text
esp_idf_demo/
esp_idf_demo/README.md
esp_idf_demo/CMakeLists.txt
esp_idf_demo/dependencies.lock
esp_idf_demo/partitions.csv
esp_idf_demo/sdkconfig
esp_idf_demo/sdkconfig.defaults
esp_idf_demo/sdkconfig.old
esp_idf_demo/main/
esp_idf_demo/main/CMakeLists.txt
esp_idf_demo/main/idf_component.yml
esp_idf_demo/main/config.h
esp_idf_demo/main/main.c
esp_idf_demo/main/cloud_client.c
esp_idf_demo/main/cloud_client.h
esp_idf_demo/main/audio_in.c
esp_idf_demo/main/audio_in.h
esp_idf_demo/main/audio_out.c
esp_idf_demo/main/audio_out.h
esp_idf_demo/main/trigger_input.c
esp_idf_demo/main/trigger_input.h
esp_idf_demo/spiffs/
esp_idf_demo/spiffs/record_prompt_1.pcm
esp_idf_demo/spiffs/record_retry_rearm_1.pcm
esp_idf_demo/spiffs/record_retry_timeout_1.pcm
esp_idf_demo/spiffs/record_retry_error_1.pcm
esp_idf_demo/spiffs/intro_1.pcm
esp_idf_demo/BUILD_INFO.txt
esp_idf_demo/build_flash_p3d_002.ps1
esp_idf_demo/build_flash_p3d_002.cmd
esp_idf_demo/build_flash_p3d_002.sh
```

## 必须排除

不要把这些内容放进硬件日常 compile-only 包：

```text
esp_idf_demo/build/
esp_idf_demo/managed_components/
.git/
.env
.env.*
tmp/
data/
indices/
*.bin
flash-only 包
服务端源码
历史交付包
```

注意：`managed_components` 可能在临时 artifact source 目录里是软链接，也必须排除。否则包结构会和 v36 参考包不一致。

## 标准打包命令

优先使用自动化脚本打包。脚本会排除 `build/`、`managed_components/`、`.env*` 等目录，并自动注入 Windows/Linux 一键入口：

```bash
python3 scripts/package_esp_compile_only.py \
  --source /data/GMT-assets/v37_p3d_artifact_src \
  --output tmp/esp_compile_only_v37_p3d_002_20260520.tar.gz \
  --project-version v37-p3d-canary \
  --device-id miaoban-v1p2-002 \
  --default-port COM3
```

只有在脚本不可用时，才使用手工 `tar` 命令；手工打包必须额外确认包内包含一键脚本。

在仓库根目录执行：

```bash
tar -czf tmp/esp_compile_only_vNN_p3d_002_YYYYMMDD.tar.gz \
  --exclude=esp_idf_demo/build \
  --exclude=esp_idf_demo/managed_components \
  esp_idf_demo
```

如果从 artifact source 目录打包，例如 `/data/GMT-assets/v37_p3d_artifact_src`：

```bash
tar -C /data/GMT-assets/v37_p3d_artifact_src \
  --exclude=esp_idf_demo/managed_components \
  -czf tmp/esp_compile_only_v37_p3d_002_20260520.tar.gz \
  esp_idf_demo
```

## 结构检查

打包后先看包内结构：

```bash
tar -tzf tmp/esp_compile_only_vNN_p3d_002_YYYYMMDD.tar.gz
```

合格结构应该以 `esp_idf_demo/` 开头，不应该出现：

```text
compile_only_vNN_p3d_002_YYYYMMDD/
*.bin
esp_idf_demo/managed_components
esp_idf_demo/build
```

并且必须出现：

```text
esp_idf_demo/BUILD_INFO.txt
esp_idf_demo/build_flash_p3d_002.ps1
esp_idf_demo/build_flash_p3d_002.cmd
esp_idf_demo/build_flash_p3d_002.sh
```

推荐同时和 v36 包做人工对照：

```bash
tar -tzf tmp/esp_compile_only_v36_p3d_002_20260520.tar.gz
tar -tzf tmp/esp_compile_only_vNN_p3d_002_YYYYMMDD.tar.gz
```

## 校验记录

交付前记录：

```bash
ls -lh tmp/esp_compile_only_vNN_p3d_002_YYYYMMDD.tar.gz
sha256sum tmp/esp_compile_only_vNN_p3d_002_YYYYMMDD.tar.gz
```

输出里至少要能给出：

```text
path=
size=
sha256=
```

## Windows scp 模板

```powershell
scp -i "C:\Users\AW\.ssh\id_ed25519" "us-hanxiao-zhu:/home/hanxiao_zhu_us/GMT/20260508_v5_realtime_opus/tmp/esp_compile_only_vNN_p3d_002_YYYYMMDD.tar.gz" "C:\Users\AW\Downloads\esp_compile_only_vNN_p3d_002_YYYYMMDD.tar.gz"
```

v37 示例：

```powershell
scp -i "C:\Users\AW\.ssh\id_ed25519" "us-hanxiao-zhu:/home/hanxiao_zhu_us/GMT/20260508_v5_realtime_opus/tmp/esp_compile_only_v37_p3d_002_20260520.tar.gz" "C:\Users\AW\Downloads\esp_compile_only_v37_p3d_002_20260520.tar.gz"
```

## 交付口径

给硬件同事时说明：

```text
这是 compile-only 源码包，不是 flash-only/bin-only 包。
请解压后进入 esp_idf_demo/，不要点 VSCode 默认 build。
Windows PowerShell 执行：.\build_flash_p3d_002.ps1 COM3
Windows CMD 执行：build_flash_p3d_002.cmd COM3
如果实际串口不是 COM3，请换成设备管理器里的实际 COM 口。
请从上电开始保留完整串口日志；ESP panic/backtrace 默认只在当时 UART 输出，不会自动落盘。
验收日志必须包含 App version: vNN-p3d-canary，不能是 App version: 1。
```

## 常见错误

- 错误：包内只有 `esp_idf_demo_vNN_*.bin`。
  正确：包内应是 `esp_idf_demo/` 源码工程。
- 错误：包内多了一层 `compile_only_vNN_.../`。
  正确：根目录直接是 `esp_idf_demo/`。
- 错误：包内包含 `managed_components` 或 `build`。
  正确：这两个都排除，让对方本机 ESP-IDF 重新解析依赖和编译。
- 错误：硬件同事直接点击 VSCode 默认 build，烧录后显示 `App version: 1`。
  正确：必须执行包内 `build_flash_p3d_002.ps1` 或 `build_flash_p3d_002.cmd`，脚本会强制传入 `PROJECT_VER` 并在构建后校验版本。
