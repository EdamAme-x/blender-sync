"""MockBlender: a pytest-friendly stand-in for the bpy runtime.

The real bug behind "token doesn't show up" / "panel goes blank" /
"Push button is dead" hid in the seam between Blender's main thread,
the asyncio loop, and our PropertyGroup. Unit tests with isolated
fakes never exercised that whole chain together, so seam bugs
shipped.

This module installs a fake `bpy` module that mimics enough of:
  - bpy.context.scene.blender_sync_state  (PropertyGroup attrs)
  - bpy.context.window_manager.windows / screens / areas / regions
  - bpy.app.timers.register / unregister / is_registered
  - region.tag_redraw()

so we can drive entire flows (Start Sharing → token visible on the
panel, Disconnect → state reset, etc.) inside a single test.

Usage:

    def test_something(monkeypatch):
        bl = MockBlender.install(monkeypatch)
        bl.tick(0.5)               # advance fake timers by 0.5s
        assert bl.state.token == "bsync_..."
        assert bl.tag_redraw_count >= 1
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class MockSyncState:
    """Mirrors blender_sync.presentation.properties.SyncSessionState."""
    status: str = "idle"
    token: str = ""
    join_token: str = ""
    error: str = ""
    peer_id: str = ""
    manual_answer_input: str = ""

    pc_state: str = ""
    reliable_open: bool = False
    fast_open: bool = False

    # Filter toggles (default True like the real PropertyGroup).
    sync_transform: bool = True
    sync_material: bool = True
    sync_modifier: bool = True
    sync_compositor: bool = True
    sync_render: bool = True
    sync_scene_world: bool = True
    sync_visibility: bool = True
    sync_camera: bool = True
    sync_light: bool = True
    sync_collection: bool = True
    sync_animation: bool = True
    sync_image: bool = True
    sync_armature: bool = True
    sync_pose: bool = True
    sync_shape_keys: bool = True
    sync_constraints: bool = True
    sync_grease_pencil: bool = True
    sync_curve: bool = True
    sync_particle: bool = True
    sync_node_group: bool = True
    sync_texture: bool = True
    sync_lattice: bool = True
    sync_metaball: bool = True
    sync_volume: bool = True
    sync_point_cloud: bool = True
    sync_vse_strip: bool = True
    sync_sound: bool = True
    sync_view3d: bool = True

    # Metrics (live-state UI fields).
    latency_ms: float = 0.0
    bandwidth_kbps: float = 0.0
    peer_count: int = 0

    # Mesh / conflict policy (panel exposes them).
    mesh_on_edit_exit: bool = True
    mesh_during_edit: bool = False
    mesh_edit_hz: float = 5.0
    conflict_policy: str = "auto"
    conflict_window: float = 1.0
    conflict_peer_priority: str = ""


@dataclass
class _Region:
    type: str
    redraw_calls: int = 0

    def tag_redraw(self) -> None:
        self.redraw_calls += 1


@dataclass
class _Area:
    type: str
    regions: list[_Region] = field(default_factory=list)


@dataclass
class _Screen:
    areas: list[_Area] = field(default_factory=list)


@dataclass
class _Window:
    screen: _Screen | None = None


@dataclass
class _WindowManager:
    windows: list[_Window] = field(default_factory=list)


class _FakeTimers:
    """Mimics bpy.app.timers. Supports register/unregister/is_registered
    and a simulated clock advanced by `MockBlender.tick`."""
    def __init__(self) -> None:
        # Each entry: (callback, next_fire_at, persistent).
        self._entries: list[tuple[Callable, float, bool]] = []
        self._now = 0.0

    def register(self, callback, first_interval=0.0, persistent=False) -> None:
        self._entries.append((callback, self._now + first_interval, persistent))

    def is_registered(self, callback) -> bool:
        return any(cb is callback for cb, _t, _p in self._entries)

    def unregister(self, callback) -> None:
        self._entries = [
            (cb, t, p) for (cb, t, p) in self._entries if cb is not callback
        ]

    def advance(self, dt: float) -> int:
        """Move the simulated clock forward and fire any due timers.
        Returns how many fires happened (useful for assertions)."""
        target = self._now + dt
        fires = 0
        # Loop because callbacks reschedule themselves.
        while True:
            due = [
                (cb, t, p) for (cb, t, p) in self._entries if t <= target
            ]
            if not due:
                break
            for cb, t, p in due:
                # Remove this scheduled instance, then run.
                self._entries.remove((cb, t, p))
                self._now = t
                ret = None
                try:
                    ret = cb()
                except Exception:
                    pass
                fires += 1
                if isinstance(ret, (int, float)) and ret is not None:
                    # Reschedule.
                    self._entries.append((cb, self._now + float(ret), p))
        self._now = target
        return fires


class MockBlender:
    """The handle the test holds onto. After install(), the test can
    inspect state, tick timers, and assert UI side effects."""

    def __init__(self) -> None:
        self.state = MockSyncState()
        self._sidebar_region = _Region(type="UI")
        self._area = _Area(
            type="VIEW_3D",
            regions=[self._sidebar_region, _Region(type="WINDOW")],
        )
        self._screen = _Screen(areas=[self._area])
        self._window = _Window(screen=self._screen)
        self._wm = _WindowManager(windows=[self._window])
        self.timers = _FakeTimers()

    @property
    def tag_redraw_count(self) -> int:
        return self._sidebar_region.redraw_calls

    @classmethod
    def install(cls, monkeypatch) -> "MockBlender":
        """Install a fake `bpy` module backed by a fresh MockBlender.
        Returns the handle so the test can inspect state."""
        bl = cls()
        fake_scene = types.SimpleNamespace(blender_sync_state=bl.state)
        fake_context = types.SimpleNamespace(
            scene=fake_scene,
            window_manager=bl._wm,
        )
        fake_app = types.SimpleNamespace(timers=bl.timers)
        fake_bpy = types.ModuleType("bpy")
        fake_bpy.context = fake_context
        fake_bpy.app = fake_app
        monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
        return bl

    def tick(self, seconds: float) -> int:
        """Advance the fake timer clock. Returns fired-callback count."""
        return self.timers.advance(seconds)
