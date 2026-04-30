# Blender Sync

Real-time collaborative editing for Blender 5.0+. P2P over WebRTC.

## Install

Download the zip for your platform from [Releases](https://github.com/EdamAme-x/blender-sync/releases),
then `Edit → Preferences → Get Extensions → Install from Disk`.

## Use

1. Open `Sidebar (N) → Sync` in the 3D View.
2. **Start Sharing** generates a token. Send it to your peer.
3. Peer pastes it into **Token** and clicks **Join**.

## Build from source

```bash
python scripts/build_extension.py --platforms linux-x64
```

## License

MIT
