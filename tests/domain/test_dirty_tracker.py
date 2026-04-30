from blender_sync.domain.policies.dirty_tracker import DirtyTracker


def test_flush_returns_snapshot_and_clears():
    t = DirtyTracker()
    t.mark_transform("Cube")
    t.mark_material("Mat.001")
    t.mark_render()
    snap = t.flush()
    assert "Cube" in snap.objects_transform
    assert "Mat.001" in snap.materials
    assert snap.render is True

    second = t.flush()
    assert second.is_empty()


def test_modifier_pair_set():
    t = DirtyTracker()
    t.mark_modifier("Cube", "Subsurf")
    snap = t.flush()
    assert ("Cube", "Subsurf") in snap.modifiers
