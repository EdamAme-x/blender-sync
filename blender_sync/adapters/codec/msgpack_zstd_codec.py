from __future__ import annotations

from ...domain.entities import Packet
from ...domain.errors import CodecError
from ...domain.ports import ICodec

_RAW = 0x00
_ZSTD = 0x01


class MsgpackZstdCodec(ICodec):
    def __init__(self, compression_min_bytes: int = 256, level: int = 1) -> None:
        self._min = compression_min_bytes
        self._level = level
        self._msgpack = None
        self._zstd_compressor = None
        self._zstd_decompressor = None

    def _ensure_msgpack(self):
        if self._msgpack is None:
            import msgpack
            self._msgpack = msgpack
        return self._msgpack

    def _ensure_zstd(self):
        if self._zstd_compressor is None:
            import zstandard
            self._zstd_compressor = zstandard.ZstdCompressor(level=self._level)
            self._zstd_decompressor = zstandard.ZstdDecompressor()
        return self._zstd_compressor, self._zstd_decompressor

    def encode(self, packet: Packet) -> bytes:
        msgpack = self._ensure_msgpack()
        try:
            raw = msgpack.packb(packet.to_wire_dict(), use_bin_type=True)
        except Exception as exc:
            raise CodecError(f"msgpack pack failed: {exc}") from exc

        if len(raw) < self._min:
            return bytes([_RAW]) + raw

        compressor, _ = self._ensure_zstd()
        try:
            compressed = compressor.compress(raw)
        except Exception as exc:
            raise CodecError(f"zstd compress failed: {exc}") from exc
        return bytes([_ZSTD]) + compressed

    def decode(self, data: bytes) -> Packet:
        if not data:
            raise CodecError("empty payload")
        header = data[0]
        body = data[1:]
        if header == _RAW:
            payload = body
        elif header == _ZSTD:
            _, decompressor = self._ensure_zstd()
            try:
                payload = decompressor.decompress(body)
            except Exception as exc:
                raise CodecError(f"zstd decompress failed: {exc}") from exc
        else:
            raise CodecError(f"unknown codec header byte: {header}")

        msgpack = self._ensure_msgpack()
        try:
            obj = msgpack.unpackb(payload, raw=False)
        except Exception as exc:
            raise CodecError(f"msgpack unpack failed: {exc}") from exc

        if not isinstance(obj, dict):
            raise CodecError(f"expected dict packet, got {type(obj).__name__}")
        return Packet.from_wire_dict(obj)
