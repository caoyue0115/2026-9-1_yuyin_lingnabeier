# Local WebSocket task-stack patch

This component is based on Espressif `esp_websocket_client` 1.7.0 at commit
`b385915ca011094238f5e8ebc45d539183b09cf2`.

The ESP-VoCat demo keeps the upstream 6 KB WebSocket task size, but creates
that task with `xTaskCreatePinnedToCoreWithCaps()` so its stack is allocated
from PSRAM. The matching exit path uses `vTaskDeleteWithCaps()`. The task TCB
remains in internal RAM.

This prevents repeat conversations from failing with
`Error create websocket task` after internal RAM becomes fragmented.
