"""Repo-context helpers for workspace repo inference."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


def normalize_git_remote(remote_url: str | None) -> str:
    """Normalize a git remote into a stable host/path key."""
    if not remote_url:
        return ""

    remote = remote_url.strip()
    if not remote:
        return ""

    if "://" in remote:
        parsed = urlparse(remote)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
    elif "@" in remote and ":" in remote:
        _, remainder = remote.split("@", 1)
        host, path = remainder.split(":", 1)
        host = host.lower()
    else:
        parts = remote.split("/", 1)
        if len(parts) == 2:
            host, path = parts[0], "/" + parts[1]
        else:
            return remote.lower().removesuffix(".git").strip("/")
        host = host.lower()

    path = re.sub(r"/+", "/", path).strip("/").lower()
    if path.endswith(".git"):
        path = path[:-4]
    return f"{host}/{path}".strip("/")


def derive_repo_display_name(
    canonical_remote: str,
    local_path: str | None = None,
) -> str:
    """Derive a display name for a repo from remote or local path."""
    if canonical_remote:
        return canonical_remote.rsplit("/", 1)[-1]
    if local_path:
        return Path(local_path).name
    return "repo"
