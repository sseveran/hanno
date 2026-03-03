"""Tests for the local filesystem artifact store."""

from pathlib import Path

import pytest
from hanno_core.stores.local_fs import LocalFsArtifactStore


@pytest.fixture
def store(tmp_path: Path):
    return LocalFsArtifactStore(tmp_path)


class TestLocalFsArtifactStore:
    async def test_store_and_retrieve(self, store):
        data = b"hello world"
        ref = await store.store(data)
        assert ref.startswith("sha256:")

        retrieved = await store.retrieve(ref)
        assert retrieved == data

    async def test_deduplication(self, store):
        data = b"same content"
        ref1 = await store.store(data)
        ref2 = await store.store(data)
        assert ref1 == ref2

    async def test_exists(self, store):
        ref = await store.store(b"test data")
        assert await store.exists(ref) is True
        assert await store.exists("sha256:nonexistent") is False

    async def test_delete(self, store):
        ref = await store.store(b"to delete")
        assert await store.exists(ref) is True
        await store.delete(ref)
        assert await store.exists(ref) is False

    async def test_retrieve_nonexistent(self, store):
        with pytest.raises(FileNotFoundError):
            await store.retrieve("sha256:nonexistent")

    async def test_invalid_ref_format(self, store):
        with pytest.raises(ValueError, match="Unsupported"):
            await store.retrieve("md5:abc")

    async def test_content_addressing(self, store, tmp_path: Path):
        data = b"content addressed"
        ref = await store.store(data)
        digest = ref.split(":")[1]

        blob_path = tmp_path / digest[:2] / f"{digest[2:]}.blob"
        assert blob_path.exists()

        meta_path = tmp_path / digest[:2] / f"{digest[2:]}.meta.json"
        assert meta_path.exists()
