"""i18n translation dictionary for Blender Sync.

Format follows bpy.app.translations.register():
    {locale: {(context, msgid): translation, ...}, ...}

Philosophy:
- Blender Japanese UI users are already comfortable reading English
  technical terms (Material, Modifier, Compositor, etc.). Over-
  translating to katakana actively makes the UI harder to scan, so
  filter category labels stay in English. Same for tooltips: the
  rest of Blender keeps tooltips in English by default.
- We only translate (a) action verbs (Start Sharing, Disconnect),
  (b) user-facing status text, and (c) instruction strings the user
  reads in flow.
"""
from __future__ import annotations

import locale as _locale
from typing import Any

CTX_OPERATOR = "Operator"
CTX_DEFAULT = "*"


_JA: dict[tuple[str, str], str] = {
    # ---- Section labels users read in flow ----
    (CTX_DEFAULT, "Status: %s"): "状態: %s",
    (CTX_DEFAULT, "Error: %s"): "エラー: %s",
    (CTX_DEFAULT, "Share Token:"): "共有トークン:",
    (CTX_DEFAULT, "Join Existing:"): "参加:",
    (CTX_DEFAULT, "Manual SDP fallback active"): "手動 SDP モード",
    (CTX_DEFAULT, "Nostr relay was unreachable."):
        "Nostr リレーに接続できません。",
    (CTX_DEFAULT, "1. Copy the token above and send it to the peer."):
        "1. 上のトークンを相手に送る",
    (CTX_DEFAULT, "2. Paste the peer's reply token below."):
        "2. 相手の返信トークンを下に貼り付け",

    # ---- Operator buttons ----
    (CTX_OPERATOR, "Start Sharing"): "共有を開始",
    (CTX_OPERATOR, "Join Session"): "参加",
    (CTX_OPERATOR, "Disconnect"): "切断",
    (CTX_OPERATOR, "Copy Token"): "トークンをコピー",
    (CTX_OPERATOR, "Submit Manual Answer"): "アンサーを送信",
    (CTX_OPERATOR, "Force Push (My Scene -> All)"): "強制プッシュ",
    (CTX_OPERATOR, "Force Pull (Receive from peers)"): "強制プル",

    # ---- Statuses ----
    (CTX_DEFAULT, "idle"): "待機中",
    (CTX_DEFAULT, "sharing"): "共有中",
    (CTX_DEFAULT, "awaiting_answer"): "応答待ち",
    (CTX_DEFAULT, "awaiting_manual_answer"): "手動アンサー待ち",
    (CTX_DEFAULT, "connecting"): "接続中",
    (CTX_DEFAULT, "live"): "接続済み",
    (CTX_DEFAULT, "error"): "エラー",

    # ---- Reports / messages ----
    (CTX_DEFAULT, "Token copied to clipboard"): "トークンをコピーしました",
    (CTX_DEFAULT, "No token to copy"): "トークンがありません",
    (CTX_DEFAULT, "Empty answer token"): "アンサートークンが空です",
    (CTX_DEFAULT, "Token is empty"): "トークンが空です",
    (CTX_DEFAULT, "Sync runtime is not initialized"):
        "Sync ランタイムが未初期化です",
    (CTX_DEFAULT, "Force pushed local scene to peers"):
        "強制プッシュしました",
    (CTX_DEFAULT, "Force pull request sent to peers"):
        "強制プル要求を送信しました",
}


TRANSLATIONS: dict[str, dict[tuple[str, str], str]] = {
    "ja_JP": _JA,
}


def get_translations() -> dict[str, dict[tuple[str, str], str]]:
    return TRANSLATIONS


# === Fallback translator for non-bpy contexts ===

def _detect_system_lang() -> str:
    try:
        lang, _enc = _locale.getlocale()
        if not lang:
            try:
                lang = _locale.getdefaultlocale()[0] or ""
            except Exception:
                lang = ""
        return lang or ""
    except Exception:
        return ""


_SYSTEM_LANG = _detect_system_lang()


def _is_japanese(lang: str) -> bool:
    return lang.lower().startswith("ja")


def t(msgid: str, *, context: str = CTX_DEFAULT) -> str:
    """Translate `msgid` using the system locale (no bpy required).

    UI strings that go through Blender should prefer
    ``bpy.app.translations.pgettext_iface`` directly so the user-
    selected Blender locale takes precedence.
    """
    if _is_japanese(_SYSTEM_LANG):
        ja = _JA.get((context, msgid))
        if ja:
            return ja
    return msgid


def tf(msgid: str, *args: Any, context: str = CTX_DEFAULT) -> str:
    """`t()` + printf-style formatting."""
    template = t(msgid, context=context)
    if args:
        try:
            return template % args
        except Exception:
            return template
    return template
