# 录音前提示、等待开口与 Intro 并行设计

日期：2026-04-14

## 背景

当前板端下行 `Opus + framed-v1` 主链路已经基本稳定，`bug40` 说明 `stream_audio` 的假超时问题已被压住，系统开始进入体验优化阶段。

当前交互仍有三个明显缺口：

1. 按键触发后没有明确的“开始说话”提示。
2. 按键后会立即进入正式录音，用户如果慢半拍开口，正式录音时长会被浪费。
3. 开场音 `intro` 仍是串行播放，拉高了首个云端音频到达用户耳边的总时延。
4. `waiting_speech` 超时与首次麦克风初始化失败时，用户仍缺少明确的本地重试反馈。

## 目标

分两阶段完成以下体验优化：

1. 板端本地固定提示音播报“阿弥陀佛，请说”。
2. 按键后新增“等待用户开口”状态，用户真正开始说话后再进入正式录音。
3. `waiting_speech` 超时或麦克风初始化最终失败时，播报本地重试提示音。
4. 在前几项稳定后，再做 `intro + /audio` 并行。

## 非目标

本轮不做以下内容：

1. 不把录音前提示改成云端 TTS。
2. 不在第一阶段同时改造 `intro + /audio` 并行。
3. 不引入新的复杂 VAD 模型，仅复用现有轻量能量阈值。
4. 不尝试用“首次多等一会儿”来掩盖 `ES7210` 初始化失败问题。

## 关键判断

### 1. 录音前提示应使用本地固定资源

提示语“阿弥陀佛，请说”应使用板端本地固定音频资源，例如：

- `/spiffs/record_prompt_1.pcm`

理由：

1. 延迟更低，触发后可立即播报。
2. 不依赖网络或云端 TTS。
3. 和当前 `intro_1.pcm` 的资源管理方式一致，便于硬件联调。

### 2. “等待开口”应成为显式状态

按键后不应立刻进入正式录音，而应先进入新状态：

- `waiting_speech`

建议状态流：

- `idle -> playing_prompt -> waiting_speech -> recording -> posting_session -> ...`

其中：

1. `playing_prompt` 负责本地播报“阿弥陀佛，请说”。
2. `waiting_speech` 负责开麦等待用户真正开口。
3. 只有检测到开口后，才进入正式 `recording`。

### 3. 正式录音时长应从“检测到开口”开始计时

当前“最长 4 秒”的语义应调整为：

- 用户开口后最长录音 4 秒

而不是：

- 按键后立刻开始消耗 4 秒预算

这样能避免：

1. 用户按键后反应慢，正式录音时间被提示和迟疑吃掉。
2. 最终上传的是“前面一大段空白 + 后面半句有效语音”。

### 4. `intro + /audio` 并行放第二阶段

虽然 `bug40` 说明下行主链路已经稳定，但当前队列峰值仍长期接近上限，因此不建议把“录音前提示/等待开口”和“intro 并行”放在同一轮实现。

第二阶段再做：

- 本地 `intro` 播放期间提前打开 `/audio`
- 允许先收流、先缓存，但不立即打断 `intro`

## 第一阶段设计

### 新资源

新增本地提示音文件：

- `/spiffs/record_prompt_1.pcm`

约束：

1. 格式与现有本地 PCM 提示音保持一致：
   - `16kHz`
   - `16-bit`
   - `mono`
2. 文件缺失时允许降级：
   - 记录 warning
   - 继续进入 `waiting_speech`

新增两条本地重试提示音：

- `/spiffs/record_retry_timeout_1.pcm`
- `/spiffs/record_retry_error_1.pcm`

建议默认文案：

- timeout：`请再讲一次。`
- mic init 最终失败：`请再试一次。`

### 新状态

新增应用状态：

- `APP_STATE_PLAYING_PROMPT`
- `APP_STATE_WAITING_SPEECH`

状态流：

1. GPIO 触发
2. 播放 `record_prompt_1.pcm`
3. 当最后一个 PCM chunk 已提交并且本地播放路径已 drain 完成后，才进入 `waiting_speech`
4. 检测到语音起点
5. 进入正式 `recording`
6. 沿用现有 VAD 结束与后续上传流程

### 等待开口逻辑

新增等待窗口，例如：

- `DEMO_WAIT_FOR_SPEECH_TIMEOUT_MS = 3000`
- `DEMO_WAITING_SPEECH_ARM_MS = 100~200`
- `DEMO_SPEECH_START_HOLD_MS = 80~150`

行为：

1. 提示音播放完成后打开麦克风。
2. 麦克风打开后先进入一个很短的 `arm` 保护窗口。
3. 在 `DEMO_WAITING_SPEECH_ARM_MS` 期间只采样，不触发开口判定。
4. 保护窗口结束后，轮询当前轻量能量阈值。
5. 只有连续超过 `DEMO_RECORD_VAD_START_THRESHOLD` 达到 `DEMO_SPEECH_START_HOLD_MS`，才视为用户已开口。
4. 若超时仍未开口：
   - 播放 timeout 重试提示音
   - 结束本轮流程
   - 不上传空音频
   - 状态回 `idle`

这样可以降低以下误触发：

1. 按键声
2. 机身摩擦声
3. 环境短脉冲噪声
4. 提示音结束后的尾波或音频外设切换毛刺

### 录音逻辑调整

新增一条录音入口，语义为：

- 等待开口后开始正式录音

对应最大录音预算应显式拆成独立常量：

- `DEMO_RECORD_AFTER_SPEECH_MAX_MS`

实现层面可以拆成：

1. `audio_in_wait_for_speech_start(...)`
2. `audio_in_record_after_voice_start(...)`

第一阶段不要求立刻做成非常抽象的通用录音状态机，但必须做到：

