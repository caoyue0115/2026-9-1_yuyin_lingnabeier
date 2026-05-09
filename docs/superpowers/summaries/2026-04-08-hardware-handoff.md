# 硬件联调对接说明

日期：`2026-04-10`

## 1. 适用对象

这份文档给拿到喵伴开发板、准备烧录和联调的同事。
当前默认联调模式已经切到 `v3/realtime`。

当前默认硬件与工具链：

- 开发板：`ESP-VoCat v1.2`
- 模组：`ESP32-S3-WROOM-1`
- 触发方式：`触摸屏`
- 工具链：`ESP-IDF 5.5.4`

`ESP32-S3-WROOM-1` 基本规格补充：

- 核心芯片：`ESP32-S3`，`Xtensa` 双核 32 位 `LX7`
- 无线功能：`2.4GHz Wi-Fi (802.11b/g/n)`、`Bluetooth 5`
- 内存规格：当前板卡确认 `PSRAM=16MB`，`Flash` 按当前分区表使用
- GPIO：最多 `36` 个 `GPIO`
- 应用场景：适合 `AIoT`、智能家居、智能控制面板等

## 2. 分工

- 我这边负责：云服务器、模型服务、接口契约、设备端参考工程
- 硬件同事负责：烧录、串口联调、板级音频问题定位、实板收放音验证

## 3. 已准备好的内容

- 云端接口已可用
- 公网地址已可访问
- 原始 PCM 上传契约已稳定
- `v2` 任务轮询接口已稳定
- `v2` 返回 WAV 下载接口已稳定
- `v3/realtime` session 创建和 `/audio` 拉流接口已稳定
- `ESP-VoCat v1.2` 参考工程已可编译

关键位置：

- 设备端工程：`esp_idf_demo/`
- 工程说明：`esp_idf_demo/README.md`
- 板端联调清单：`20260409_流式传输/板端联调清单.md`

## 4. 云服务器与公网信息

- 公网 IP：旧公网已停用；当前入口需按 greenunion-sh 确认
- SSH：`OLD_PUBLIC_ENTRY_DISABLED_SSH`
- 设备端基准地址：`http://<CURRENT_BASE_URL>`
- 配置项：`DEMO_SERVER_BASE_URL=http://<CURRENT_BASE_URL>`

健康检查：

```bash
curl -sS http://<CURRENT_BASE_URL>/healthz
```

截至 `2026-04-12` 的当前状态：

- 云服务器在线
- `healthz` 正常
- API / worker / redis 正常
- 已实测跑通 `v2` “模拟设备上传 -> 轮询 -> 下载返回音频”的完整链路
- 已实测跑通 `v3/realtime` “模拟设备上传 -> 创建 session -> /audio 拉流”的完整链路
- 当前远端 `v3` 已部署：
  - `LLM_MODEL=qwen3.5-flash-2026-02-23`
  - `extra_body.enable_thinking=false`
  - LLM prompt：“首句 `6` 到 `10` 字、总回答约 `25` 到 `35` 字”
- 最近一次部署后 smoke：
  - session：`2634b2ab-9a66-403a-984b-07e9c811fd68`
  - `first_audio_byte_ms=2628`
  - `done_ms=5302`
  - `audio_duration_ms=10240`
  - `production_ratio=3.908`
  - 脚本虚拟播放器 `underrun_count=0`

因此现在可以开始实板联调。

## 5. 推荐联调流程

当前建议优先按 `v3/realtime` 联调：

1. 开发板连上 Wi-Fi
2. 触摸屏触发一次
3. 板载麦克风录音
4. 上传原始 PCM 到云端，创建 `session`
5. 板端拿到 `session_id` 和 `audio_stream_url`
6. 板端建立 `/audio` 连接
7. 校验响应头
8. 边收 `PCM` chunk 边写 codec
9. 板载喇叭直接出声

`v2` 仍保留在代码里，但当前不作为默认联调链路。

## 6. 接口约定

### 6.1 创建 session

- 方法：`POST`
- 路径：`/api/v3/realtime/sessions`
- 完整地址：`http://<CURRENT_BASE_URL>/api/v3/realtime/sessions`

请求体：

- 原始 PCM 二进制

请求头：

- `Content-Type: application/octet-stream`
- `x-device-id: <设备ID>`
- `x-sample-rate: 16000`
- `x-sample-width: 16`
- `x-channels: 1`

典型返回：

```json
{
  "status": "accepted",
  "session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "audio_stream_url": "http://<CURRENT_BASE_URL>/api/v3/realtime/sessions/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/audio",
  "received_at": "2026-04-10T12:34:56Z"
}
```

### 6.2 查询 session 状态

- 方法：`GET`
- 路径：`/api/v3/realtime/sessions/{session_id}`

重点字段：

- `status`
- `step`
- `final_reason`
- `question_text`
- `answer_text`
- `trace`
- `error_code`
- `error_message`

### 6.3 拉流音频

- 方法：`GET`
- 路径：`/api/v3/realtime/sessions/{session_id}/audio`
- 返回：`HTTP chunked` 裸 `PCM`

响应头固定值：

- `Content-Type: application/octet-stream`
- `X-Audio-Sample-Rate: 16000`
- `X-Audio-Sample-Width: 16`
- `X-Audio-Channels: 1`
- `X-Audio-Endian: little`

## 7. 上传音频规格

上传给服务端的协议格式固定如下：

