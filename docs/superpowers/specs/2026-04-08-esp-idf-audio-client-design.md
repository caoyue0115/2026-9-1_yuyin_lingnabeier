# ESP-IDF Audio Client Design

**Goal:** 提供一个独立的 ESP-IDF 工程，在喵伴 `ESP-VoCat v1.2` 硬件上实现“唤醒 -> 录音 -> 上传云端 -> 轮询结果 -> 下载语音 -> 本地播放”的完整闭环。

**Scope:** 本设计覆盖设备侧最小可跑客户端的喵伴适配方向，不修改云端接口契约；首轮优先打通触摸唤醒和板载音频闭环，语音唤醒作为后续增强项设计进同一状态机。

## 1. Product Fit

本次设备侧交付形态要尽量贴近真实产品，而不是只做开发验证脚本。由于硬件已经明确为喵伴 `ESP-VoCat v1.2`，设计目标从“通用 ESP32-S3 最小板”切换为“优先适配实际板卡”，因此首版适配方向直接覆盖：

- 麦克风录音
- 原始 PCM 上传
- 轮询任务结果
- 返回语音下载
- 扬声器播放

这样可以尽早暴露设备侧最关键的集成风险：板载音频通路、触摸交互、HTTP 传输、WAV 解析和音频播放。

## 2. Hardware Assumptions

当前已知硬件约束如下：

- 目标板：Espressif `ESP-VoCat v1.2（喵伴）`
- 主控：ESP32-S3
- 输入：板载麦克风阵列，经 `espressif/esp_vocat` BSP 暴露的录音接口
- 输出：板载喇叭，经 `espressif/esp_vocat` BSP 暴露的播放接口
- 触发来源：触摸屏点击、提示词/唤醒词
- 开发环境基线：`ESP-IDF 5.5.4`

喵伴适配必须以板级 BSP 或已知可用的板载外设初始化路径为准，不能依赖通用 GPIO 假设。

## 3. User Flow

设备侧交互最小化处理：

1. 上电后连接 Wi-Fi。
2. 初始化触摸输入、音频输入、音频输出。
3. 用户点击触摸屏后进入录音，后续扩展为提示词/唤醒词也可触发录音。
4. 录音完成后将 PCM 数据上传到云端。
5. 设备轮询任务状态。
6. 任务完成后下载返回的 WAV。
7. 设备解析 WAV 头并播放 PCM。
8. 首版全程通过串口打印状态，触摸屏 UI 仅承担最小唤醒职责。

首版串口状态：

- `idle`
- `recording`
- `uploading`
- `polling`
- `downloading`
- `playing`
- `error`

补充约束：

- “触发”是独立模块，不再在状态机里硬编码为单一输入设备
- 触摸唤醒是第一优先级，因为实现确定性更高
- 提示词/唤醒词是同一触发接口下的第二触发源，不要求和触摸同一轮同时落地

## 4. Audio Contract

设备侧严格遵守当前云端契约：

- 采样率：`16kHz`
- 上传 PCM 位宽：`16-bit`
- 声道：`mono`
- 上传内容：原始 PCM
- `Content-Type`：`application/octet-stream`

上传时带以下 Header：

- `x-device-id`
- `x-sample-rate=16000`
- `x-sample-width=16`
- `x-channels=1`

下载结果为标准 WAV，设备只需解析 44 字节左右的 WAV 头并取出 PCM 主体送入播放链路。

板端采集实现单独说明：

- 云端看到的始终是 `16kHz / 16-bit / mono PCM`
- 板端内部采样 slot 位宽可以根据喵伴实际音频驱动决定，不强行要求与上传位宽一致
- 如果板载音频链路底层仍采用 `32-bit slot`，设备端应继续在 DMA 读取后下变换成 `16-bit PCM`

这样区分的原因是：协议格式和板级驱动实现是两层不同约束。对接服务器必须稳定输出 `16-bit PCM`，但板端底层为保证采样稳定可以使用更宽 slot。

## 5. Software Architecture

新工程建议放在：

- `esp_idf_demo/`

目录职责拆分如下：

- `esp_idf_demo/main/main.c`
  主状态机，协调触发、录音、上传、轮询、下载、播放
- `esp_idf_demo/main/trigger_input.c/.h`
  统一触发接口，屏蔽触摸触发和后续语音唤醒触发差异
- `esp_idf_demo/main/audio_in.c/.h`
  板载录音封装，输出 PCM buffer
