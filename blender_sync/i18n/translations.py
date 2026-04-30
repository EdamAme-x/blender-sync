"""i18n translation dictionary for Blender Sync.

Format follows bpy.app.translations.register():
    {locale: {(context, msgid): translation, ...}, ...}

Blender automatically picks the active locale based on
Preferences > Interface > Translation. We provide:
    - ja_JP : Japanese
    - en_US is the source/key locale (no entry needed)

Module also provides a fallback ``t()`` for non-bpy contexts (logging, error
messages, statuses) that detects the system locale via ``locale``.
"""
from __future__ import annotations

import locale as _locale
from typing import Any

# Translation contexts. "Operator" is Blender's standard context for operator
# names; "*" is the default for any text.
CTX_OPERATOR = "Operator"
CTX_DEFAULT = "*"


_JA: dict[tuple[str, str], str] = {
    # ---- Panels / sections ----
    (CTX_DEFAULT, "Blender Sync"): "Blender Sync",
    (CTX_DEFAULT, "Sync Filters"): "同期フィルター",
    (CTX_DEFAULT, "Status: %s"): "状態: %s",
    (CTX_DEFAULT, "Error: %s"): "エラー: %s",
    (CTX_DEFAULT, "Share Token:"): "共有トークン:",
    (CTX_DEFAULT, "Join Existing:"): "セッションに参加:",
    (CTX_DEFAULT, "Manual SDP fallback active"): "手動 SDP フォールバックが有効です",
    (CTX_DEFAULT, "Nostr relay was unreachable."):
        "Nostr リレーに接続できませんでした。",
    (CTX_DEFAULT, "1. Copy the token above and send it to the peer."):
        "1. 上のトークンをコピーして相手に送ってください。",
    (CTX_DEFAULT, "2. Paste the peer's reply token below."):
        "2. 相手から受け取った返信トークンを下に貼り付けてください。",
    (CTX_DEFAULT, "Force Sync (bypass LWW):"): "強制同期 (LWW を無視):",
    (CTX_DEFAULT, "Honors Sync Filters below."): "下の同期フィルターに従います。",
    (CTX_DEFAULT, "Mesh:"): "メッシュ:",

    # ---- Operators (bl_label / button text) ----
    (CTX_OPERATOR, "Start Sharing"): "共有を開始",
    (CTX_OPERATOR, "Join Session"): "セッションに参加",
    (CTX_OPERATOR, "Disconnect"): "切断",
    (CTX_OPERATOR, "Copy Token"): "トークンをコピー",
    (CTX_OPERATOR, "Submit Manual Answer"): "手動アンサーを送信",
    (CTX_OPERATOR, "Force Push (My Scene -> All)"): "強制プッシュ (自分のシーン → 全員)",
    (CTX_OPERATOR, "Force Pull (Receive from peers)"): "強制プル (相手から受信)",
    (CTX_DEFAULT, "Push"): "プッシュ",
    (CTX_DEFAULT, "Pull"): "プル",

    # ---- Operator descriptions (tooltips) ----
    (CTX_DEFAULT, "Generate a share token and wait for a peer to join"):
        "共有トークンを生成し、相手の参加を待ちます",
    (CTX_DEFAULT, "Join an existing session using a token"):
        "トークンを使って既存のセッションに参加します",
    (CTX_DEFAULT, "Disconnect from the current sync session"):
        "現在の同期セッションを切断します",
    (CTX_DEFAULT, "Copy the current share token to clipboard"):
        "現在の共有トークンをクリップボードにコピーします",
    (CTX_DEFAULT, "Paste an answer token from the joining peer"):
        "参加側の相手から受け取ったアンサートークンを貼り付けます",
    (
        CTX_DEFAULT,
        "Overwrite all peers with MY current scene state. "
        "Bypasses last-write-wins. Honors Sync Filters.",
    ): "自分の現在のシーンで全相手を上書きします。LWW を無視。同期フィルターに従います。",
    (
        CTX_DEFAULT,
        "Ask peers to send their state and overwrite MY scene. "
        "Bypasses last-write-wins. Honors Sync Filters.",
    ): "相手にシーン状態の送信を要求し、自分のシーンを上書きします。LWW を無視。同期フィルターに従います。",

    # ---- Sync Filter labels ----
    (CTX_DEFAULT, "Transform"): "トランスフォーム",
    (CTX_DEFAULT, "Material"): "マテリアル",
    (CTX_DEFAULT, "Modifier"): "モディファイアー",
    (CTX_DEFAULT, "Compositor"): "コンポジター",
    (CTX_DEFAULT, "Render"): "レンダー",
    (CTX_DEFAULT, "Scene/World"): "シーン/ワールド",
    (CTX_DEFAULT, "Visibility"): "可視性",
    (CTX_DEFAULT, "Camera"): "カメラ",
    (CTX_DEFAULT, "Light"): "ライト",
    (CTX_DEFAULT, "Collection"): "コレクション",
    (CTX_DEFAULT, "Animation"): "アニメーション",
    (CTX_DEFAULT, "Image"): "画像",
    (CTX_DEFAULT, "Armature"): "アーマチュア",
    (CTX_DEFAULT, "Pose"): "ポーズ",
    (CTX_DEFAULT, "Shape Keys"): "シェイプキー",
    (CTX_DEFAULT, "Constraints"): "コンストレイント",
    (CTX_DEFAULT, "Grease Pencil"): "グリースペンシル",
    (CTX_DEFAULT, "Curve"): "カーブ",
    (CTX_DEFAULT, "Particle"): "パーティクル",
    (CTX_DEFAULT, "Node Group"): "ノードグループ",
    (CTX_DEFAULT, "Texture"): "テクスチャ",
    (CTX_DEFAULT, "Lattice"): "ラティス",
    (CTX_DEFAULT, "Metaball"): "メタボール",
    (CTX_DEFAULT, "Volume"): "ボリューム",
    (CTX_DEFAULT, "Point Cloud"): "ポイントクラウド",
    (CTX_DEFAULT, "Latency (ms)"): "レイテンシ (ms)",
    (CTX_DEFAULT, "Bandwidth (KB/s)"): "帯域 (KB/s)",
    (CTX_DEFAULT, "Peer Count"): "ピア数",
    (CTX_DEFAULT, "Connection Metrics"): "接続メトリクス",
    (CTX_DEFAULT, "Peers: %d"): "ピア: %d",
    (CTX_DEFAULT, "Latency: %.1f ms"): "レイテンシ: %.1f ms",
    (CTX_DEFAULT, "Bandwidth: %.1f KB/s"): "帯域: %.1f KB/s",
    (CTX_DEFAULT, "Mesh: On Exit Edit"): "メッシュ: 編集モード離脱時",
    (CTX_DEFAULT, "Mesh: During Edit"): "メッシュ: 編集中",
    (CTX_DEFAULT, "Edit-mode Hz"): "編集中の Hz",
    (CTX_DEFAULT, "Conflict Resolution:"): "衝突解決:",
    (CTX_DEFAULT, "Conflict Policy"): "衝突ポリシー",
    (CTX_DEFAULT, "Conflict Window (s)"): "衝突判定期間 (秒)",
    (CTX_DEFAULT, "Peer Priority (comma)"): "ピア優先順位 (カンマ区切り)",
    (CTX_DEFAULT, "Auto (LWW)"): "自動 (LWW)",
    (CTX_DEFAULT, "Local Wins"): "ローカル優先",
    (CTX_DEFAULT, "Remote Wins"): "リモート優先",
    (CTX_DEFAULT, "Peer Priority"): "ピア優先",
    (CTX_DEFAULT, "Manual"): "手動",

    # ---- Preferences ----
    (CTX_DEFAULT, "ICE Servers"): "ICE サーバー",
    (CTX_DEFAULT, "Signaling"): "シグナリング",
    (CTX_DEFAULT, "STUN URL"): "STUN URL",
    (CTX_DEFAULT, "TURN URL"): "TURN URL",
    (CTX_DEFAULT, "TURN Username"): "TURN ユーザー名",
    (CTX_DEFAULT, "TURN Password"): "TURN パスワード",
    (CTX_DEFAULT, "Nostr Relays (comma-separated)"): "Nostr リレー (カンマ区切り)",

    # ---- Statuses (used by SyncSessionState.status) ----
    (CTX_DEFAULT, "idle"): "待機中",
    (CTX_DEFAULT, "sharing"): "共有中",
    (CTX_DEFAULT, "awaiting_answer"): "応答待ち",
    (CTX_DEFAULT, "awaiting_manual_answer"): "手動アンサー待ち",
    (CTX_DEFAULT, "connecting"): "接続中",
    (CTX_DEFAULT, "live"): "接続済み",
    (CTX_DEFAULT, "error"): "エラー",

    # ---- Reports / messages ----
    (CTX_DEFAULT, "Token copied to clipboard"): "トークンをクリップボードにコピーしました",
    (CTX_DEFAULT, "No token to copy"): "コピーするトークンがありません",
    (CTX_DEFAULT, "Empty answer token"): "アンサートークンが空です",
    (CTX_DEFAULT, "Token is empty"): "トークンが空です",
    (CTX_DEFAULT, "Sync runtime is not initialized"): "Sync ランタイムが初期化されていません",
    (CTX_DEFAULT, "Force pushed local scene to peers"):
        "ローカルシーンを相手にプッシュしました",
    (CTX_DEFAULT, "Force pull request sent to peers"):
        "強制プル要求を相手に送信しました",
}


TRANSLATIONS: dict[str, dict[tuple[str, str], str]] = {
    "ja_JP": _JA,
}


def get_translations() -> dict[str, dict[tuple[str, str], str]]:
    return TRANSLATIONS


# === Fallback translator for non-bpy contexts ===
# Detects system locale once at import and returns translations from the
# same dictionary. Used by logger output, headless tests, etc.

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
    """Translate a string using the system locale (no bpy required).

    For UI strings that go through Blender, prefer
    ``bpy.app.translations.pgettext_iface`` so that the user-selected
    Blender locale takes precedence.
    """
    if _is_japanese(_SYSTEM_LANG):
        ja = _JA.get((context, msgid))
        if ja:
            return ja
    return msgid


def tf(msgid: str, *args: Any, context: str = CTX_DEFAULT) -> str:
    """t() + printf-style formatting in one call."""
    template = t(msgid, context=context)
    if args:
        try:
            return template % args
        except Exception:
            return template
    return template
