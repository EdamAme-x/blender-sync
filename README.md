# Blender Sync (harmonic-whisper)

Blender 5.0+ のリアルタイム共同編集拡張機能。WebRTC DataChannel + Nostr シグナリングで P2P 接続し、シーン状態 (transform / material / modifier / mesh / compositor / render / scene / visibility) をリアルタイム同期します。

クリーンアーキテクチャ + 依存性注入で構築されているため、Domain / UseCase は `bpy` 無しで pytest 単体テスト可能です。

---

## 主な機能

| カテゴリ | 内容 |
|---|---|
| Transform | location / rotation / scale を 60Hz で同期 (DataChannel `fast`) |
| Material | ノードツリー全体 (ノード/プロパティ/リンク) |
| Modifier | スタック + 全プロパティ |
| Mesh | Edit mode 離脱時スナップショット / Edit mode 中低頻度 (UI 切替) |
| Compositor | コンポジターノードツリー |
| Render | engine / resolution / samples / fps / Cycles・EEVEE 設定 |
| Scene/World | World 背景色・強度 |
| Visibility | hide_viewport / hide_render / hide_select |
| Initial Snapshot | Join 時にホストが全状態を一括送信 |

接続方式:
- **Nostr public relay** (推奨): 短いトークン (~30 文字) で接続。relay は分散公開ノード 4 個から並行
- **手動 SDP トークン** (フォールバック): relay 全障害時、SDP まるごと圧縮した巨大トークンをコピペ

---

## ビルドとインストール

### 依存
- Python 3.11 (Blender 5 同梱バージョンに合わせる)
- pip で wheel ダウンロード可能な環境

### 拡張機能 zip のビルド

```bash
python scripts/build_extension.py
# 5 platform 分の wheel を blender_sync/wheels/ に取得
# blender_manifest.toml の wheels セクションを自動更新
# dist/blender_sync-<version>.zip を生成
```

特定 platform のみビルドする場合:

```bash
python scripts/build_extension.py --platforms linux-x64,windows-x64
```

wheel を再取得しない場合 (manifest 更新と zip のみ):

```bash
python scripts/build_extension.py --skip-download
```

### Blender へのインストール

1. Blender 5.0+ を起動
2. `Edit > Preferences > Get Extensions > Install from Disk`
3. `dist/blender_sync-0.1.0.zip` を選択
4. View3D の Sidebar (`N` キー) に `Sync` タブが追加される

---

## 使い方

### Start Sharing (ホスト側)

1. Sidebar > Sync > `Start Sharing` を押す
2. 短いトークンが表示される (例: `bsync_v1_7xK2mNpQrStUvWx_aB3dEf`)
3. `Copy` ボタンでクリップボードにコピー
4. 相手にトークンを送る (Slack/メール等)
5. 相手が Join するまで待機

### Join Session (参加側)

1. Sidebar > Sync の `Token:` 欄にトークンを貼り付け
2. `Join Session` ボタンを押す
3. 接続が確立すると `Status: live` になり、ホストのシーン状態が同期される

### Manual SDP フォールバック (relay 全障害時)

Nostr relay が全滅した場合、自動的に Manual SDP モードへフォールバック:

1. ホスト側に巨大トークン (1500 文字程度) が表示される
2. 相手にコピペで渡す → 相手が Join し、巨大 answer トークンを返す
3. ホスト側の `Manual Answer:` 欄に貼り付け → `Submit Manual Answer`

### Sync Filters

`Sync` パネル > `Sync Filters` でカテゴリ別 ON/OFF が可能。Mesh は以下 2 モードを切替可能:

- **On Exit Edit**: Edit mode → Object mode に戻った瞬間にスナップショット送信 (デフォルト ON)
- **During Edit**: Edit mode 中も低頻度 (1-30Hz, デフォルト 5Hz) で送信

---

## 設定 (Preferences)

`Edit > Preferences > Add-ons > Blender Sync > Preferences` から以下を設定可能:

| 項目 | デフォルト | 用途 |
|---|---|---|
| STUN URL | `stun:stun.l.google.com:19302` | NAT 越え |
| TURN URL | (空) | シンメトリック NAT 用。任意設定 |
| TURN Username/Password | (空) | TURN 認証 |
| Nostr Relays | 4 公開 relay (カンマ区切り) | シグナリング |

---

## 開発

### テスト実行

```bash
python -m pytest tests/ -v
```

bpy 不在環境でも 29 テスト全てパスします (Domain / UseCase / Adapter の純Python部分)。

### スタンドアロン統合テスト

Nostr シグナリング単体:

```bash
# ターミナル A
python scripts/test_signaling.py offerer --room MYROOM

# ターミナル B
python scripts/test_signaling.py answerer --room MYROOM
```

WebRTC DataChannel 込み (aiortc 必須):

```bash
pip install aiortc-datachannel-only websockets

# ターミナル A
python scripts/test_datachannel.py offerer --room MYROOM

# ターミナル B
python scripts/test_datachannel.py answerer --room MYROOM
```

### アーキテクチャ

```
blender_sync/
├── domain/        ← 外部依存ゼロ (bpy/aiortc を import しない)
├── usecases/      ← ports のみに依存
├── adapters/      ← ports を実装 (bpy / aiortc / msgpack 等)
├── infrastructure/← asyncio loop, thread bridge, DI container
├── presentation/  ← Operator / Panel / Preferences (薄く)
└── _runtime.py    ← Composition Root (DI 配線)
```

詳細は `/home/edamame/.claude/plans/blender-blender-v5-etc-start-sharing-p2-harmonic-whisper.md` 参照。

---

## ライセンス

MIT
