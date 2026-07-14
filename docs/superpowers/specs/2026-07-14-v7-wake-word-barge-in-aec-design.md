# v7 唤醒词打断与 AEC 设计

日期：2026-07-14
状态：已确认（GPT-5.6 审查修订版）
实施阶段：第二部分

## 1. 前置条件

本阶段仅在第一阶段“联网与多轮追问”已经完成、通过 COM4 验收并合并后开始。

第一阶段必须已经提供：

- v6 持久 conversation WebSocket。
- `turn_cancel / turn_cancelled` 协议。
- 第一阶段 `playback_session` 已统一拥有 HTTP、解码、jitter、I2S 和共享取消令牌，并提供幂等 `cancel/join`。
- conversation controller 的状态和剩余追问额度。
- 回答结束后的追问与会话关闭逻辑。

本阶段不得重新设计联网、配网、追问数量、上下文或提示语规则。

## 2. 目标

用户在云端回答播放期间说“小明同学”时，设备能够可靠检测并立即打断回答：

- 有剩余追问额度时，保留当前上下文，播放“请讲”并录制下一次追问。
- 已用完 3 次追问额度时，结束旧上下文并立即开始一条新会话。
- 从 WakeNet 报告命中到扬声器静音的目标不超过约 200ms。
- 设备自身扬声器内容不得频繁误触发 WakeNet。

## 3. 非目标

- 不把回答下行迁移到 WebSocket。
- 不实现任意语音打断，只接受已配置的“小明同学”唤醒词。
- 不让 GPIO7 在回答播放期间打断。
- 不打断本地固定提示音。
- 不修改最多 3 次追问的业务规则。
- 不在 AEC 未通过真机验收前默认开启正式构建功能。

## 4. 当前约束

当前板端已有 I2S TX/RX 双工通道和独立扬声器、麦克风 codec，可以同时收发音频。但现有 WakeNet：

- pipeline 工作期间被停止。
- AFE 使用单麦克风 `M` feed。
- `aec_init`、降噪、VAD和 AGC 均关闭。
- 没有扬声器 PCM 参考通道。

因此仅在回答期间重新启动现有 WakeNet 会把设备自身回答当作麦克风输入，误唤醒风险不可接受。本阶段必须增加同步播放参考和 AEC，而不是只打开并发任务。

## 5. 打断范围

WakeNet barge-in 只在“云端回答音频正在播放”状态接受事件。

以下本地音频播放时禁用 barge-in：

- 开机钟声。
- “阿弥陀佛”。
- “请联网”。
- “请讲 / 请重讲 / 请重试”。
- “善哉”。

连接、录音、ASR等待、5秒静默追问窗口和普通待机继续使用各自现有输入状态，不属于播放期 barge-in。

## 6. 音频与 AEC 架构

### 6.1 播放参考

reference tap 位于实际 codec write 调用之前，复制“解码、重采样、声道转换和软件增益之后、提交给 I2S/codec 的同一批数字采样”。当前 ES8311 音量属于 codec 侧增益，不能声称已经反映在 PCM 中；AEC 配置记录当前 codec 音量档位，并靠真机标定吸收扬声器、房间和麦克风链路增益。

reference buffer 必须：

- 只保存 AEC 所需的短窗口，不积累整段回答。
- 丢帧时记录计数，不阻塞扬声器播放。
- 在回答开始、取消和结束时清空，防止上一轮尾音污染下一轮。
- 使用 PSRAM 优先分配，但控制路径和小块缓冲可留在内部 RAM。
- 每个 reference block 携带单调递增 sample counter；麦克风块使用同一 I2S 时基对应的 sample counter，禁止只靠任务到达时间猜测对齐。

### 6.2 麦克风与参考同步

启用 barge-in 的构建从启动起只创建一次 `MR` AFE，`aec_init=true`，不再先创建 `M` 后运行时切换。普通待机继续给同一 AFE 喂麦克风和全零 reference，但只按现有待机规则接受 WakeNet；云端回答开始时清空 AFE 状态和 reference 队列，切入带真实 reference 的播放期监听。其他处理项保持最小化，除非真机数据证明必须启用。

板级新增唯一 `audio_duplex_session` owner，串行管理 ES8311、ES7210 和共享 I2S data interface 的打开、格式配置、开始、停止与关闭。播放任务、录音任务和 WakeNet task 只能申请 session/提交数据，不得各自重配或销毁 codec/I2S 句柄。状态转换必须等待前一 owner 操作完成，避免关闭麦克风时连带破坏仍在静音收尾的扬声器。

播放开始标定一个可配置的 `mic_minus_reference_delay_samples`，以 sample counter 对齐麦克风块和 reference 块；初始值来自有线/声学 loopback 测量，真机矩阵允许按板型配置。音量变化、underrun、seek、取消或 sample counter 跳变时重置 AFE 和对齐器。时钟漂移或短时 reference 缺帧不得导致越界或死锁。无法取得有效参考时，该音频块不得直接绕过 AEC 喂给 WakeNet；应丢弃该块并记录降级指标，以避免设备自身回答触发。

