"""Build the Blender Sync extension zip.

Steps:
  1. Download required wheels for every (platform × Python) combination
     into blender_sync/wheels/. Default Python set is 3.11 (Blender 5.0)
     plus 3.12 / 3.13 (Blender 5.1+) so a single zip installs cleanly on
     any modern Blender — Blender picks the wheel that matches its own
     bundled Python at install time.
  2. Patch blender_manifest.toml with the resolved wheel list.
  3. Zip blender_sync/ into dist/blender_sync-<version>.zip.

Usage:
    python scripts/build_extension.py [--skip-download]
                                       [--platforms windows-x64,linux-x64]
                                       [--python-versions 3.11,3.12,3.13]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "blender_sync"
WHEELS_DIR = PKG_DIR / "wheels"
MANIFEST_PATH = PKG_DIR / "blender_manifest.toml"
DIST_DIR = ROOT / "dist"

DEFAULT_PLATFORMS = [
    "windows-x64",
    "windows-arm64",
    "macos-arm64",
    "macos-x64",
    "linux-x64",
]

PIP_PLATFORM_TAGS = {
    "windows-x64": ["win_amd64"],
    "windows-arm64": ["win_arm64"],
    "macos-arm64": ["macosx_11_0_arm64"],
    "macos-x64": ["macosx_10_9_x86_64", "macosx_11_0_x86_64"],
    "linux-x64": ["manylinux2014_x86_64", "manylinux_2_17_x86_64"],
}

REQUIREMENTS = [
    # Upstream aiortc keeps pace with new cryptography releases; the
    # `aiortc-datachannel-only` fork is stuck on aiortc 1.3.2 and breaks
    # against cryptography>=44. We accept the heavier dep tree (PyAV) for
    # robustness — DataChannel is the only feature we use at runtime.
    ("aiortc", ">=1.14,<2"),
    ("websockets", ">=12,<14"),
    ("msgpack", ">=1.0,<2"),
    ("zstandard", ">=0.22,<1"),
    ("base58", ">=2.1,<3"),
    ("coincurve", ">=20,<22"),
]

# Default Python versions to bundle. Blender picks at install time
# whichever cp* wheel matches its embedded interpreter.
#   - 3.11: Blender 5.0
#   - 3.12: defensive future-proofing (no Blender release ships this
#     today, but the wheels are tiny and harmless to include)
#   - 3.13: Blender 5.1+
DEFAULT_PYTHON_VERSIONS = ["3.11", "3.12", "3.13"]


def download_wheels(platforms: list[str], python_versions: list[str]) -> None:
    WHEELS_DIR.mkdir(parents=True, exist_ok=True)
    for name, spec in REQUIREMENTS:
        package_arg = f"{name}{spec}" if spec else name
        for platform in platforms:
            tags = PIP_PLATFORM_TAGS[platform]
            for py_version in python_versions:
                cmd = [
                    sys.executable, "-m", "pip", "download",
                    "--only-binary=:all:",
                    "--python-version", py_version,
                    "--implementation", "cp",
                    "--abi", f"cp{py_version.replace('.', '')}",
                    "-d", str(WHEELS_DIR),
                    package_arg,
                ]
                for tag in tags:
                    cmd.extend(["--platform", tag])
                print(f"[download] {package_arg} ({platform}, py{py_version})")
                try:
                    subprocess.run(cmd, check=True, capture_output=True)
                except subprocess.CalledProcessError as exc:
                    stderr = (
                        exc.stderr.decode("utf-8", errors="ignore")
                        if exc.stderr else ""
                    )
                    print(
                        f"  WARN: {name} for {platform} py{py_version} "
                        f"failed:\n{stderr.strip()[:400]}",
                        file=sys.stderr,
                    )


def expand_abi3_wheels(python_versions: list[str]) -> None:
    """Some packages (cryptography, pylibsrtp, ...) ship abi3 wheels:
    a single binary that is forward-compatible across cpython 3.x.
    `pip download --python-version 3.13 --abi cp313` happily resolves
    these and returns the same `cp311-abi3` (or `cp39-abi3`) file for
    every requested target.

    Blender's extension installer, however, looks at the wheel file
    NAME and rejects a `cp311-abi3` wheel when the embedded Python
    is 3.13 — so packages-via-abi3 installs cleanly only on the
    Python version that happens to match the lower bound encoded in
    the filename.

    Fix: detect those wheels and create renamed *copies* for every
    python version we're bundling. The actual binary works on each
    of them because abi3 is forward-compatible by definition; we're
    only cooperating with Blender's filename-based picker.
    """
    if not WHEELS_DIR.exists():
        return
    abi3_re = re.compile(
        r"^(?P<dist>.+?)-(?P<ver>[^-]+)-cp(?P<lower>\d+)-abi3-(?P<rest>.+\.whl)$"
    )
    for f in list(WHEELS_DIR.glob("*-abi3-*.whl")):
        m = abi3_re.match(f.name)
        if m is None:
            continue
        dist = m.group("dist")
        ver = m.group("ver")
        lower = int(m.group("lower"))   # e.g. 39 or 311
        rest = m.group("rest")
        # `lower` follows pip wheel-tag conventions: '39' = 3.9, '311'
        # = 3.11. Treat anything < 100 as a single-digit minor.
        lower_minor = lower % 10 if lower < 100 else lower % 100
        for py_version in python_versions:
            target_minor = int(py_version.split(".")[1])
            if target_minor < lower_minor and lower < 100:
                # abi3 wheel encodes "cpython >= 3.<lower_minor>"; if
                # the requested target is older than that, skip.
                continue
            # Build the renamed target.
            tag = f"cp3{target_minor}"
            new_name = f"{dist}-{ver}-{tag}-{tag}-{rest}"
            target = WHEELS_DIR / new_name
            if target.exists():
                continue
            # Copy bytes (hardlink would be nicer but cross-fs unsafe).
            target.write_bytes(f.read_bytes())
            print(f"[abi3] {f.name} -> {new_name}")
        # Remove the original abi3-tagged file so Blender's installer
        # only sees the cleanly-tagged copies.
        try:
            f.unlink()
        except OSError:
            pass


def collect_wheel_paths() -> list[str]:
    if not WHEELS_DIR.exists():
        return []
    out: list[str] = []
    for f in sorted(WHEELS_DIR.glob("*.whl")):
        out.append(f"./wheels/{f.name}")
    return out


_WHEELS_MARKER_BEGIN = "# === wheels (auto-generated by build_extension.py) ==="
_WHEELS_MARKER_END = "# === end wheels ==="


def patch_platforms(text: str, platforms: list[str]) -> str:
    """Rewrite the top-level `platforms = [...]` array to match the build set."""
    block_lines = ["platforms = ["]
    for plat in platforms:
        block_lines.append(f'  "{plat}",')
    block_lines.append("]")
    block = "\n".join(block_lines) + "\n"

    pattern = re.compile(
        r"^platforms\s*=\s*\[[^\]]*\]\s*$",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub(block.rstrip() + "\n", text, count=1)
    return text


def patch_manifest(wheels: list[str], platforms: list[str] | None = None) -> None:
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    if platforms:
        text = patch_platforms(text, platforms)

    # Strip any previously-generated wheels block (between markers).
    if _WHEELS_MARKER_BEGIN in text and _WHEELS_MARKER_END in text:
        before, _, rest = text.partition(_WHEELS_MARKER_BEGIN)
        _, _, after = rest.partition(_WHEELS_MARKER_END)
        text = before.rstrip() + "\n\n" + after.lstrip()

    # Strip any stray top-level `wheels = [...]` array (multi-line).
    lines = text.splitlines(keepends=True)
    cleaned: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.lstrip()
        if not skipping:
            if stripped.startswith("wheels") and "=" in stripped and "[" in stripped:
                skipping = True
                if "]" in stripped[stripped.find("="):]:
                    skipping = False
                continue
            cleaned.append(line)
        else:
            if "]" in line:
                skipping = False
            continue
    text = "".join(cleaned)

    block_lines = [_WHEELS_MARKER_BEGIN, "wheels = ["]
    for w in wheels:
        block_lines.append(f'  "{w}",')
    block_lines.append("]")
    block_lines.append(_WHEELS_MARKER_END)
    block = "\n".join(block_lines) + "\n"

    # `wheels` must be a top-level key, so insert BEFORE the first [section]
    # table to avoid TOML parsing it as a member of that section.
    insertion_pattern = re.compile(r"^\s*\[[^\]]+\]\s*$", re.MULTILINE)
    match = insertion_pattern.search(text)
    if match:
        new_text = text[: match.start()].rstrip() + "\n\n" + block + "\n" + text[match.start():]
    else:
        new_text = text.rstrip() + "\n\n" + block

    MANIFEST_PATH.write_text(new_text, encoding="utf-8")
    print(f"[manifest] wrote {len(wheels)} wheel entries")


def read_version() -> str:
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return m.group(1) if m else "0.0.0"


def build_zip(platforms: list[str]) -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    version = read_version()
    if len(platforms) == 1:
        suffix = f"-{platforms[0]}"
    elif len(platforms) == len(DEFAULT_PLATFORMS):
        suffix = "-all"
    else:
        suffix = "-" + "+".join(platforms)
    out = DIST_DIR / f"blender_sync-{version}{suffix}.zip"
    if out.exists():
        out.unlink()

    excludes = ("__pycache__", ".pytest_cache", ".mypy_cache")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in PKG_DIR.rglob("*"):
            if any(part in excludes for part in path.parts):
                continue
            if path.is_dir():
                continue
            arcname = path.relative_to(PKG_DIR.parent)
            zf.write(path, arcname)
    print(f"[zip] wrote {out} ({out.stat().st_size // 1024} KiB)")
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--platforms", default=",".join(DEFAULT_PLATFORMS))
    p.add_argument(
        "--python-versions",
        default=",".join(DEFAULT_PYTHON_VERSIONS),
        help="Comma-separated CPython versions to bundle wheels for. "
             "Blender picks the matching cp* wheel at install time.",
    )
    p.add_argument("--no-zip", action="store_true")
    args = p.parse_args()

    platforms = [s.strip() for s in args.platforms.split(",") if s.strip()]
    python_versions = [
        s.strip() for s in args.python_versions.split(",") if s.strip()
    ]
    if not python_versions:
        print("ERROR: --python-versions is empty", file=sys.stderr)
        return 1

    if not args.skip_download:
        download_wheels(platforms, python_versions)

    expand_abi3_wheels(python_versions)

    wheels = collect_wheel_paths()
    if not wheels:
        print("WARNING: no wheels in blender_sync/wheels/", file=sys.stderr)
    patch_manifest(wheels, platforms)

    if not args.no_zip:
        build_zip(platforms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
