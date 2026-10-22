"""Secure source packager for Liara source uploads.

Liara expects a ``.gz`` archive (``POST /v2/projects/{name}/sources`` with the
``file`` field).  Packaging is a security boundary: secrets, VCS data,
dependency trees and anything outside the workspace must never be uploaded.
"""

from __future__ import annotations

import hashlib
import os
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import PolicyViolation, ValidationError
from app.core.security import assert_within

# Directories that are never packaged, at any depth.
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", ".env.d",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    ".next", ".nuxt", ".turbo", ".parcel-cache", "dist", "build", "coverage",
    ".idea", ".vscode", "data", ".arena", "site-packages",
}

# File names / suffixes that are never packaged.
EXCLUDED_NAMES = {
    ".DS_Store", "Thumbs.db", "id_rsa", "id_ed25519", ".netrc", ".npmrc",
    ".pgpass", ".bash_history", ".zsh_history",
}
EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db", ".pyc"}

# ``.env`` and every ``.env.*`` variant (including .env.local / .env.example).
ENV_PREFIX = ".env"


@dataclass
class PackageResult:
    path: Path
    file_count: int
    size_bytes: int
    sha256: str
    excluded: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "archive": self.path.name,
            "file_count": self.file_count,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "excluded_count": len(self.excluded),
            "excluded_sample": self.excluded[:10],
        }


def is_excluded(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    name = parts[-1] if parts else ""
    if name in EXCLUDED_NAMES:
        return True
    if name == ENV_PREFIX or name.startswith(ENV_PREFIX + "."):
        return True
    if Path(name).suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    return False


def create_source_archive(
    root: Path,
    destination: Path,
    *,
    max_mb: int = 50,
    extra_excludes: set[str] | None = None,
) -> PackageResult:
    """Create a deterministic ``.tar.gz`` of *root* with security exclusions."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValidationError(f"Source root does not exist: {root}")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = max(1, int(max_mb)) * 1024 * 1024
    extra = extra_excludes or set()

    excluded: list[str] = []
    included: list[tuple[Path, str]] = []
    total_bytes = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        # prune excluded directories in-place for efficiency
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in EXCLUDED_DIRS and d not in extra
        )
        for dirname in list(dirnames):
            if (current / dirname).is_symlink():
                excluded.append(str((current / dirname).relative_to(root)))
                dirnames.remove(dirname)
        for filename in sorted(filenames):
            absolute = current / filename
            rel = absolute.relative_to(root).as_posix()
            if is_excluded(rel) or filename in extra or rel in extra:
                excluded.append(rel)
                continue
            if absolute.is_symlink():
                # Only allow symlinks that stay inside the workspace.
                try:
                    assert_within(root, absolute)
                except PolicyViolation:
                    excluded.append(rel)
                    continue
                excluded.append(rel)  # never archive links, keep the archive simple
                continue
            if not absolute.is_file():
                excluded.append(rel)
                continue
            try:
                assert_within(root, absolute)
            except PolicyViolation as exc:
                raise PolicyViolation(
                    "Source packaging aborted: a file escapes the workspace root.",
                    details={"file": rel},
                ) from exc
            size = absolute.stat().st_size
            total_bytes += size
            if total_bytes > max_bytes:
                raise PolicyViolation(
                    f"Source package exceeds the {max_mb} MB limit.",
                    details={"limit_mb": max_mb, "checked_files": len(included) + 1},
                )
            included.append((absolute, rel))

    if destination.exists():
        destination.unlink()

    with tarfile.open(destination, "w:gz") as tar:
        for absolute, rel in included:
            info = tarfile.TarInfo(name=rel)
            stat = absolute.stat()
            info.size = stat.st_size
            info.mtime = int(stat.st_mtime)
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = "liarapilot"
            with absolute.open("rb") as handle:
                tar.addfile(info, handle)

    size_bytes = destination.stat().st_size
    if size_bytes > max_bytes:
        destination.unlink(missing_ok=True)
        raise PolicyViolation(
            f"Compressed source package exceeds the {max_mb} MB limit.",
            details={"limit_mb": max_mb, "size_bytes": size_bytes},
        )

    digest = hashlib.sha256()
    with destination.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)

    return PackageResult(
        path=destination,
        file_count=len(included),
        size_bytes=size_bytes,
        sha256=digest.hexdigest(),
        excluded=excluded,
    )


def archive_members(archive_path: Path) -> list[str]:
    with tarfile.open(archive_path, "r:gz") as tar:
        return [m.name for m in tar.getmembers()]


def assert_archive_has_no_secrets(archive_path: Path) -> None:
    """Fail closed if a forbidden path made it into the archive."""
    for name in archive_members(archive_path):
        if is_excluded(name):
            raise PolicyViolation(
                "Refusing to upload an archive containing excluded paths.",
                details={"member": name},
            )
        if name.startswith("/") or ".." in Path(name).parts:
            raise PolicyViolation(
                "Refusing to upload an archive containing unsafe paths.",
                details={"member": name},
            )
