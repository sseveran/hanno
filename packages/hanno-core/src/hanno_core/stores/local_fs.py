"""Local filesystem artifact store with content-addressed storage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class LocalFsArtifactStore:
    """Content-addressable local filesystem artifact store.

    Files are stored as: {root}/{sha256[:2]}/{sha256[2:]}.blob
    Metadata sidecars: {root}/{sha256[:2]}/{sha256[2:]}.meta.json
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def _blob_path(self, digest: str) -> Path:
        return self._root / digest[:2] / f"{digest[2:]}.blob"

    def _meta_path(self, digest: str) -> Path:
        return self._root / digest[:2] / f"{digest[2:]}.meta.json"

    async def store(
        self,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        digest = hashlib.sha256(data).hexdigest()
        blob_path = self._blob_path(digest)

        if not blob_path.exists():
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            blob_path.write_bytes(data)

            meta = {
                "content_type": content_type,
                "size": len(data),
                **(metadata or {}),
            }
            self._meta_path(digest).write_text(json.dumps(meta))

        return f"sha256:{digest}"

    async def retrieve(self, ref: str) -> bytes:
        digest = _parse_ref(ref)
        blob_path = self._blob_path(digest)
        if not blob_path.exists():
            msg = f"Artifact not found: {ref}"
            raise FileNotFoundError(msg)
        return blob_path.read_bytes()

    async def exists(self, ref: str) -> bool:
        digest = _parse_ref(ref)
        return self._blob_path(digest).exists()

    async def delete(self, ref: str) -> None:
        digest = _parse_ref(ref)
        blob_path = self._blob_path(digest)
        meta_path = self._meta_path(digest)
        if blob_path.exists():
            blob_path.unlink()
        if meta_path.exists():
            meta_path.unlink()


def _parse_ref(ref: str) -> str:
    """Extract the hex digest from a 'sha256:...' reference."""
    if not ref.startswith("sha256:"):
        msg = f"Unsupported artifact ref format: {ref}"
        raise ValueError(msg)
    return ref[7:]