- 编码：原始 PCM
- 采样率：`16kHz`
- 位宽：`16-bit`
- 声道：`mono`
- 字节序：`little-endian`
- `Content-Type`：`application/octet-stream`

这是实板和服务端真正要对齐的格式。

## 8. 当前设备端基线

当前 `esp_idf_demo/` 的默认实现已经切到：

- 板型：`ESP-VoCat v1.2`
- 触发：`touch`
- 录音：板载麦克风，经 `esp_vocat` BSP + `esp_codec_dev`
- 播放：板载喇叭，经 `esp_vocat` BSP + `esp_codec_dev`
- 构建基线：`ESP-IDF 5.5.4`
- 音频模式：`DEMO_AUDIO_MODE_V3_REALTIME`

刷机前至少要填写：

- `DEMO_WIFI_SSID`
- `DEMO_WIFI_PASSWORD`
- `DEMO_SERVER_BASE_URL`
- `DEMO_DEVICE_ID`

常用调参项：

- `DEMO_AUDIO_INPUT_GAIN_DB`
- `DEMO_AUDIO_OUTPUT_VOLUME`
- `DEMO_RECORD_DURATION_SEC`
- `DEMO_REALTIME_SESSION_TIMEOUT_MS`
- `DEMO_REALTIME_AUDIO_OPEN_TIMEOUT_MS`
- `DEMO_REALTIME_AUDIO_READ_TIMEOUT_MS`

配置文件：

- `esp_idf_demo/main/config.h`

## 9. 烧录命令

```bash
cd esp_idf_demo
source /home/aitopia/esp/esp-idf-v5.5.4-full/export.sh
idf.py set-target esp32s3
idf.py -p /dev/ttyUSB0 flash monitor
```

如果串口不是 `/dev/ttyUSB0`，替换成实际端口。

## 10. 联调时优先看哪些日志

启动阶段先看：

1. `Runtime config`
2. 是否成功连 Wi-Fi
3. `Initialized ESP-VoCat v1.2 touch trigger`

触发后再看：

1. `Touch trigger event: x=... y=...`
2. `stage=record`
3. `stage=post_session`
4. `stage=open_audio`
5. `stage=stream_audio`
7. `pipeline result=ok`

如果联调的是当前默认 `v3`，最关键再看这几项：

1. `session_id=...`
2. `http_status=...`
3. `headers_validated=true`
4. `audio_connect_ms=...`
5. `first_audio_byte_local_ms=...`
6. `playback_start_ms=...`
7. `playback_end_ms=...`
8. `error_code=...`

如果失败，直接看失败发生在哪个 `stage` 和 `error_code`。

## 11. 当前实测延迟

当前 `v3` 远端较优实测为：

- `first_llm_chunk_ms: 2202`
- `first_tts_chunk_ms: 2628`
- `first_audio_byte_ms: 2628`
- `done_ms: 5302`

也就是说当前服务端首包大约在 `2.6s`，总回答大约在 `5.3s`。
如果板端显著慢于这个量级，优先排查：

- `/audio` 建连是否慢
- 响应头是否被代理或服务端改写
- chunk 是否被板端整包等待
- codec 写入是否阻塞
- 播放是否因为云端段间空档而断续

## 12. 常见排查顺序

### 12.1 没有触摸触发

- 看是否出现 `Touch trigger event: x=... y=...`
- 没有的话先看触摸驱动初始化日志

### 12.2 录音后识别不到文本

- 先调高 `DEMO_AUDIO_INPUT_GAIN_DB`
- 再确认环境噪声和说话距离

### 12.3 `/audio` 建连成功但没有声音

- 先调高 `DEMO_AUDIO_OUTPUT_VOLUME`
- 再看 `headers_validated`
- 再看 `first_audio_byte_local_ms`
- 再看 `error_code=codec_write_failed`

### 12.4 建连失败或提前断流

- 先看 `http_status`
- 再看 `error_code=audio_connect_failed | audio_header_mismatch | audio_stream_read_failed | early_eof`
- 再查云端 API / worker 日志

### 12.5 返包说话断断续续

当前板端已经针对 `v3/realtime` 做了两层抗抖：

- 默认关闭 Wi-Fi 省电：`DEMO_WIFI_POWER_SAVE_NONE=1`
- 增加轻量 jitter buffer：HTTP 收到的 `PCM` 先入队，再由播放任务写 codec

bug14 经验：

- 曾尝试增大预缓冲和 jitter buffer
- 当前建议不要继续优先加板端 buffer
- 应先看服务端和 smoke 的生产统计，确认是不是上游产音频速度不足或段间 gap 过大

相关配置：

- `DEMO_REALTIME_AUDIO_JITTER_BUFFER_BYTES=65536`
- `DEMO_REALTIME_AUDIO_JITTER_PREBUFFER_BYTES=40960`
- `DEMO_REALTIME_AUDIO_JITTER_READ_BYTES`

串口优先看：

- `Realtime jitter playback task done total_in=... total_out=... max_level=...`
- `stage=stream_audio event=done elapsed_ms=...`

服务端/脚本优先看：

- `production_ratio`
- `audio_max_chunk_gap_ms`
- `virtual_player.underrun_count`
- `virtual_player.underrun_ms`

## 13. 交付压缩包

给硬件同事时只包含两类内容：

- `esp_idf_demo/`
- 当前这份硬件联调对接文档
