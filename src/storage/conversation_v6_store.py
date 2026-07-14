from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator


class TurnCancelled(RuntimeError):
    """Raised when work attempts to publish after its turn was cancelled."""

    def __init__(self, partial_answer: str = "") -> None:
        super().__init__("turn_cancelled")
        self.partial_answer = partial_answer


class BoundedAudioQueue:
    """A cancellation-aware FIFO whose capacity is measured in bytes."""

    def __init__(self, max_bytes: int, cancel_event: threading.Event) -> None:
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes_must_be_positive")
        self._max_bytes = max_bytes
        self._cancel_event = cancel_event
        self._condition = threading.Condition()
        self._chunks: deque[bytes] = deque()
        self._byte_count = 0
        self._finished = False
        self._revoked = False
        self._close_hooks: list[Callable[[], None]] = []
        self._close_hooks_called = False

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def byte_count(self) -> int:
        with self._condition:
            return self._byte_count

    @property
    def revoked(self) -> bool:
        with self._condition:
            return self._revoked

    @property
    def finished(self) -> bool:
        with self._condition:
            return self._finished

    def put(self, chunk: bytes | bytearray | memoryview) -> None:
        with self._condition:
            self._raise_if_cancelled()
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise TypeError("audio_chunk_must_be_bytes")
            chunk = bytes(chunk)
            if not chunk:
                return
            if len(chunk) > self._max_bytes:
                raise ValueError("audio_chunk_exceeds_queue_capacity")
            while self._byte_count + len(chunk) > self._max_bytes:
                self._condition.wait()
                self._raise_if_cancelled()
            self._raise_if_cancelled()
            if self._finished:
                raise RuntimeError("audio_queue_finished")
            self._chunks.append(chunk)
            self._byte_count += len(chunk)
            self._condition.notify_all()

    def get(self, timeout: float | None = None) -> bytes | None:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            while not self._chunks:
                self._raise_if_cancelled()
                if self._finished:
                    return None
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("audio_queue_get_timeout")
                self._condition.wait(timeout=remaining)
            chunk = self._chunks.popleft()
            self._byte_count -= len(chunk)
            self._condition.notify_all()
            return chunk

    def finish(self) -> None:
        with self._condition:
            if self._revoked:
                return
            self._finished = True
            self._condition.notify_all()

    def revoke(self) -> None:
        self._cancel_event.set()
        with self._condition:
            self._revoked = True
            self._finished = True
            self._chunks.clear()
            self._byte_count = 0
            self._condition.notify_all()

    cancel = revoke

    def add_close_hook(self, hook: Callable[[], None]) -> None:
        if not callable(hook):
            raise TypeError("close_hook_must_be_callable")
        call_now = False
        with self._condition:
            if self._close_hooks_called:
                call_now = True
            else:
                self._close_hooks.append(hook)
        if call_now:
            hook()

    def close_providers(self, timeout: float) -> None:
        with self._condition:
            if self._close_hooks_called:
                return
            self._close_hooks_called = True
            hooks = tuple(self._close_hooks)
            self._close_hooks.clear()

        deadline = time.monotonic() + max(0.0, timeout)
        threads: list[threading.Thread] = []
        for hook in hooks:
            thread = threading.Thread(target=self._call_close_hook, args=(hook,), daemon=True)
            thread.start()
            threads.append(thread)
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

    def __iter__(self) -> Iterator[bytes]:
        while True:
            chunk = self.get()
            if chunk is None:
                return
            yield chunk

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set() or self._revoked:
            raise TurnCancelled()

    @staticmethod
    def _call_close_hook(hook: Callable[[], None]) -> None:
        try:
            hook()
        except Exception:
            pass


class IdempotentTurnBudget:
    """Returns a stable admission decision for each turn identifier."""

    def __init__(self, limit: int) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("turn_budget_limit_must_be_nonnegative")
        self._limit = limit
        self._used = 0
        self._decisions: dict[str, bool] = {}
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self._limit - self._used)

    def consume(self, turn_id: str) -> bool:
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("missing_turn_id")
        with self._lock:
            previous = self._decisions.get(turn_id)
            if previous is not None:
                return previous
            accepted = self._used < self._limit
            self._decisions[turn_id] = accepted
            if accepted:
                self._used += 1
            return accepted

    reserve = consume
