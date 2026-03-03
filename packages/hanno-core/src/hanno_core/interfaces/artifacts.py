"""ArtifactStore protocol — blob storage contract."""

from __future__ import annotations

from typing import Protocol


class ArtifactStore(Protocol):
    """Content-addressable blob storage for artifacts.

    Implementations: local filesystem (SHA-256), S3-compatible.
    """

    async def store(
        self,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Store bytes and return a content-addressed reference (e.g. 'sha256:abcdef...')."""
        ...

    async def retrieve(self, ref: str) -> bytes:
        """Retrieve bytes by reference."""
        ...

    async def exists(self, ref: str) -> bool:
        """Check if a reference exists."""
        ...

    async def delete(self, ref: str) -> None:
        """Delete a stored blob."""
        ...
