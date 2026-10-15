# Changelog

## 1.0.1

- Images are rebuilt from the same MinIO binaries (server `RELEASE.2025-09-07T16-13-09Z`, client `RELEASE.2025-08-13T08-35-41Z`). They now carry the AGPL-3.0 text at `/licenses/LICENSE.AGPL-3.0` and the label `org.opencontainers.image.licenses=AGPL-3.0-or-later`.
- New image digests. The 1.0.0 digests stay pullable.
- The release workflow refuses binaries whose sha256 differs from the pinned values (the binaries inside the 1.0.0 images).
- Images are published by version with `release-image.yml`; digests are pinned by a pull request and the tag is created after the registry digests match.

## 1.0.0

- First release of the `minio` resource package (`provides: s3/v1`).
- Each consumer gets its own bucket and user. The MinIO root key stays with the installer.
- Runs MinIO server `RELEASE.2025-09-07T16-13-09Z` and client `RELEASE.2025-08-13T08-35-41Z`, pulled from GHCR because Docker Hub no longer serves those images.
