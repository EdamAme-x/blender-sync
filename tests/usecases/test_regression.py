"""Regression tests for issues identified by code review."""
import pytest

from blender_sync.adapters.codec.token_codec import (
    MAX_DECOMPRESSED_BYTES,
    Base58TokenCodec,
)
from blender_sync.domain.entities import (
    CategoryKind,
    Packet,
)
from blender_sync.domain.errors import TokenParseError
from blender_sync.domain.policies.lww_resolver import LWWResolver
from blender_sync.usecases.disconnect import DisconnectUseCase


def test_shared_providers_list_reflects_swap():
    """Foundation of _runtime._swap_nostr_provider: a swap on a shared list
    is visible to anyone holding a reference to that same list."""
    a = object(); b = object(); c = object()
    shared: list = [a, b]
    held = shared
    for i, p in enumerate(shared):
        if p is a:
            shared[i] = c
            break
    assert held[0] is c
    assert held[1] is b
    assert shared is held


def test_disconnect_has_blocking_variant():
    assert hasattr(DisconnectUseCase, "execute_blocking")


def test_manual_token_oversize_rejected():
    c = Base58TokenCodec()
    big = "bsync_m1_" + "A" * 60_000
    with pytest.raises(TokenParseError) as exc:
        c.decode_manual(big)
    assert "exceeds size limit" in str(exc.value)


def test_manual_token_zip_bomb_protection():
    import base64
    import zlib
    huge = b"A" * (MAX_DECOMPRESSED_BYTES * 2)
    compressed = zlib.compress(huge, level=9)
    token = "bsync_m1_" + base64.b85encode(compressed).decode("ascii")
    c = Base58TokenCodec()
    with pytest.raises(TokenParseError):
        c.decode_manual(token)


def test_nostr_kinds_are_replaceable_range():
    from blender_sync.adapters.signaling import nostr_provider
    assert 30000 <= nostr_provider.NOSTR_KIND_OFFER < 40000
    assert 30000 <= nostr_provider.NOSTR_KIND_ANSWER < 40000
    assert nostr_provider.NOSTR_KIND_OFFER != nostr_provider.NOSTR_KIND_ANSWER


def test_packet_force_flag_roundtrip():
    p = Packet(
        version=1, seq=1, ts=1.0, author="a",
        category=CategoryKind.TRANSFORM, ops=({"n": "Cube"},),
        force=True,
    )
    d = p.to_wire_dict()
    assert d.get("f") == 1
    back = Packet.from_wire_dict(d)
    assert back.force is True


def test_packet_force_flag_default_false():
    p = Packet(
        version=1, seq=1, ts=1.0, author="a",
        category=CategoryKind.TRANSFORM, ops=(),
    )
    assert p.force is False
    assert "f" not in p.to_wire_dict()
    back = Packet.from_wire_dict(p.to_wire_dict())
    assert back.force is False


def test_session_status_enum_includes_awaiting_states():
    from blender_sync.domain.entities import SessionStatus
    assert SessionStatus.AWAITING_ANSWER.value == "awaiting_answer"
    assert SessionStatus.AWAITING_MANUAL_ANSWER.value == "awaiting_manual_answer"


def test_lww_full_tie_breaks_by_author_name():
    r = LWWResolver()
    assert r.should_apply("k", "alice", 1, 100.0) is True
    assert r.should_apply("k", "bob", 1, 100.0) is True
    assert r.should_apply("k", "alice", 1, 100.0) is False
    assert r.should_apply("k", "carol", 1, 100.0) is True
