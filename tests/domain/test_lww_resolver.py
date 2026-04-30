from blender_sync.domain.policies.lww_resolver import LWWResolver


def test_first_packet_accepted():
    r = LWWResolver()
    assert r.should_apply("transform:Cube", "alice", 1, 100.0) is True


def test_older_seq_rejected():
    r = LWWResolver()
    r.should_apply("transform:Cube", "alice", 5, 100.0)
    assert r.should_apply("transform:Cube", "alice", 4, 99.0) is False


def test_newer_ts_wins():
    r = LWWResolver()
    r.should_apply("transform:Cube", "alice", 5, 100.0)
    assert r.should_apply("transform:Cube", "bob", 1, 200.0) is True


def test_tie_breaks_by_author():
    r = LWWResolver()
    r.should_apply("k", "alice", 1, 100.0)
    assert r.should_apply("k", "bob", 1, 100.0) is True
    assert r.should_apply("k", "alice", 1, 100.0) is False
