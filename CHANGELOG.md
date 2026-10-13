# Changelog

## 1.0.0

- First release of the `minio` resource package (`provides: s3/v1`).
- Each consumer gets its own bucket and user. The MinIO root key stays with the installer.
- Runs MinIO server `RELEASE.2025-09-07T16-13-09Z` and client `RELEASE.2025-08-13T08-35-41Z`, pulled from GHCR because Docker Hub no longer serves those images.
