"""Shared serialization for Blender NodeTree (used by Material + Compositor).

A node tree is a graph of nodes connected by links. We serialize:
  - per node: type, name, location, label, primitive props, default input
    socket values
  - links: from/to node names + socket names

The serialization is intentionally lossy for property types we cannot
represent in msgpack (object references, image datablocks). Image / Object
references are out of scope here — they require their own datablock-level
sync.
"""
from __future__ import annotations

from typing import Any

from . import _datablock_ref

_PRIMITIVE = (int, float, bool, str)

_NODE_PROP_BLACKLIST = {
    "rna_type", "name", "label", "type", "inputs", "outputs", "internal_links",
    "parent", "select", "show_options", "show_preview", "show_texture",
    "use_custom_color", "color", "dimensions", "width", "height",
    "width_hidden", "bl_description", "bl_height_default", "bl_height_max",
    "bl_height_min", "bl_icon", "bl_idname", "bl_label", "bl_rna",
    "bl_static_type", "bl_width_default", "bl_width_max", "bl_width_min",
    "hide", "mute", "image_user", "color_mapping", "texture_mapping",
}

# Node properties that hold pointer types (Image / NodeGroup / Object / etc).
# Other attributes are walked as primitives or sequences.
_REFERENCE_PROPS = frozenset({
    "image", "node_tree", "object", "scene", "clip", "mask",
})


def _is_serializable(value: Any) -> bool:
    if isinstance(value, _PRIMITIVE):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_serializable(v) for v in value)
    return False


def _serialize_value(value: Any) -> Any:
    if hasattr(value, "__iter__") and not isinstance(value, str):
        try:
            return [float(v) if isinstance(v, (int, float)) else v for v in value]
        except Exception:
            return None
    if isinstance(value, _PRIMITIVE):
        return value
    return None


def serialize_node(node) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": node.name,
        "type": node.bl_idname,
        "loc": [float(node.location[0]), float(node.location[1])],
    }
    try:
        out["label"] = str(node.label or "")
    except Exception:
        pass

    props: dict[str, Any] = {}
    for attr in dir(node):
        if attr.startswith("_") or attr in _NODE_PROP_BLACKLIST:
            continue
        try:
            val = getattr(node, attr)
        except Exception:
            continue
        if callable(val):
            continue
        if isinstance(val, _PRIMITIVE):
            props[attr] = val
        elif attr in _REFERENCE_PROPS:
            ref = _datablock_ref.try_ref(val)
            if ref is not None:
                props[attr] = ref
        elif _is_serializable(val):
            serialized = _serialize_value(val)
            if serialized is not None:
                props[attr] = serialized
    out["props"] = props

    inputs: list[dict[str, Any]] = []
    for sock in node.inputs:
        entry: dict[str, Any] = {"name": sock.name, "type": sock.bl_idname}
        if not sock.is_linked and hasattr(sock, "default_value"):
            serialized = _serialize_value(sock.default_value)
            if serialized is not None:
                entry["default"] = serialized
        inputs.append(entry)
    out["inputs"] = inputs
    return out


def serialize_link(link) -> dict[str, Any]:
    return {
        "fn": link.from_node.name,
        "fs": link.from_socket.name,
        "tn": link.to_node.name,
        "ts": link.to_socket.name,
    }


def serialize_tree_interface(tree) -> list[dict[str, Any]]:
    """Serialize node_tree.interface (Blender 4.0+).

    The interface is the input/output socket definition of a NodeGroup
    (Shader / Geometry Nodes). Without this, group nodes on the receiver
    have empty I/O sockets even if the inner tree is reproduced.
    Returns [] on older Blender versions that don't expose .interface.
    """
    iface = getattr(tree, "interface", None)
    if iface is None:
        return []
    items = getattr(iface, "items_tree", None)
    if items is None:
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        entry: dict[str, Any] = {
            "name": getattr(it, "name", ""),
            "item_type": getattr(it, "item_type", "SOCKET"),
        }
        if entry["item_type"] == "SOCKET":
            entry["socket_type"] = getattr(it, "socket_type", "NodeSocketFloat")
            entry["in_out"] = getattr(it, "in_out", "INPUT")
            try:
                desc = getattr(it, "description", "")
                if desc:
                    entry["description"] = str(desc)
            except Exception:
                pass
            for k in ("default_value", "min_value", "max_value",
                      "subtype", "default_input"):
                if not hasattr(it, k):
                    continue
                try:
                    val = getattr(it, k)
                    if isinstance(val, _PRIMITIVE):
                        entry[k] = val
                    elif hasattr(val, "__iter__") and not isinstance(val, str):
                        try:
                            entry[k] = [float(v) for v in val]
                        except Exception:
                            pass
                except Exception:
                    pass
        out.append(entry)
    return out


def apply_tree_interface(tree, interface_data: list[dict]) -> None:
    iface = getattr(tree, "interface", None)
    if iface is None or not interface_data:
        return
    try:
        for it in list(iface.items_tree):
            iface.remove(it)
    except Exception:
        return
    for entry in interface_data:
        if entry.get("item_type") != "SOCKET":
            continue
        try:
            sock = iface.new_socket(
                name=entry.get("name", ""),
                in_out=entry.get("in_out", "INPUT"),
                socket_type=entry.get("socket_type", "NodeSocketFloat"),
            )
        except Exception:
            continue
        for k in ("default_value", "min_value", "max_value",
                  "subtype", "default_input", "description"):
            if k not in entry or not hasattr(sock, k):
                continue
            v = entry[k]
            try:
                if isinstance(v, list):
                    setattr(sock, k, tuple(v))
                else:
                    setattr(sock, k, v)
            except Exception:
                pass


def apply_nodetree(tree, nodes_op: list, links_op: list) -> None:
    tree.nodes.clear()
    created: dict[str, Any] = {}
    for n in nodes_op:
        try:
            node = tree.nodes.new(type=n["type"])
        except Exception:
            continue
        try:
            node.name = n.get("name", node.name)
        except Exception:
            pass
        loc = n.get("loc")
        if loc and len(loc) == 2:
            try:
                node.location = (float(loc[0]), float(loc[1]))
            except Exception:
                pass
        label = n.get("label")
        if label is not None:
            try:
                node.label = str(label)
            except Exception:
                pass

        for k, v in (n.get("props") or {}).items():
            if not hasattr(node, k):
                continue
            if _datablock_ref.is_ref(v):
                resolved = _datablock_ref.resolve_ref(v)
                if resolved is None:
                    continue
                try:
                    setattr(node, k, resolved)
                except Exception:
                    pass
                continue
            try:
                setattr(node, k, v)
            except Exception:
                continue

        for sock_op in n.get("inputs", []):
            sock = node.inputs.get(sock_op.get("name", ""))
            if sock is None or "default" not in sock_op:
                continue
            if not hasattr(sock, "default_value"):
                continue
            try:
                val = sock_op["default"]
                if isinstance(val, list):
                    sock.default_value = tuple(val)
                else:
                    sock.default_value = val
            except Exception:
                pass

        created[n["name"]] = node

    for link in links_op:
        fn = created.get(link.get("fn"))
        tn = created.get(link.get("tn"))
        if fn is None or tn is None:
            continue
        fs = fn.outputs.get(link.get("fs", ""))
        ts = tn.inputs.get(link.get("ts", ""))
        if fs is None or ts is None:
            continue
        try:
            tree.links.new(fs, ts)
        except Exception:
            pass
