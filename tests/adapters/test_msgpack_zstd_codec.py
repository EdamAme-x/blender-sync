import pytest

from blender_sync.domain.entities import CategoryKind, Packet


pytest.importorskip("msgpack")
pytest.importorskip("zstandard")


def _import_codec():
    from blender_sync.adapters.codec.msgpack_zstd_codec import MsgpackZstdCodec
    return MsgpackZstdCodec


def test_small_packet_uses_raw_header():
    Codec = _import_codec()
    codec = Codec(compression_min_bytes=1024)
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="me",
        category=CategoryKind.TRANSFORM,
        ops=({"n": "Cube", "loc": [1, 2, 3]},),
    )
    data = codec.encode(pkt)
    assert data[0] == 0x00
    back = codec.decode(data)
    assert back == pkt


def test_large_packet_uses_zstd_header():
    Codec = _import_codec()
    codec = Codec(compression_min_bytes=64)
    big_ops = tuple({"n": f"Cube_{i}", "loc": [float(i)] * 3} for i in range(200))
    pkt = Packet(
        version=1, seq=42, ts=99.5, author="alice",
        category=CategoryKind.MATERIAL, ops=big_ops,
    )
    data = codec.encode(pkt)
    assert data[0] == 0x01
    back = codec.decode(data)
    assert back == pkt


def test_decode_rejects_unknown_header():
    Codec = _import_codec()
    codec = Codec()
    with pytest.raises(Exception):
        codec.decode(bytes([0x99]) + b"garbage")


def test_decode_rejects_empty():
    Codec = _import_codec()
    codec = Codec()
    with pytest.raises(Exception):
        codec.decode(b"")
