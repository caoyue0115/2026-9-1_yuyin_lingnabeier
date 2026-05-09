# Audio Downlink Decouple Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `v3 realtime` 下行链路改成 `receive -> decode -> playback`，把 Opus 解码从当前串行收流路径中剥离，降低 `bug31` 这类崩溃和收流反压风险。

**Architecture:** 复用现有 `audio_out` jitter/playback 作为最终播放端，只在 `cloud_client` 内新增“编码包队列 + 解码任务 + 控制事件传播”。第一版不改协议，不改上行录音，不引入静默丢包策略。

**Tech Stack:** ESP-IDF 5.5.4, FreeRTOS queue/task, esp_http_client, esp_opus_dec, existing audio_out jitter path

---

### Task 1: 基础对象与控制语义

**Files:**
- Modify: `esp_idf_demo/main/cloud_client.c`
- Modify: `esp_idf_demo/main/cloud_client.h`

- [ ] 定义 `PACKET / EOF / ERROR` 事件类型
- [ ] 定义 `encoded_packet_t` / `pcm_packet_t`
- [ ] 写清对象所有权：入队即转移、消费方释放
- [ ] 为后续 queue 统计预留字段

### Task 2: 解码任务与队列骨架

**Files:**
- Modify: `esp_idf_demo/main/cloud_client.c`
- Modify: `esp_idf_demo/main/config.h`

- [ ] 新增 `encoded_queue` 与 `pcm_queue`
- [ ] 新增 `decode task`
- [ ] 给 `decode task` 单独栈与运行时日志
- [ ] 先让 `decode task` 支持 `PCM passthrough` 与 `Opus decode`

### Task 3: 收流路径改为只产出编码包

**Files:**
- Modify: `esp_idf_demo/main/cloud_client.c`

- [ ] 让 receive 路径只做 HTTP read + framed/legacy parse
- [ ] 不再在 receive 路径里直接 decode 或直接回调播放
- [ ] 队列满时统一转 `ERROR` 并停止继续收流

### Task 4: 协调与收尾

**Files:**
- Modify: `esp_idf_demo/main/cloud_client.c`
- Modify: `esp_idf_demo/main/main.c`

- [ ] 由 pipeline/协调层等待 `receive/decode/playback`
- [ ] 明确 `EOF/ERROR` 传播顺序
- [ ] 为每段等待加超时
- [ ] 保留 summary，并补充 queue/decode 指标

### Task 5: 验证

**Files:**
- Modify: `esp_idf_demo/main/*` as needed

- [ ] 跑 `idf.py build`
- [ ] 检查启动日志和 summary 字段是否完整
- [ ] 如构建通过，重新打交付包
