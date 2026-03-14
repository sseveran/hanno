"""Tests for repo-context normalization helpers."""

from hanno_core.repo_context import derive_repo_display_name, normalize_git_remote


def test_normalize_https_remote():
    assert (
        normalize_git_remote("https://github.com/OpenAI/hanno.git")
        == "github.com/openai/hanno"
    )


def test_normalize_ssh_remote():
    assert (
        normalize_git_remote("git@github.com:OpenAI/hanno.git")
        == "github.com/openai/hanno"
    )


def test_derive_display_name_from_remote():
    assert derive_repo_display_name("github.com/openai/hanno") == "hanno"


def test_derive_display_name_from_local_path():
    assert derive_repo_display_name("", "/tmp/worktrees/hanno") == "hanno"