1. 等待开口阶段与正式录音阶段语义清楚分离。
2. 等待阶段不占用正式录音 4 秒预算。
3. 仍复用现有轻量 VAD 阈值与静音结束逻辑。

### 麦克风初始化失败重试

第一阶段增加一次受控重试：

- `DEMO_MIC_INIT_RETRY_COUNT = 1`
- `DEMO_MIC_INIT_RETRY_DELAY_MS = 150`

行为：

1. `audio_in_wait_for_speech_start(...)` 若首次因 mic init / open 失败返回错误：
   - `audio_in_deinit()`
   - 短暂等待
   - 再重试一次
2. 若第二次仍失败：
   - 播放本地错误重试提示音
   - 本轮结束
   - 回 `idle`

约束：

1. 不做无限重试
2. 不用长时间固定 delay 掩盖问题
3. 日志必须明确区分：
   - 首次失败
   - 进入 retry
   - retry 后仍失败

### 失败与降级

第一阶段的降级策略：

1. 提示音文件缺失：
   - warning，必须明确打印文件路径和错误原因
   - 继续 `waiting_speech`
2. 若 SPIFFS 未挂载或资源分区明显异常：
   - 打印更明确的错误
   - 不静默吞掉
2. 麦克风初始化首次失败：
   - 做一次受控短重试
3. 麦克风初始化重试后仍失败：
   - 播放本地错误重试提示音
   - 返回 `idle`
4. 等待开口超时：
   - 播放本地 timeout 重试提示音
   - 不上传
   - 不保留等待阶段残片
   - 回 `idle`

## 第二阶段设计

### `intro + /audio` 并行

在第一阶段稳定后，再做：

1. `intro` 播放开始后，立即并行发起 `/audio` 收流。
2. `/audio` 到达的音频先进入现有 `receive/decode/playback` 缓冲链路。
3. 第一版不允许云端音频打断本地 `intro`。
4. 默认始终是 `intro` 优先播完。
5. 只有 `intro` 结束后，才释放 playback 消费云端缓冲数据。

也就是说，第二阶段并行的是收流，不是抢播。

### 第二阶段前提

只有满足以下条件才进入第二阶段实现：

1. 第一阶段“录音前提示 + 等待开口”真机验证稳定。
2. 当前串行下行链路连续多轮 `pipeline result=ok`。
3. 队列指标虽高但不再引发失败。

## 可观测性

第一阶段建议新增以下日志：

1. `stage=record_prompt event=start/done`
2. `stage=waiting_speech event=start`
3. `stage=waiting_speech event=armed`
4. `stage=waiting_speech event=speech_detected elapsed_ms=...`
5. `stage=waiting_speech event=timeout`
6. `stage=recording event=start reason=speech_detected`
7. `record_budget_ms=...`
8. `stage=waiting_speech event=mic_init_retry attempt=...`
9. `stage=waiting_speech event=mic_init_retry_failed`
10. `stage=retry_prompt event=start/done reason=...`

第二阶段建议新增以下日志：

1. `stage=intro_and_audio_parallel event=start`
2. `audio_open_during_intro_ms=...`
3. `intro_end_backlog_receive_queue=...`
4. `intro_end_backlog_decode_queue=...`
5. `intro_end_pcm_backlog_ms=...`

## 风险

### 风险 1：录音前提示和麦克风初始化互相抢占

提示音播放与麦克风初始化都涉及音频外设，若顺序处理不清，可能放大 `ES7210/ES8311` 初始化问题。

规避方式：

1. 第一阶段先串行：
   - 先播提示音
   - 再初始化录音链路
2. 不把“多等几百毫秒”作为主修法。
3. 内部保留一个后手：
   - 若后续确认麦克风初始化耗时明显影响体验，再考虑“提示音播放期间预初始化录音链路，但不开始采样”
   - 第一阶段先不这样做

### 风险 2：等待开口阈值过严或过松

1. 过严会出现按键后迟迟进不了录音。
2. 过松会把环境噪声误判成开口。

规避方式：

1. 第一阶段复用当前阈值，不一次引入太多新参数。
2. 通过真机日志观察开口命中率后再微调。

### 风险 3：并行 `intro` 会再次放大 backlog

即使 `bug40` 已经稳定，并行后仍会把 backlog 提前压入队列。

规避方式：

1. 第二阶段必须单独实现、单独验证。
2. 上并行前先确认第一阶段稳定。
3. 第二阶段补 backlog 上限观测与告警，至少记录：
   - `intro_end_backlog_receive_queue`
   - `intro_end_backlog_decode_queue`
   - `intro_end_pcm_backlog_ms`

## 实施顺序

1. 新增本地提示音资源与播放阶段。
2. 新增 `waiting_speech` 状态与开口等待逻辑。
3. 调整正式录音预算语义为“开口后计时”。
4. 做第一阶段真机验证。
5. 第一阶段稳定后，再实现 `intro + /audio` 并行。

## 成功标准

第一阶段成功标准：

1. 按键后会播报“阿弥陀佛，请说”。
2. 用户未开口时不会上传空音频。
3. 用户开口后才进入正式录音。
4. 正式录音时长不再被按键后的迟疑时间浪费。
5. 在安静和普通室内环境下，`waiting_speech -> recording` 的误触发率可接受，且日志可观测。
6. `waiting_speech` 超时后，用户能听到明确的本地重试提示。
7. 首次 mic init 偶发失败时，单次重试可覆盖“第二次正常”的场景；若仍失败，用户能听到明确的本地失败提示。

第二阶段成功标准：

1. `intro + /audio` 并行后，`first_audio_byte_local_ms` 明显下降。
2. 不引入新的 `queue full` 或 `stream_audio timeout`。
3. `pipeline result=ok` 保持稳定。
