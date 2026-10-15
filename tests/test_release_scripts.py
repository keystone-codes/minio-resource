"""Release scripts edit the two image pins and refuse a version that is not this tree."""

from __future__ import annotations

from pathlib import Path

import check_release_version
import pin_digests

_ROOT = Path(__file__).resolve().parents[1]
_OLD_SERVER = "af8333b0a5e9209abbb677c546b595dec87b45a227f33a2757b60e7d0ec5717f"
_OLD_CLIENT = "63ba7ba9b7ba59af56cb52d9052eb385cce4e8531b40d6b43639c9e7e514c97f"
_NEW_SERVER = "0123456789abcdef" * 4
_NEW_CLIENT = "fedcba9876543210" * 4

_MANIFEST = f"""\
schema_version: 1
# comment stays
version: 1.2.3
containers:
  server:
    image: ghcr.io/keystone-codes/minio-server@sha256:{_OLD_SERVER}
provision:
  image: ghcr.io/keystone-codes/minio-client@sha256:{_OLD_CLIENT}
"""

_README = f"""\
Example `ghcr.io/keystone-codes/minio-client@sha256:{_OLD_CLIENT}` stays.

| Image | Digest |
|---|---|
| `ghcr.io/keystone-codes/minio-server` | `sha256:{_OLD_SERVER}` |
| `ghcr.io/keystone-codes/minio-client` | `sha256:{_OLD_CLIENT}` |

| Image | License |
|---|---|
| `ghcr.io/keystone-codes/minio-server` | AGPL-3.0-or-later |
| `ghcr.io/keystone-codes/minio-client` | AGPL-3.0-or-later |
"""


def _write_pair(tmp_path: Path, manifest: str = _MANIFEST, readme: str = _README) -> None:
    (tmp_path / "keystone-service.yaml").write_text(manifest, encoding="utf-8")
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")


def _texts(tmp_path: Path) -> tuple[str, str]:
    manifest = (tmp_path / "keystone-service.yaml").read_text(encoding="utf-8")
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    return manifest, readme


def test_pin_updates_manifest_and_readme_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = (_ROOT / "keystone-service.yaml").read_text(encoding="utf-8")
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    _write_pair(tmp_path, manifest, readme)
    completed = pin_digests.main([f"sha256:{_NEW_SERVER}", _NEW_CLIENT])
    assert completed == 0
    new_manifest, new_readme = _texts(tmp_path)
    assert new_manifest == manifest.replace(_OLD_SERVER, _NEW_SERVER).replace(_OLD_CLIENT, _NEW_CLIENT)
    assert new_readme == readme.replace(_OLD_SERVER, _NEW_SERVER).replace(
        f"`sha256:{_OLD_CLIENT}`", f"`sha256:{_NEW_CLIENT}`"
    )
    assert f"@sha256:{_OLD_CLIENT}" in new_readme
    assert "# The old Docker Hub index sha256:14cea493" in new_manifest


def test_pin_refuses_a_missing_line(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = _MANIFEST.replace(
        f"  image: ghcr.io/keystone-codes/minio-client@sha256:{_OLD_CLIENT}\n",
        "",
    )
    assert "minio-client@sha256" not in manifest
    _write_pair(tmp_path, manifest, _README)
    before = _texts(tmp_path)
    assert pin_digests.main([_NEW_SERVER, _NEW_CLIENT]) == 1
    assert _texts(tmp_path) == before


def test_pin_refuses_two_lines_for_one_image(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    extra = f"    image: ghcr.io/keystone-codes/minio-server@sha256:{_OLD_SERVER}\n"
    _write_pair(tmp_path, _MANIFEST + extra, _README)
    before = _texts(tmp_path)
    assert pin_digests.main([_NEW_SERVER, _NEW_CLIENT]) == 1
    assert _texts(tmp_path) == before


def test_pin_refuses_a_digest_that_is_not_64_hex_digits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_pair(tmp_path)
    before = _texts(tmp_path)
    assert pin_digests.main(["sha256:not-a-digest", _NEW_CLIENT]) == 1
    assert pin_digests.main([_NEW_SERVER.upper(), _NEW_CLIENT]) == 1
    assert _texts(tmp_path) == before


def test_pin_rejects_the_wrong_number_of_arguments(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_pair(tmp_path)
    before = _texts(tmp_path)
    assert pin_digests.main([]) == 2
    assert pin_digests.main([_NEW_SERVER]) == 2
    assert _texts(tmp_path) == before


def test_print_emits_version_and_both_digests(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "keystone-service.yaml").write_text(_MANIFEST, encoding="utf-8")
    assert pin_digests.main(["--print"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "version=1.2.3",
        f"server=sha256:{_OLD_SERVER}",
        f"client=sha256:{_OLD_CLIENT}",
    ]


def test_version_problem_when_manifest_differs() -> None:
    problem = check_release_version.version_problem("1.2.3", "1.2.3", "1.2.2")
    assert problem is not None
    assert "1.2.3" in problem
    assert "1.2.2" in problem


def test_version_problem_when_project_differs() -> None:
    problem = check_release_version.version_problem("1.2.3", "9.9.9", "1.2.3")
    assert problem is not None
    assert "9.9.9" in problem
    assert "1.2.3" in problem
