"""Interface protocols for the workflow ledger."""

from .artifacts import ArtifactStore
from .hooks import Hook, HookRegistry
from .identity import IdentityProvider
from .search import SearchBackend
from .storage import StorageBackend

__all__ = [
    "ArtifactStore",
    "Hook",
    "HookRegistry",
    "IdentityProvider",
    "SearchBackend",
    "StorageBackend",
]
