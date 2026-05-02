# Known Issues — blender-sync

This file tracks edge cases that we are aware of but have intentionally
deferred to post-β. None of these are data-loss bugs; they manifest
as missed updates in specific multi-peer / multi-scene scenarios.

If you hit one of these, the workaround in every case is the **Force
Push** button in the Sync panel — it broadcasts the full local scene
state to peers using the recovery primitive, which bypasses LWW and
realigns the chain.

## Open

### VSE: timeline updates lost when scenes are renamed across peers
**Severity**: low (multi-scene users only)
**Discovered**: codex review round 16

If peer A renames `Scene` → `Edit01` while peer B keeps `Scene`, A's
subsequent VSE strip ops carry `scene: "Edit01"`, which B can't
resolve. Pre-fix the receiver fell back to `bpy.context.scene` and
applied to the wrong timeline (data destruction). Post-fix the
receiver skips the op safely, but the two timelines diverge.

**Workaround**: keep scene names aligned across peers, or use Force
Push after a rename.

**Fix path**: requires a Scene-rename sync category that propagates
the new name *before* a VSE op for that scene reaches peers.

### Particle / Sound: stale state after first-only undo edge cases
**Severity**: low
Particle systems and Sound datablocks rely on the same `_last_seen_count`
dedupe pattern as material_slots and constraints, but their handlers
predate that pattern. A theoretical "remote sends N items → local
clears them all → no clear-op emitted" path mirrors the P2-29 case
that was fixed for material_slots/constraints.

**Workaround**: Force Push.

**Fix path**: backport the `_last_seen_count` apply-side update from
`material_slots.py` / `constraints.py`.

### Mesh on remote rename of object whose mesh datablock has a
different name
**Severity**: very low (Blender power-user case)
The undo handler now walks `bpy.data.objects` for type=='MESH' to
mark the object name (P2-15), so post-undo broadcasts work. Normal
depsgraph updates also work via depsgraph_update_post hooks. The
remaining edge case is "remote A's object renamed independently of
its mesh datablock" — unlikely in practice.

## Closed in current branch

See git log on `fix/codex-p1-blockers` for the full chain. Headlines:

- 12 reviewed P1 chain-protocol bugs (wedge, force recovery,
  stale resend, etc.) — all fixed.
- Undo / Redo sync added end-to-end (UNDO-1).
- 30+ category-specific bugs across the 32-category sync surface.

## Process

After β use surfaces the next batch of bugs, expect another round
of codex review. The chain protocol itself is stable; future
findings will most likely be in:

- Real-bpy quirks (collection iteration semantics, depsgraph
  ordering, undo-step granularity)
- Performance under sustained 60 Hz transform load
- WebRTC / NAT traversal failures (TURN required)
- Wheel compatibility across Blender 5 builds on each OS
