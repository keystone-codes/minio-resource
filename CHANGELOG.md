# Changelog

## 1.0.2 - 2026-10-28

- `minio-server` and `minio-client` are rebuilt from `registry.access.redhat.com/ubi9/ubi-minimal:9.6`, now pinned by digest, with `microdnf upgrade` run at build time. Trivy against the rebuilt images reports 0 CRITICAL/HIGH OS findings (previously 163 of the CRITICAL/HIGH findings in 1.0.1 were in the base layer).
- Both images run as `keystone-minio` (uid:gid `10001:10001`) instead of root. `minio-server` still starts as root and drops privileges itself in `docker-entrypoint.sh`: on an existing `data` volume from 1.0.0/1.0.1 (owned by root), the first 1.0.2 start `chown -R`s it to `10001:10001` once, then every later start is a `stat`, not a `chown -R`. The deprecated `MINIO_USERNAME`/`MINIO_GROUPNAME`/`MINIO_UID`/`MINIO_GID` switch keeps working for operators who still set it. `minio-client` keeps defaulting to root (see README.md#running-as-non-root for why) but gets the same account for operators who pass `--user` themselves.
- `NOTICE` (upstream MinIO/mc source and license locations) is now at `/licenses/NOTICE` in both images, next to `/licenses/LICENSE.AGPL-3.0`. Both images also carry `org.opencontainers.image.version`.
- `release-image.yml` turns on `provenance` and `sbom` (both were `false`), and gates on Trivy OS-package findings (CRITICAL/HIGH, ignore-unfixed, exit-code 1) after publishing each image; a second, non-gating scan covers the bundled `minio`/`mc` Go binaries, which this package cannot fix because both are archived upstream (see CT-01/PK-01 in the publication audit).
- CI now runs `ruff check`/`ruff format --check` and lints `keystone-service.yaml` with `keystonectl==0.2.0` (the version on PyPI, not the `0.1.0` pre-release it used before). Added `.github/dependabot.yml` (pip, docker, github-actions).

## 1.0.1

- Images are rebuilt from the same MinIO binaries (server `RELEASE.2025-09-07T16-13-09Z`, client `RELEASE.2025-08-13T08-35-41Z`). They now carry the AGPL-3.0 text at `/licenses/LICENSE.AGPL-3.0` and the label `org.opencontainers.image.licenses=AGPL-3.0-or-later`.
- New image digests. The 1.0.0 digests stay pullable.
- The release workflow refuses binaries whose sha256 differs from the pinned values (the binaries inside the 1.0.0 images).
- Images are published by version with `release-image.yml`; digests are pinned by a pull request and the tag is created after the registry digests match.

## 1.0.0

- First release of the `minio` resource package (`provides: s3/v1`).
- Each consumer gets its own bucket and user. The MinIO root key stays with the installer.
- Runs MinIO server `RELEASE.2025-09-07T16-13-09Z` and client `RELEASE.2025-08-13T08-35-41Z`, pulled from GHCR because Docker Hub no longer serves those images.
