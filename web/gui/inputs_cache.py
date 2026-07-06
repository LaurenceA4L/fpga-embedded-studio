# sopc2dts - Devicetree generation for Altera systems
#
# Python port Copyright (C) 2026 Laurence <laurence@anodes4life.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
Local working-copy cache for GUI inputs.

Every ``Load`` action in the GUI (sopcinfo/.qsys, board file, HPS/kernel DTS,
its cpp include dirs) may point at files that live in unrelated external
trees (an example-design build output, an OS build tree, ...). Rather than
parse those live paths directly, we copy them into ``data/`` at the repo top
level and parse from there — that copy is what a :class:`TrackedInput`
tracks, and what the GUI's periodic status poll compares against the live
source to flag drift. Nothing here auto-refreshes the cache; only
:func:`refresh` (invoked from the GUI's explicit "Refresh" button) does.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class TrackedInputError(Exception):
    """Raised when a source path can't be copied into the cache."""


@dataclass
class TrackedInput:
    kind: str          # "sopcinfo" | "boardinfo" | "hps" | "hps_include"
    slot: str           # unique cache subdir name under data/
    label: str          # display name (basename of source)
    source: Path        # original path, outside data/
    cache_path: Path    # the copy actually parsed by the app
    digest: str         # tree digest snapshot taken at copy time
    checked_at: datetime
    status: str         # "in_sync" | "changed" | "missing"


def tree_digest(path: Path) -> str:
    """
    Cheap, stat-only digest of a file or directory tree: sha256 over sorted
    ``(relpath, size, mtime_ns)`` tuples. No file contents are read, so this
    stays fast even over large trees (kernel dt-bindings, dts directories).
    A bare ``touch`` will conservatively read as "changed" — acceptable,
    since the user decides whether to refresh, nothing happens automatically.
    """
    h = hashlib.sha256()
    if path.is_file():
        st = path.stat()
        h.update(f"{path.name}:{st.st_size}:{st.st_mtime_ns}".encode())
        return h.hexdigest()
    if not path.is_dir():
        return "missing"
    entries = []
    for p in path.rglob("*"):
        if p.is_file():
            st = p.stat()
            entries.append((str(p.relative_to(path)), st.st_size, st.st_mtime_ns))
    for relpath, size, mtime_ns in sorted(entries):
        h.update(f"{relpath}:{size}:{mtime_ns}\n".encode())
    return h.hexdigest()


def _sibling_dir_files(source: Path) -> list[Path]:
    """Regular files directly alongside ``source`` (not recursive) — this is
    exactly the ``-I <parent-dir>`` search path ``dts_merge.parser.run_cpp``
    gives cpp for same-directory ``#include "sibling.dtsi"`` chains."""
    return [p for p in source.parent.iterdir() if p.is_file()]


def copy_into_cache(source: Path, cache_root: Path, slot: str, *, with_siblings: bool) -> Path:
    """
    Wipe and recreate ``cache_root/slot`` from ``source``.

    - ``source`` is a directory (an cpp ``-I`` include dir) -> recursive copy.
    - ``source`` is a file and ``with_siblings`` (HPS DTS, whose sibling
      ``.dtsi`` files resolve relative to its own directory) -> copy every
      regular file next to it, flattened into the slot.
    - ``source`` is a standalone file (sopcinfo/.qsys, boardinfo xml) -> copy
      just that file.

    Returns the path to the cached counterpart of ``source`` itself.
    """
    if not source.exists():
        raise TrackedInputError(f"Source not found: {source}")

    dest_dir = cache_root / slot
    if dest_dir.exists():
        shutil.rmtree(dest_dir)

    if source.is_dir():
        shutil.copytree(source, dest_dir)
        return dest_dir

    dest_dir.mkdir(parents=True)
    if with_siblings:
        for f in _sibling_dir_files(source):
            shutil.copy2(f, dest_dir / f.name)
        return dest_dir / source.name

    shutil.copy2(source, dest_dir / source.name)
    return dest_dir / source.name


def register(
    kind: str,
    slot: str,
    source: Path,
    cache_root: Path,
    *,
    with_siblings: bool = False,
) -> TrackedInput:
    """Copy ``source`` into the cache and return a fresh, in-sync entry."""
    cache_path = copy_into_cache(source, cache_root, slot, with_siblings=with_siblings)
    return TrackedInput(
        kind=kind,
        slot=slot,
        label=source.name,
        source=source,
        cache_path=cache_path,
        digest=tree_digest(source),
        checked_at=datetime.now(),
        status="in_sync",
    )


def refresh(entry: TrackedInput, cache_root: Path, *, with_siblings: bool = False) -> TrackedInput:
    """Re-copy ``entry.source`` into its existing slot; new digest snapshot."""
    return register(entry.kind, entry.slot, entry.source, cache_root, with_siblings=with_siblings)


def check(entry: TrackedInput) -> TrackedInput:
    """Recompute the source digest and compare to the snapshot taken at the
    last copy/refresh. Never touches the cache."""
    if not entry.source.exists():
        status = "missing"
    else:
        status = "in_sync" if tree_digest(entry.source) == entry.digest else "changed"
    return TrackedInput(
        kind=entry.kind,
        slot=entry.slot,
        label=entry.label,
        source=entry.source,
        cache_path=entry.cache_path,
        digest=entry.digest,
        checked_at=datetime.now(),
        status=status,
    )
