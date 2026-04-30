from blender_sync.domain.entities import CategoryKind, ChannelKind, Packet


def test_packet_roundtrip():
    p = Packet(
        version=1, seq=10, ts=123.45, author="peer_a",
        category=CategoryKind.TRANSFORM,
        ops=({"n": "Cube", "loc": [1, 2, 3]},),
    )
    d = p.to_wire_dict()
    assert d["v"] == 1 and d["seq"] == 10 and d["ch"] == "transform"
    back = Packet.from_wire_dict(d)
    assert back == p
    assert back.channel is ChannelKind.FAST


def test_reliable_channel_for_material():
    p = Packet(
        version=1, seq=1, ts=1.0, author="x",
        category=CategoryKind.MATERIAL, ops=(),
    )
    assert p.channel is ChannelKind.RELIABLE
