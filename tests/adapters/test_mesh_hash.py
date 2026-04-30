from blender_sync.adapters.scene.categories.mesh import _mesh_hash


def test_mesh_hash_stable():
    verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    faces = [[0, 1, 2]]
    assert _mesh_hash(verts, faces) == _mesh_hash(verts, faces)


def test_mesh_hash_changes_when_verts_change():
    a = _mesh_hash([[0, 0, 0]], [[0]])
    b = _mesh_hash([[0, 0, 1]], [[0]])
    assert a != b


def test_mesh_hash_changes_when_faces_change():
    a = _mesh_hash([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])
    b = _mesh_hash([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[2, 1, 0]])
    assert a != b
