"""Artifact model — immutable blobs or references."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID


class Artifact(BaseModel):
    """Metadata record for an artifact stored in an ArtifactStore."""

    id: str = Field(default_factory=lambda: str(ULID()))

    run_id: str

    step_run_id: str | None = None
    """Optional association with a specific step."""

    kind: str
    """Artifact kind: 'transcript', 'diff', 'patch', 'log', 'dataset', 'report', 'aar', etc."""

    uri: str
    """URI referencing the blob in the artifact store."""

    content_hash: str
    """Content hash (e.g. 'sha256:abcdef...')."""

    size: int
    """Size in bytes."""

    content_type: str = "application/octet-stream"

    name: str = ""
    """Human-readable name."""

    metadata: dict[str, object] = {}

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
