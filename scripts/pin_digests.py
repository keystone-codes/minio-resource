#!/usr/bin/env python3
"""Replace the MinIO server and client digests in the manifest and the README table.

The rest of each file, including comments and the provision example, stays as
it is. A digest is 64 lowercase hex digits; a ``sha256:`` prefix is optional.
Wrong arguments exit 2. A bad digest, or not exactly one matching line per
image, exits 1 and leaves both files unchanged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r'(?m)^version:\s*["\']?([^"\'#\s]+)')
_README_DIGEST = re.compile(r"`sha256:[0-9a-f]{64}`")
_MANIFEST = Path("keystone-service.yaml")
_README = Path("README.md")
_IMAGES = ("minio-server", "minio-client")


class _PinError(Exception):
    pass


def _normalize(digest: str) -> str | None:
    if digest.startswith("sha256:"):
        digest = digest[len("sha256:") :]
    if _DIGEST.fullmatch(digest) is None:
        return None
    return digest


def _split_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _PinError(f"{path}: {exc.strerror or exc}") from exc


def _manifest_candidates(lines: list[str], image: str) -> list[int]:
    needle = f"ghcr.io/keystone-codes/{image}@sha256:"
    found: list[int] = []
    for index, line in enumerate(lines):
        body, _ending = _split_ending(line)
        stripped = body.lstrip(" \t")
        if stripped.startswith("image:") and needle in stripped:
            found.append(index)
    return found


def _rewrite_manifest(line: str, image: str, digest: str) -> str | None:
    body, ending = _split_ending(line)
    pattern = re.compile(
        rf"^(?P<head>[ \t]*image:[ \t]+ghcr\.io/keystone-codes/{re.escape(image)}@sha256:)"
        rf"[0-9a-f]{{64}}(?P<tail>.*)$"
    )
    match = pattern.fullmatch(body)
    if match is None:
        return None
    return f"{match.group('head')}{digest}{match.group('tail')}{ending}"


def _readme_candidates(lines: list[str], image: str) -> list[int]:
    needle = f"ghcr.io/keystone-codes/{image}"
    found: list[int] = []
    for index, line in enumerate(lines):
        body, _ending = _split_ending(line)
        if needle in body and _README_DIGEST.search(body):
            found.append(index)
    return found


def _rewrite_readme(line: str, digest: str) -> str | None:
    body, ending = _split_ending(line)
    if len(_README_DIGEST.findall(body)) != 1:
        return None
    return _README_DIGEST.sub(f"`sha256:{digest}`", body, count=1) + ending


def _replace_one(
    lines: list[str],
    indexes: list[int],
    rewrite,
    label: str,
) -> None:
    if len(indexes) != 1:
        raise _PinError(f"expected exactly one {label} line, found {len(indexes)}")
    updated = rewrite(lines[indexes[0]])
    if updated is None:
        raise _PinError(f"the {label} line has no sha256 digest")
    lines[indexes[0]] = updated


def _apply(manifest: str, readme: str, server: str, client: str) -> tuple[str, str]:
    manifest_lines = manifest.splitlines(keepends=True)
    readme_lines = readme.splitlines(keepends=True)
    digests = {"minio-server": server, "minio-client": client}
    for image in _IMAGES:
        digest = digests[image]
        _replace_one(
            manifest_lines,
            _manifest_candidates(manifest_lines, image),
            lambda line, image=image, digest=digest: _rewrite_manifest(line, image, digest),
            f"{image} image:",
        )
        _replace_one(
            readme_lines,
            _readme_candidates(readme_lines, image),
            lambda line, digest=digest: _rewrite_readme(line, digest),
            f"{image} README",
        )
    return "".join(manifest_lines), "".join(readme_lines)


def _manifest_digest(lines: list[str], image: str) -> str:
    indexes = _manifest_candidates(lines, image)
    if len(indexes) != 1:
        raise _PinError(f"expected exactly one {image} image: line, found {len(indexes)}")
    body, _ending = _split_ending(lines[indexes[0]])
    match = re.search(rf"ghcr\.io/keystone-codes/{re.escape(image)}@sha256:([0-9a-f]{{64}})\b", body)
    if match is None:
        raise _PinError(f"the {image} image line has no sha256 digest")
    return match.group(1)


def _print_pins() -> int:
    text = _read(_MANIFEST)
    version = _VERSION.search(text)
    if version is None:
        print("pin_digests: version is missing from keystone-service.yaml", file=sys.stderr)
        return 1
    lines = text.splitlines(keepends=True)
    server = _manifest_digest(lines, "minio-server")
    client = _manifest_digest(lines, "minio-client")
    print(f"version={version.group(1)}")
    print(f"server=sha256:{server}")
    print(f"client=sha256:{client}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--print"]:
        try:
            return _print_pins()
        except _PinError as exc:
            print(f"pin_digests: {exc}", file=sys.stderr)
            return 1
    if len(args) != 2:
        print(
            "usage: pin_digests.py <server-digest> <client-digest> | pin_digests.py --print",
            file=sys.stderr,
        )
        return 2
    server = _normalize(args[0])
    client = _normalize(args[1])
    if server is None or client is None:
        print("pin_digests: digest must be 64 lowercase hex digits", file=sys.stderr)
        return 1
    try:
        manifest = _read(_MANIFEST)
        readme = _read(_README)
        new_manifest, new_readme = _apply(manifest, readme, server, client)
    except _PinError as exc:
        print(f"pin_digests: {exc}", file=sys.stderr)
        return 1
    _MANIFEST.write_text(new_manifest, encoding="utf-8")
    _README.write_text(new_readme, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
