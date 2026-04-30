import pytest

from blender_sync.adapters.codec.token_codec import Base58TokenCodec
from blender_sync.domain.errors import TokenParseError


def test_short_token_roundtrip():
    c = Base58TokenCodec()
    t = c.encode_short("ROOM123", "AUTHX")
    assert c.is_short(t)
    room, hmac = c.decode_short(t)
    assert room == "ROOM123" and hmac == "AUTHX"


def test_short_token_no_hmac():
    c = Base58TokenCodec()
    t = c.encode_short("ROOM123", "")
    room, hmac = c.decode_short(t)
    assert room == "ROOM123" and hmac == ""


def test_manual_token_roundtrip():
    c = Base58TokenCodec()
    sdp = "v=0\no=- 1 1 IN IP4 0.0.0.0\ns=-\nt=0 0\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\n"
    t = c.encode_manual(sdp)
    assert not c.is_short(t)
    assert c.decode_manual(t) == sdp


def test_invalid_token():
    c = Base58TokenCodec()
    with pytest.raises(TokenParseError):
        c.decode_short("not-a-token")
    with pytest.raises(TokenParseError):
        c.decode_manual("nope")
