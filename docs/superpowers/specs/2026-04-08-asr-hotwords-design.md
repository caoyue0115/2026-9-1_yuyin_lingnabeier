# DashScope ASR Hotwords Design

**Goal:** 在现有 DashScope ASR 链路上增加佛学领域热词能力，并将语种提示收紧为中文，以提升“无相”“般若”等术语的识别准确率。

## Decision

本次只做三个最小增强：

- ASR 请求的 `language_hints` 从 `["zh", "en"]` 收紧为 `["zh"]`
- 新增可选配置 `ASR_VOCABULARY_ID`，在识别时透传给 DashScope
- 提供一份首版佛学热词表和一个本地/云端可运行的热词创建脚本

## Why This Shape

- 当前问题是领域词偏置不够，而不是链路不通
- 先加热词比先接 ESP32-S3 AFE 更对症，也更低风险
- 不改动现有 API、队列、数据库结构，回归成本最低

## Runtime Behavior

- 当 `ASR_VOCABULARY_ID` 为空时，ASR 仍可正常工作
- 当 `ASR_VOCABULARY_ID` 存在时，识别请求附带该热词表 ID
- `question_text`、`trace`、错误码行为保持不变

## Assets

- 新增一份首版佛学热词 JSON
- 新增一个脚本用于创建或更新 DashScope 热词表，并输出可直接写入 `.env` 的 `ASR_VOCABULARY_ID`

## Out Of Scope

- 不引入板端 AFE
- 不改为实时流式 ASR
- 不实现自动比较多个 ASR 模型
