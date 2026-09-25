import subprocess

import pytest

from trading_robinhood.release import build_manifest, verify_manifest


def repository(tmp_path):
    for args in [
        ["init", "-b", "main"],
        ["config", "user.name", "Test"],
        ["config", "user.email", "test@example.invalid"],
    ]:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "app.py").write_text("print('test')\n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"], cwd=tmp_path, check=True, capture_output=True
    )
    return tmp_path


def test_manifest_detects_changed_artifact_and_policy(tmp_path):
    root = repository(tmp_path)
    manifest = build_manifest(root, policy_digest="abc", capability_digest="none")
    verify_manifest(root, manifest, policy_digest="abc")
    assert manifest["live_certified"] is False
    with pytest.raises(ValueError, match="policy"):
        verify_manifest(root, manifest, policy_digest="different")
    (root / "app.py").write_text("print('tampered')\n")
    with pytest.raises(ValueError):
        verify_manifest(root, manifest, policy_digest="abc")


def test_dirty_or_untracked_source_cannot_create_release(tmp_path):
    root = repository(tmp_path)
    (root / "unexpected.py").write_text("bad = True\n")
    with pytest.raises(ValueError, match="clean"):
        build_manifest(root, policy_digest="abc", capability_digest="none")
