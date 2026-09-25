"""Content provenance checks; manifests are not signatures or live authorization."""

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import digest


def git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git is required to verify releases")
    # Internal argument arrays only; never run a shell.
    return subprocess.run(  # noqa: S603
        [executable, *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def build_manifest(root: Path, *, policy_digest: str, capability_digest: str) -> dict[str, Any]:
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Release requires a clean repository")
    files: dict[str, str] = {}
    for name in git(root, "ls-files", "-z").split("\0"):
        if not name:
            continue
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Release files must be regular files")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "version": 1,
        "source_commit": git(root, "rev-parse", "HEAD"),
        "files": files,
        "tree_digest": digest(files),
        "policy_digest": policy_digest,
        "capability_digest": capability_digest,
        "live_certified": False,
    }


def verify_manifest(root: Path, manifest: dict[str, Any], *, policy_digest: str) -> None:
    if manifest.get("policy_digest") != policy_digest:
        raise ValueError("Release policy mismatch")
    current = build_manifest(
        root,
        policy_digest=policy_digest,
        capability_digest=manifest.get("capability_digest", "none"),
    )
    if current != manifest:
        raise ValueError("Release content or provenance mismatch")