- `esp_idf_demo/main/audio_out.c/.h`
  WAV 解析与板载播放封装
- `esp_idf_demo/main/cloud_client.c/.h`
  HTTP 上传、轮询、下载
- `esp_idf_demo/main/config.h`
  Wi-Fi、服务地址、录音时长、buffer 大小、触发模式等配置

当前实现已经把 `espressif/esp_vocat` 作为 `idf_component.yml` 依赖，并通过 `esp_codec_dev` 完成录音和播放。

这种拆法的目标是让触发输入、音频输入、音频输出、网络访问四块边界清晰，后续更容易替换成真实产品固件中的模块。

## 6. Recording Strategy

首版不做按住录音或 VAD，采用固定时长录音：

- 触摸触发一次
- 录音 3 到 5 秒
- 录完后自动上传

推荐默认值为 `4 秒`。这样简单、稳定，也足够演示一句短问题。

本轮不使用 AFE，原因：

- 当前优先级是闭环可跑
- 语音识别已通过云端热词显著改善
- AFE 和本地唤醒词更适合后续在真实噪声环境里优化，而不是首轮最小工程

## 7. Cloud Interaction

设备侧固定调用现有接口：

- `POST /api/v2/tasks`
- `GET /api/v2/tasks/{task_id}`

成功路径：

1. 上传 PCM 获取 `task_id`
2. 每秒轮询一次任务状态
3. `status=done` 时读取 `audio_url`
4. 下载 `audio_url`
5. 播放音频

失败路径：

- 上传失败：直接报错并回到 `idle`
- 轮询超时：报错并回到 `idle`
- 任务失败：打印 `error_code` 并回到 `idle`
- 音频下载失败：报错并回到 `idle`
- WAV 解析失败：报错并回到 `idle`

## 8. Error Handling

首版的错误处理原则是“立即失败，串口可见，快速回到待机”。

不做：

- 自动重试多次上传
- 本地缓存未完成任务
- 后台并发多任务

另外增加两类明确错误：

- 触摸初始化或触摸事件读取失败：打印板级输入错误并回到 `idle`
- 板载音频驱动初始化失败：打印板级音频错误并阻止进入录音/播放

这样可以让行为最可预测，便于板端联调。

## 9. Testing Strategy

验收分三层：

### 9.1 Build 验收

- ESP-IDF 工程可编译
- 配置项和组件依赖完整

### 9.2 Device 行为验收

- 上电可连 Wi-Fi
- 触摸可触发一次录音
- 串口能看到状态迁移

### 9.3 End-to-End 验收

- 说出“什么是无相”
- 云端返回 `question_text=什么是无相？`
- 设备成功下载并播放语音结果

### 9.4 Version 验收

- 使用 `ESP-IDF 5.5.4` 可完成构建
- 不依赖已废弃的旧音频 API
- 喵伴相关 BSP 组件版本与 `ESP-IDF 5.5.4` 匹配

## 10. Out Of Scope

以下内容明确不纳入本轮：

- 板端 AFE
- 流式对话
- 完整屏幕 UI
- 多轮会话
- OTA
- 低功耗策略
- 板端本地 ASR/TTS
- 自研提示词检测算法

## 11. Risks

- 喵伴 BSP 的录音和播放路径与当前最小外设版差异较大，若直接沿用现有 `config.h` 引脚定义会导致初始化失败
- `ESP-IDF 5.5.4` 下喵伴相关组件版本若不匹配，可能出现编译通过但运行时初始化失败
- 当前为接入官方触摸接口使用的是完整 `espressif/esp_vocat` BSP，而不是裁剪版 `esp_vocat_noglib`；代价是会额外引入 `LVGL` 相关依赖和更大的固件体积
- 触摸唤醒路径若依赖屏幕驱动初始化顺序，状态机必须避免在屏幕未就绪时进入录音
- 若后续接入提示词/唤醒词，必须避免与云端 ASR 路径混淆，唤醒只负责进入录音，不负责替代上传识别
- 下载 WAV 的大小可能接近内存上限，因此播放实现应支持边收边播或最小缓存

## 12. Design Decision Summary

本轮采用“喵伴 `ESP-VoCat v1.2` + 统一触发接口 + 固定时长录音 + HTTP 上传 + WAV 下载播放”的策略。执行顺序应先完成 `ESP-IDF 5.5.4` 下的触摸唤醒和板载音频闭环，再评估语音唤醒、本地 AFE 和更复杂的交互控制。
