"""Auto-detect missing i18n keys.

Walks the presentation/ AST to find every literal string passed to
``pgettext_iface(...)`` or its alias ``_(...)``, plus every
``SessionStatus`` enum value (UI displays them via translation), and
asserts each one has a corresponding entry in the JA translation dict.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from blender_sync.domain.entities import CategoryKind, SessionStatus
from blender_sync.i18n.translations import (
    CTX_DEFAULT,
    CTX_OPERATOR,
    get_translations,
)

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "blender_sync"

UI_FILES = [
    PKG / "presentation" / "panels.py",
    PKG / "presentation" / "operators.py",
    PKG / "presentation" / "preferences.py",
    PKG / "presentation" / "properties.py",
]


def _extract_translated_literals(source: str) -> set[str]:
    tree = ast.parse(source)
    out: set[str] = set()

    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in ("_", "pgettext_iface", "t", "tf"):
                if node.args and isinstance(node.args[0], ast.Constant):
                    value = node.args[0].value
                    if isinstance(value, str):
                        out.add(value)
            self.generic_visit(node)

    V().visit(tree)
    return out


def _extract_bl_labels(source: str) -> set[str]:
    """Operator/Panel `bl_label` only — those are the button text the
    user actually clicks, so they belong in the JA dict.

    `bl_description` (= tooltip) is intentionally NOT required to have
    a JA entry: the rest of Blender keeps tooltips in English by
    default and over-translating them clutters the UI without adding
    meaning for users who already read English technical terms.
    """
    tree = ast.parse(source)
    out: set[str] = set()

    class V(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            for stmt in node.body:
                if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
                    continue
                tgt = stmt.targets[0]
                if not (isinstance(tgt, ast.Name) and tgt.id == "bl_label"):
                    continue
                value = stmt.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    out.add(value.value)
            self.generic_visit(node)

    V().visit(tree)
    return out


def _extract_property_names(source: str) -> set[str]:
    """Pick up `name="..."` keyword args inside *Property(...) calls — these
    are translated automatically by Blender. Also extracts EnumProperty
    `items=[(id, label, desc), ...]` labels and descriptions."""
    tree = ast.parse(source)
    out: set[str] = set()

    PROP_FUNCS = {
        "BoolProperty", "FloatProperty", "IntProperty", "StringProperty",
        "EnumProperty", "PointerProperty", "CollectionProperty", "FloatVectorProperty",
    }

    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in PROP_FUNCS:
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        if isinstance(kw.value.value, str):
                            out.add(kw.value.value)
                    if kw.arg == "items" and isinstance(kw.value, ast.List):
                        for entry in kw.value.elts:
                            if not isinstance(entry, ast.Tuple):
                                continue
                            for sub in entry.elts:
                                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                                    out.add(sub.value)
            self.generic_visit(node)

    V().visit(tree)
    return out


@pytest.fixture(scope="module")
def ja_dict() -> dict[tuple[str, str], str]:
    return get_translations()["ja_JP"]


def _key_present(d, msgid: str) -> bool:
    return (CTX_DEFAULT, msgid) in d or (CTX_OPERATOR, msgid) in d


def test_translated_literals_have_japanese_entries(ja_dict):
    missing: list[tuple[str, str]] = []
    for ui in UI_FILES:
        source = ui.read_text(encoding="utf-8")
        for msgid in _extract_translated_literals(source):
            if not _key_present(ja_dict, msgid):
                missing.append((ui.name, msgid))
    assert not missing, "Missing JA translations:\n" + "\n".join(
        f"  {f}: {repr(m)}" for f, m in missing
    )


def test_session_status_values_have_japanese_entries(ja_dict):
    missing = [s.value for s in SessionStatus
               if not _key_present(ja_dict, s.value)]
    assert not missing, f"SessionStatus values missing JA: {missing}"


def test_operator_bl_labels_have_japanese_entries(ja_dict):
    """bl_label = button text the user clicks. Must have a JA entry.
    bl_description = tooltip; intentionally exempt — Blender shows
    tooltips in English by default and translating them adds noise
    for technical users."""
    operators_path = PKG / "presentation" / "operators.py"
    source = operators_path.read_text(encoding="utf-8")
    labels = _extract_bl_labels(source)
    missing = [m for m in labels if not _key_present(ja_dict, m)]
    assert not missing, (
        "Operator bl_label missing JA:\n"
        + "\n".join(f"  {repr(m)}" for m in missing)
    )


def test_translation_dict_has_no_orphan_keys(ja_dict):
    referenced: set[str] = set()
    for ui in UI_FILES:
        src = ui.read_text(encoding="utf-8")
        referenced.update(_extract_translated_literals(src))
        referenced.update(_extract_bl_labels(src))
        referenced.update(_extract_property_names(src))
    referenced.update(s.value for s in SessionStatus)
    referenced.update(c.value for c in CategoryKind)
    referenced.update({"Status: %s", "Error: %s"})

    orphans = [
        (ctx, msgid) for (ctx, msgid) in ja_dict if msgid not in referenced
    ]
    assert not orphans, (
        f"Unused translation entries (likely outdated):\n"
        + "\n".join(f"  ({c!r}, {m!r})" for c, m in orphans)
    )


def test_extract_helper_basic():
    sample = '''
from bpy.app.translations import pgettext_iface as _
def f():
    a = _("hello")
    b = pgettext_iface("world")
    c = "not translated"
    return a, b, c
'''
    found = _extract_translated_literals(sample)
    assert "hello" in found
    assert "world" in found
    assert "not translated" not in found
