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


class LibOpusDecoder:
    def __init__(self, sample_rate: int, channels: int) -> None:
        self._lib = _load_libopus()
        self._lib.opus_decoder_create.argtypes = [
            ctypes.c_int32,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self._lib.opus_decoder_create.restype = ctypes.c_void_p
        self._lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
        self._lib.opus_decoder_destroy.restype = None
        self._lib.opus_decode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._lib.opus_decode.restype = ctypes.c_int

        error = ctypes.c_int(0)
        self._decoder = self._lib.opus_decoder_create(
            sample_rate,
            channels,
            ctypes.byref(error),
        )
        if not self._decoder or error.value != 0:
            raise OpusError(f"opus decoder create failed: {error.value}")
        self._channels = channels

    def decode_packet(self, packet: bytes, *, frame_size: int) -> bytes:
        if not packet:
            return b""
        packet_buf = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
        sample_buf = (ctypes.c_int16 * (frame_size * self._channels))()
        decoded_samples = self._lib.opus_decode(
            self._decoder,
            packet_buf,
            len(packet),
            sample_buf,
            frame_size,
            0,
        )
        if decoded_samples < 0:
            raise OpusError(f"opus_decode_failed:{decoded_samples}")
        decoded_byte_count = decoded_samples * self._channels * ctypes.sizeof(ctypes.c_int16)
        return ctypes.string_at(sample_buf, decoded_byte_count)

    def close(self) -> None:
        if getattr(self, "_decoder", None):
            self._lib.opus_decoder_destroy(self._decoder)
            self._decoder = None

    def __enter__(self) -> "LibOpusDecoder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def pack_framed_v1_packets(payloads: Iterable[bytes]) -> Iterator[bytes]:
    sequence = 0
    for payload in payloads:
        if not payload:
            continue
        yield sequence.to_bytes(4, "big") + len(payload).to_bytes(4, "big") + payload
        sequence += 1


def parse_framed_v1_packets(
    body: bytes,
    *,
    expected_sequence: int = 0,
) -> list[tuple[int, bytes]]:
    packets: list[tuple[int, bytes]] = []
    offset = 0
    next_sequence = expected_sequence
    while offset < len(body):
        if len(body) - offset < 8:
            raise OpusError("framed_packet_truncated")
        sequence = int.from_bytes(body[offset : offset + 4], "big")
        payload_len = int.from_bytes(body[offset + 4 : offset + 8], "big")
        offset += 8
        if sequence != next_sequence:
            raise OpusError("framed_sequence_gap")
        if len(body) - offset < payload_len:
            raise OpusError("framed_packet_truncated")
        packets.append((sequence, body[offset : offset + payload_len]))
        offset += payload_len
        next_sequence += 1
    return packets


def decode_framed_opus_to_pcm(
    chunks: Iterable[bytes],
    *,
    sample_rate: int,
    channels: int,
    frame_duration_ms: int,
) -> tuple[bytes, dict[str, int | float | None]]:
    body = b"".join(chunks)
    outer_packets = parse_framed_v1_packets(body)
    frame_size = sample_rate * frame_duration_ms // 1000
    if frame_size <= 0:
        raise OpusError("invalid_opus_frame_size")

    opus_bytes = 0
    decoded = bytearray()
    with LibOpusDecoder(sample_rate=sample_rate, channels=channels) as decoder:
        for _sequence, payload in outer_packets:
            if len(payload) < 2:
                raise OpusError("opus_packet_truncated")
            packet_len = int.from_bytes(payload[:2], "big")
            packet = payload[2:]
            if len(packet) != packet_len:
                raise OpusError("opus_packet_truncated")
            opus_bytes += len(packet)
            decoded.extend(decoder.decode_packet(packet, frame_size=frame_size))

    pcm_bytes = len(decoded)
    compression_ratio = round(pcm_bytes / opus_bytes, 3) if opus_bytes > 0 else None
    byte_rate = sample_rate * channels * 2
    return bytes(decoded), {
        "uplink_opus_bytes": opus_bytes,
        "uplink_pcm_bytes": pcm_bytes,
        "uplink_compression_ratio": compression_ratio,
        "uplink_frame_count": len(outer_packets),
        "reconstructed_audio_ms": int(round((pcm_bytes / byte_rate) * 1000)) if byte_rate else 0,
    }


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