### 6.3 生命周期

- 云端回答开始实际出声前，由 `audio_duplex_session` 复位常驻 MR AFE、sample counter 对齐器和 reference 队列。
- 回答播放期间持续 feed/fetch。
- 本地提示音开始前停止接受 barge-in。
- 回答正常结束、取消或技术错误时退出播放期接受窗口、清空真实 reference，并恢复待机的零 reference feed；不销毁 AFE 模型。
- 功能关闭的构建继续使用现有 `M` AFE；功能开启的构建始终使用常驻 `MR` AFE，禁止同一次启动中切换 feed shape。

## 7. 打断状态机

### 7.1 有追问额度

当 WakeNet 在云端回答播放期间检测到“小明同学”：

1. 原子设置 cancel 标志，确保只处理第一次检测。
2. 立即调用第一阶段 `playback_session_cancel(BARGE_IN)`；该 session 统一停止 HTTP 流、解码、jitter 和 I2S 写入。
3. `playback_session` owner 清空接收、解码和播放队列；WakeNet task 不直接操作这些资源。
4. 向服务器发送当前轮 `turn_cancel`；取消确认可异步到达，不阻塞本地静音。
5. 停止播放期 WakeNet/AEC，清空 reference buffer。
6. 保留约 150ms 扬声器尾音保护时间。
7. 播放本地“请讲”。
8. 使用现有录音/VAD开始追问。
9. ASR 返回有效问题后才消耗一次追问额度。

被打断回答的文本可留在服务器当前会话上下文中，但必须标记为 `interrupted=true`。后续 LLM可以知道上一轮回答未完整播放，避免假设用户已经听完全部内容。

### 7.2 追问额度耗尽

如果 3 次追问额度已经用完，但用户在最后回答期间说“小明同学”：

1. 立即停止最后回答并发送 `turn_cancel`。
2. 发送旧会话 `conversation_end`，原因为 `barge_in_new_conversation`。
3. 不播放“善哉”，因为旧回答未正常完成。
4. 建立新的 v6 conversation WebSocket。
5. 播放“请讲”并录制新问题。
6. 新会话重新拥有最多 3 次追问额度，不继承旧上下文。

### 7.3 正常结束

未发生打断时完全沿用第一阶段规则：

- 回答结束后静默等待 5 秒。
- 任意窗口无人说话时播放“善哉”。
- 第 3 次追问回答完成后静默约 0.5 秒，再播放“善哉”。

## 8. 取消接口

板端复用第一阶段已经落地的幂等取消接口，而不是在第二阶段新增另一套资源所有权：

- `playback_session_cancel(session_id, reason)`：设置共享 token 并请求 owner 停止网络读取、解码、队列和 I2S 输出。
- `playback_session_join(session_id, timeout_ms)`：等待 owner 完成清理；重复 join 返回同一终态。
- `cloud_conversation_cancel_turn(turn_id)`：发送一次 `turn_cancel`。
- conversation controller 统一决定后续是同会话追问还是新会话。

取消可以从 WakeNet task 发出事件，但资源回收由各自 owner task 完成。不得从 WakeNet 回调直接强制删除音频或 WebSocket task。

HTTP 读取、解码和 jitter task 都必须观察同一个取消信号。WakeNet 命中至最后一次 I2S 提交目标不超过 200ms；本地 playback owner 的全部任务在 1 秒内退出，服务器取消屏障在 2 秒内返回。重复取消、取消与自然 EOF 同时发生、取消与网络错误同时发生都必须安全；本地静音不等待服务器屏障。

## 9. 功能开关与降级

新增独立编译期开关 `DEMO_WAKE_WORD_BARGE_IN_ENABLED`：

- 第一阶段和第二阶段初始合并时默认关闭。
- COM4 声学验收和稳定性测试通过后，正式发布配置才启用。
- 开关关闭时必须恢复第一阶段行为：回答期间暂停 WakeNet。

运行时 AEC、麦克风或 reference buffer 初始化失败时：

- 记录明确错误码和一次性告警。
- 当前回答继续正常播放。
- 本次回答禁用 barge-in，不得使用无 AEC 的麦克风输入冒险检测。
- 回答结束后仍进入第一阶段的 5 秒追问窗口。

## 10. 并发与资源约束

