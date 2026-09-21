"""Walk a checkout and produce one record per file.

Every file in the tree yields a record, included or not. Nothing is dropped
silently — `included=False` rows carry the reason and feed the coverage numbers
in the measurement report.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from reposcope.ingest import language as lang
from reposcope.ingest.filters import ExclusionReason, check_content, check_path

HEAD_BYTES = 8192


@dataclass(frozen=True)
class WalkedFile:
    rel_path: str
    abs_path: Path
    size_bytes: int
    language: str | None
    included: bool
    exclusion_reason: ExclusionReason | None
    content_hash: str | None
    loc: int | None


def _hash_and_count(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    lines = 0
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            digest.update(chunk)
            lines += chunk.count(b"\n")
    return digest.hexdigest(), lines


def walk(root: Path, *, max_file_bytes: int = 1_000_000) -> Iterator[WalkedFile]:
    root = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(root).as_posix()

        # Prune vendored and hidden directories in place so we never descend.
        dirnames[:] = [
            d
            for d in dirnames
            if check_path(f"{rel_dir}/{d}/sentinel" if rel_dir != "." else f"{d}/sentinel").included
        ]
        dirnames.sort()

        for filename in sorted(filenames):
            abs_path = current / filename
            rel_path = abs_path.relative_to(root).as_posix()

            # Symlinks are never followed: a repo can point one outside the root.
            if abs_path.is_symlink() or not abs_path.is_file():
                continue

            path_decision = check_path(rel_path)
            if not path_decision.included:
                yield WalkedFile(
                    rel_path=rel_path,
                    abs_path=abs_path,
                    size_bytes=abs_path.stat().st_size,
                    language=None,
                    included=False,
                    exclusion_reason=path_decision.reason,
                    content_hash=None,
                    loc=None,
                )
                continue

            size = abs_path.stat().st_size
            with abs_path.open("rb") as handle:
                head = handle.read(HEAD_BYTES)

            detected = lang.detect(rel_path, head)
            content_decision = check_content(head, size, max_file_bytes)

            if not content_decision.included:
                yield WalkedFile(
                    rel_path=rel_path,
                    abs_path=abs_path,
                    size_bytes=size,
                    language=detected,
                    included=False,
                    exclusion_reason=content_decision.reason,
                    content_hash=None,
                    loc=None,
                )
                continue

            content_hash, loc = _hash_and_count(abs_path)
            yield WalkedFile(
                rel_path=rel_path,
                abs_path=abs_path,
                size_bytes=size,
                language=detected,
                included=True,
                exclusion_reason=None,
                content_hash=content_hash,
                loc=loc + 1 if size and not head.endswith(b"\n") else loc,
            )


def summarize(files: list[WalkedFile]) -> dict:
    """Coverage stats for the run record and the published report."""
    included = [f for f in files if f.included]
    by_reason: dict[str, int] = {}
    for f in files:
        if f.exclusion_reason:
            by_reason[f.exclusion_reason.value] = by_reason.get(f.exclusion_reason.value, 0) + 1

    by_language: dict[str, int] = {}
    for f in included:
        key = f.language or "unknown"
        by_language[key] = by_language.get(key, 0) + 1

    return {
        "files_total": len(files),
        "files_included": len(included),
        "files_parseable": sum(1 for f in included if lang.is_parseable(f.language)),
        "loc_included": sum(f.loc or 0 for f in included),
        "excluded_by_reason": by_reason,
        "included_by_language": by_language,
    }
