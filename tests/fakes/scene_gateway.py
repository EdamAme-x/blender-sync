from typing import Any, Iterable

from blender_sync.domain.entities import CategoryKind


class FakeSceneGateway:
    def __init__(self) -> None:
        self.applying_remote = False
        self.dirty: dict[CategoryKind, list[dict[str, Any]]] = {}
        self.applied: list[tuple[CategoryKind, list[dict[str, Any]]]] = []
        self.snapshot: list[tuple[CategoryKind, list[dict[str, Any]]]] = []
        self.snapshot_initial_flags: list[bool] = []
        self.installed = False

    def is_applying_remote(self) -> bool:
        return self.applying_remote

    def set_applying_remote(self, value: bool) -> None:
        self.applying_remote = value

    def install_change_listeners(self) -> None:
        self.installed = True

    def uninstall_change_listeners(self) -> None:
        self.installed = False

    def collect_dirty_ops(
        self, categories: Iterable[CategoryKind]
    ) -> list[tuple[CategoryKind, list[dict[str, Any]]]]:
        cats = set(categories)
        out = []
        for cat, ops in self.dirty.items():
            if cat in cats and ops:
                out.append((cat, list(ops)))
        self.dirty.clear()
        return out

    def apply_ops(self, category: CategoryKind, ops: list[dict[str, Any]]) -> None:
        self.applied.append((category, list(ops)))

    def build_full_snapshot(
        self, *, initial_snapshot: bool = False,
    ) -> list[tuple[CategoryKind, list[dict[str, Any]]]]:
        self.snapshot_initial_flags.append(initial_snapshot)
        return list(self.snapshot)