- reference producer 不得阻塞现有播放实时路径。
- WakeNet/AEC task 优先级不得饿死 jitter、解码、Wi-Fi或 WebSocket任务。
- 复用模型和固定大小缓冲，避免每轮 PSRAM 碎片增长。
- cancel 到达后所有相关任务必须在有界时间退出，不能留下 codec 句柄、HTTP连接或队列。
- OTA轮询继续遵守空闲门槛，活跃 conversation 或 barge-in 处理期间不得启动 OTA工作。
- 开启功能前记录内部 RAM 最小空闲、最大连续块、PSRAM 最小空闲、各任务栈高水位和两核 CPU 占用基线。开启后所有任务栈至少保留 25%，连续 50 次回答和 20 次打断后内存、任务、队列与 codec 句柄回到允许误差内，且不得逐轮单调恶化。
- reference 队列只覆盖 AEC 所需窗口，满时丢弃最旧块并计数，不得反压扬声器；实现计划根据 AFE frame size 和实测最大调度抖动给出固定字节数。

## 11. 可观测性

新增结构化指标，不记录原始麦克风音频或敏感内容：

- barge-in 监听启动/停止原因。
- reference 写入、丢帧和最大队列深度。
- AEC feed/fetch 错误数。
- reference/mic sample counter 偏差、当前延迟配置和对齐重置原因。
- WakeNet 检测时间。
- 检测到扬声器静音耗时。
- HTTP、解码、jitter 和 I2S 各阶段取消耗时。
- 同会话追问或新会话分支。
- 播放期间误唤醒测试统计。
- AEC 前后残余回声能量或等价的 ERLE 指标、漏唤醒率、误唤醒率和播放 underrun 率。

日志中的 URL、设备标识、请求标识和会话标识继续遵守现有脱敏规则。

## 12. 测试与验收

### 12.1 自动化测试

- barge-in 只在云端回答播放状态接受。
- 所有固定本地提示音状态拒绝 barge-in。
- 首次 WakeNet 事件触发一次取消，重复事件幂等。
- HTTP读取、解码、jitter和播放队列均响应取消。
- `audio_duplex_session` 串行化 codec/I2S 生命周期，覆盖播放开始、录音开始、取消和技术错误竞态。
- 功能开启构建只创建 MR AFE，普通待机用零 reference；功能关闭构建保持 M AFE，运行时不切换 feed shape。
- sample counter 对齐、配置延迟、reference 缺帧、underrun、音量变化和取消均触发预期重置。
- `turn_cancel` 正确发送并处理迟到的 `turn_result`、`turn_cancelled` 和 EOF竞态。
- 有额度时保留 conversation；额度耗尽时创建新 conversation。
- 被打断轮次标记 `interrupted=true`。
- AEC 初始化失败时回退为不可打断播放，回答后仍能追问。
- 功能开关关闭时与第一阶段行为一致。
- 取消后堆、任务、队列、HTTP、WebSocket和 codec 资源回到基线。

### 12.2 COM4 声学验收

至少覆盖：

- 低、中、高三个扬声器音量。
- 近距离、中距离和房间远距离唤醒。
- 安静房间、日常环境噪声和播放佛教回答时唤醒。
- 回答文本含“小明”“同学”或相似音节时不得高频自触发。
- 连续回答不唤醒的长时间误触发测试。
- 首次回答、第一次追问和第三次追问回答期间分别打断。
- 额度耗尽时打断并进入新会话。
- 打断后“请讲”、录音、ASR和新回答完整成功。

性能门槛：

- 从 WakeNet 报告命中到扬声器静音目标不超过约 200ms。
- 连续多次打断无崩溃、看门狗、音频死锁或明显内存增长。
- AEC/WakeNet 并发不得造成回答持续卡顿、严重 underrun 或网络吞吐回退。
- 与关闭功能的同音频基线相比，开启后 underrun 率不增加超过 1 个百分点；内部 RAM/PSRAM 和 CPU/栈指标满足第 10 节预算。
- 声学矩阵记录可复现的误唤醒率、漏唤醒率和 ERLE/残余回声。Demo 放行门槛为连续播放 30 分钟零自唤醒、每个距离/音量组合至少 10 次人工唤醒成功率不低于 90%；客户发布前再根据样机数据收紧。

若 200ms 目标或误唤醒可靠性未达到，功能保持默认关闭，不进入正式发布配置。

## 13. 实施与发布顺序

1. 从已经合并并稳定的第一阶段 main 创建独立分支。
2. 先实现可取消的播放接口和测试，不启用 WakeNet并发。
3. 增加 reference tap、MR feed 和 AEC。
4. 接入 WakeNet事件和 conversation controller。
5. 在 COM4 使用功能开关开启构建，完成声学矩阵。
6. 代码审查通过后合并第二阶段 PR，默认仍关闭。
7. canary 构建启用开关，持续观察误唤醒和资源指标。
8. canary 通过后，在正式发布配置中启用并走 OTA 发布流程。

回滚只需关闭 `DEMO_WAKE_WORD_BARGE_IN_ENABLED` 或回退第二阶段 app；第一阶段联网、多轮协议和追问能力保持可用。
