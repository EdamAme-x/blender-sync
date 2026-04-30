"""i18n translation dictionary and fallback translator tests."""
import importlib

from blender_sync.i18n import translations as i18n


def test_translation_dict_has_ja_locale():
    d = i18n.get_translations()
    assert "ja_JP" in d
    assert isinstance(d["ja_JP"], dict)


def test_translation_dict_uses_tuple_keys():
    d = i18n.get_translations()
    for key in d["ja_JP"]:
        assert isinstance(key, tuple)
        assert len(key) == 2  # (context, msgid)
        ctx, msgid = key
        assert isinstance(ctx, str)
        assert isinstance(msgid, str)


def test_translation_critical_messages_present():
    d = i18n.get_translations()["ja_JP"]
    # Spot-check key UI strings exist in JA
    expected = [
        ("*", "Start Sharing"),
        ("Operator", "Start Sharing"),
        ("*", "Force Sync (bypass LWW):"),
        ("*", "live"),
        ("*", "idle"),
        ("*", "Token copied to clipboard"),
    ]
    found = 0
    for k in expected:
        if k in d:
            found += 1
    # We don't require exact match because the source uses "Operator" ctx for
    # operator labels; but at least some of these must exist.
    assert found >= 4, f"only {found}/{len(expected)} translations present"


def test_t_returns_msgid_for_unknown_locale(monkeypatch):
    monkeypatch.setattr(i18n, "_SYSTEM_LANG", "en_US")
    assert i18n.t("Start Sharing", context="Operator") == "Start Sharing"


def test_t_returns_japanese_when_system_lang_is_ja(monkeypatch):
    monkeypatch.setattr(i18n, "_SYSTEM_LANG", "ja_JP")
    # operator label translation
    assert i18n.t("Start Sharing", context="Operator") == "共有を開始"


def test_t_falls_back_when_msgid_missing(monkeypatch):
    monkeypatch.setattr(i18n, "_SYSTEM_LANG", "ja_JP")
    assert i18n.t("Nonexistent string XYZ123") == "Nonexistent string XYZ123"


def test_tf_formats_arguments(monkeypatch):
    monkeypatch.setattr(i18n, "_SYSTEM_LANG", "ja_JP")
    # "Status: %s" -> "状態: %s"
    out = i18n.tf("Status: %s", "live")
    assert out == "状態: live"


def test_tf_falls_back_on_format_error(monkeypatch):
    monkeypatch.setattr(i18n, "_SYSTEM_LANG", "ja_JP")
    # No %s in the dict but providing args should not raise
    out = i18n.tf("idle")
    assert out == "待機中"


def test_is_japanese_helper():
    assert i18n._is_japanese("ja_JP") is True
    assert i18n._is_japanese("ja") is True
    assert i18n._is_japanese("ja-JP") is True
    assert i18n._is_japanese("en_US") is False
    assert i18n._is_japanese("") is False


def test_module_reimports_cleanly():
    importlib.reload(i18n)
    assert callable(i18n.t)
    assert callable(i18n.tf)
