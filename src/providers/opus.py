from __future__ import annotations

import ctypes
import ctypes.util
from collections.abc import Iterable, Iterator


class OpusError(RuntimeError):
    pass


OPUS_APPLICATION_AUDIO = 2049
OPUS_SET_BITRATE_REQUEST = 4002
_MAX_PACKET_BYTES = 1500


def _load_libopus() -> ctypes.CDLL:
    lib_name = ctypes.util.find_library("opus") or "libopus.so.0"
    try:
        return ctypes.CDLL(lib_name)
    except OSError as exc:  # pragma: no cover - environment-dependent
        raise OpusError("libopus unavailable") from exc


def opus_available() -> bool:
    try:
        _load_libopus()
        return True
    except OpusError:
        return False


class LibOpusEncoder:
    def __init__(self, sample_rate: int, channels: int, bitrate: int) -> None:
        self._lib = _load_libopus()
        self._lib.opus_encoder_create.argtypes = [
            ctypes.c_int32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self._lib.opus_encoder_create.restype = ctypes.c_void_p
        self._lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
        self._lib.opus_encoder_destroy.restype = None
        self._lib.opus_encoder_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self._lib.opus_encoder_ctl.restype = ctypes.c_int
        self._lib.opus_encode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
        ]
        self._lib.opus_encode.restype = ctypes.c_int32

        error = ctypes.c_int(0)
        self._encoder = self._lib.opus_encoder_create(
            sample_rate,
            channels,
            OPUS_APPLICATION_AUDIO,
            ctypes.byref(error),
        )
        if not self._encoder or error.value != 0:
            raise OpusError(f"opus encoder create failed: {error.value}")
        self._sample_rate = sample_rate
        self._channels = channels
        ctl_ret = self._lib.opus_encoder_ctl(self._encoder, OPUS_SET_BITRATE_REQUEST, bitrate)
        if ctl_ret != 0:
            self.close()
            raise OpusError(f"opus encoder bitrate configure failed: {ctl_ret}")

    def encode_frame(self, pcm_frame: bytes) -> bytes:
        if not pcm_frame:
            return b""
        if len(pcm_frame) % 2 != 0:
            raise OpusError("pcm frame must be 16-bit aligned")
        sample_count = len(pcm_frame) // 2
        frame_size = sample_count // self._channels
        sample_array = (ctypes.c_int16 * sample_count).from_buffer_copy(pcm_frame)
        packet_buf = (ctypes.c_ubyte * _MAX_PACKET_BYTES)()
        packet_len = self._lib.opus_encode(
            self._encoder,
            sample_array,
            frame_size,
            packet_buf,
            _MAX_PACKET_BYTES,
        )
        if packet_len <= 0:
            raise OpusError(f"opus encode failed: {packet_len}")
        return bytes(packet_buf[:packet_len])

    def close(self) -> None:
        if getattr(self, "_encoder", None):
            self._lib.opus_encoder_destroy(self._encoder)
            self._encoder = None

    def __enter__(self) -> "LibOpusEncoder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def encode_pcm_stream_to_framed_opus(
    pcm_chunks: Iterable[bytes],
    *,
    sample_rate: int,
    channels: int,
    frame_duration_ms: int,
    bitrate: int,
) -> Iterator[bytes]:
    frame_samples = sample_rate * frame_duration_ms // 1000
    frame_bytes = frame_samples * channels * 2
    if frame_bytes <= 0:
        raise OpusError("invalid opus frame size")

    buffered = bytearray()
    with LibOpusEncoder(sample_rate=sample_rate, channels=channels, bitrate=bitrate) as encoder:
        for chunk in pcm_chunks:
            if not chunk:
                continue
            buffered.extend(chunk)
            while len(buffered) >= frame_bytes:
                frame = bytes(buffered[:frame_bytes])
                del buffered[:frame_bytes]
                packet = encoder.encode_frame(frame)
                yield len(packet).to_bytes(2, "big") + packet
        if buffered:
            padded = bytes(buffered) + b"\x00" * (frame_bytes - len(buffered))
            packet = encoder.encode_frame(padded)
            yield len(packet).to_bytes(2, "big") + packet
