from __future__ import annotations


def _have_bpy() -> bool:
    try:
        import bpy  # noqa: F401
        return True
    except ImportError:
        return False


_REGISTERED: list = []


def _register_translations():
    import bpy
    from .i18n.translations import get_translations
    bpy.app.translations.register(__name__, get_translations())


def _unregister_translations():
    import bpy
    bpy.app.translations.unregister(__name__)


def register():
    if not _have_bpy():
        return

    from . import _runtime
    from .presentation import operators, panels, preferences, properties

    steps = [
        ("translations", _register_translations, _unregister_translations),
        ("preferences", preferences.register, preferences.unregister),
        ("properties", properties.register, properties.unregister),
        ("operators", operators.register, operators.unregister),
        ("panels", panels.register, panels.unregister),
    ]

    for name, do, undo in steps:
        try:
            do()
            _REGISTERED.append((name, undo))
        except Exception:
            for _, prev_undo in reversed(_REGISTERED):
                try:
                    prev_undo()
                except Exception:
                    pass
            _REGISTERED.clear()
            raise

    try:
        _runtime.init()
        _REGISTERED.append(("runtime", _runtime.shutdown))
    except Exception:
        for _, prev_undo in reversed(_REGISTERED):
            try:
                prev_undo()
            except Exception:
                pass
        _REGISTERED.clear()
        raise


def unregister():
    if not _have_bpy():
        return

    for _, undo in reversed(_REGISTERED):
        try:
            undo()
        except Exception:
            pass
    _REGISTERED.clear()
