from blender_sync.domain.policies.echo_filter import EchoFilter


def test_self_packet_rejected():
    f = EchoFilter(self_peer_id="peer_me")
    assert f.should_accept("peer_me") is False


def test_other_packet_accepted():
    f = EchoFilter(self_peer_id="peer_me")
    assert f.should_accept("peer_other") is True
