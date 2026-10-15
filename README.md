# minio-resource

Catalog package that runs [MinIO](https://min.io) for services that need an `s3/v1` resource and do not already have S3.

`keystonectl` starts the server from the `containers` section. It does not publish the MinIO port and it does not turn on the MinIO console. Consumers reach the server as `minio-server` on port 9000 in the `keystone-resources` network (`http://minio-server:9000`).

## One bucket and one user per consumer

`provision.sh` runs once per consumer, in a short-lived `minio/mc` container. For a consumer named `file-mcp` it creates:

- a bucket named `file-mcp`
- a user named `file-mcp`, whose access key is the same name
- a policy `file-mcp-bucket-rw` that allows object, list, and lifecycle calls on that bucket only

The MinIO root user and root password stay with `keystonectl`. They are not written into the consumer's environment. A second run for the same consumer keeps the bucket, the existing secret, and any objects already stored.

`service remove` does not delete the bucket or the user. Data in the `data` volume remains until an operator removes that volume.

The policy allows the seven `s3/v1` actions and nothing else:

- on the bucket: `s3:ListBucket`, `s3:GetBucketLocation`, `s3:GetLifecycleConfiguration`, `s3:PutLifecycleConfiguration`
- on objects: `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`

The package does not set a lifecycle rule. The consumer does that itself (for example a rule on `uploads/`). Multipart upload is not part of `s3/v1`.

This was checked with `mc` `RELEASE.2025-08-13T08-35-41Z`. That release creates and updates a user when the secret is passed on stdin (`mc admin user add ALIAS ACCESSKEY`), and it uses `mc admin policy create` and `mc admin policy attach`.

## How keystonectl runs provision.sh

Secrets are not command-line arguments. The installer puts `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` in the environment of `docker`, and passes `-e NAME` without a value. The consumer secret is a file, mode `600`, mounted at `/out`.

```bash
docker run --rm --network keystone-resources \
  -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD \
  -e MC_CONFIG_DIR=/tmp/mc \
  -v <package directory>:/pkg:ro \
  -v <secret directory, mode 700>:/out \
  --entrypoint /bin/sh ghcr.io/keystone-codes/minio-client@sha256:63ba7ba9b7ba59af56cb52d9052eb385cce4e8531b40d6b43639c9e7e514c97f \
  /pkg/provision.sh --consumer file-mcp --endpoint http://minio-server:9000 --secret-file /out/file-mcp.secret
```

Optional arguments: `--region` (default `us-east-1`) and `--ready-timeout` (seconds, default 60).

Stdout is one JSON line and nothing else. The secret is not in that JSON. `keystonectl` reads it from `secret_key_file` and stores it in the consumer's env file (`packages/<name>.env`, or `packages/<name>.s3.env` when only some containers need S3). Those files are mode `600`.

```json
{"interface":"s3/v1","endpoint":"http://minio-server:9000","region":"us-east-1","bucket":"file-mcp","access_key":"file-mcp","path_style":true,"secret_key_file":"/out/file-mcp.secret"}
```

Exit codes: `0` done, `2` bad arguments or environment, `3` MinIO is down, the root password does not match the volume, or an `mc` command failed.

Inside the container, `mc` reads the root key and the consumer secret from stdin (`mc alias import` and `mc admin user add`). Neither value is an argument of `mc`.

## Why the console is off

`MINIO_BROWSER=off`, and the server command has no `--console-address`. The console is not used by services, and its port would be another way in. Only port 9000 exists, and it stays on the resource network.

## Risk: MinIO updates

Accepted by the product owner on 2026-10-12.

Free MinIO images stopped receiving updates, including security fixes, in late 2025. This package runs the last published release binaries. Docker Hub and `quay.io/minio` no longer serve those images, so the same binaries are packaged here and pulled from GHCR. The digest below is of that package. It is not the old Docker Hub index.

| Image | Software | Digest |
|---|---|---|
| `ghcr.io/keystone-codes/minio-server` | server `RELEASE.2025-09-07T16-13-09Z` | `sha256:af8333b0a5e9209abbb677c546b595dec87b45a227f33a2757b60e7d0ec5717f` |
| `ghcr.io/keystone-codes/minio-client` | client `RELEASE.2025-08-13T08-35-41Z` | `sha256:63ba7ba9b7ba59af56cb52d9052eb385cce4e8531b40d6b43639c9e7e514c97f` |

Checked on 2026-10-13. GitHub has a later server tag, `RELEASE.2025-10-15T17-29-55Z`, but that release was never published as a container image (the notes say to build it from source). No newer `mc` binary was published after `RELEASE.2025-08-13T08-35-41Z`. Security fixes for this software are not being published.

To see whether a newer release exists, check the GitHub release lists:

- https://github.com/minio/minio/releases
- https://github.com/minio/mc/releases

A digest is the pin. The software release in the table is only a label in the comments of `keystone-service.yaml`.

MinIO remains the default `s3/v1` provider. Another catalog provider (Garage, SeaweedFS, RustFS) or an external S3 endpoint can replace it through the same `s3/v1` interface. Services do not change.

## Licenses

This repository (Dockerfiles, `provision.sh`, tests, documentation) is licensed under Apache-2.0 (see `LICENSE`).

The published images bundle unmodified, pre-built binaries of third-party software:

| Image | Software | License |
|---|---|---|
| `ghcr.io/keystone-codes/minio-server` | MinIO Server `RELEASE.2025-09-07T16-13-09Z`, copyright MinIO, Inc. | AGPL-3.0-or-later |
| `ghcr.io/keystone-codes/minio-client` | MinIO Client (`mc`) `RELEASE.2025-08-13T08-35-41Z`, copyright MinIO, Inc. | AGPL-3.0-or-later |

Source for these releases: [`minio/minio`](https://github.com/minio/minio/tree/RELEASE.2025-09-07T16-13-09Z) and [`minio/mc`](https://github.com/minio/mc/tree/RELEASE.2025-08-13T08-35-41Z), at the release tags above. Full details, including the license text locations, are in `NOTICE`.

An operator who modifies and distributes these images takes on the AGPL-3.0 obligations for the MinIO Server and MinIO Client binaries they contain.

## Tests

```bash
shellcheck -s sh provision.sh tests/fake-mc
bats tests/provision.bats
uv sync
uv run pytest -q -m integration
```

The integration tests need Docker and the pinned server image. They create only networks and containers whose names start with `ks-pkg-p01-`.

## Releasing

1. On a branch named `release/<version>`, set `version` in `keystone-service.yaml` and `pyproject.toml`, and add a line to `CHANGELOG.md`.
2. The owner pushes that branch.
3. `gh workflow run release-image.yml --ref release/<version> -f version=<version>`
4. Review and merge the pull request from `release/pin-<version>`.
5. `tag-release.yml` creates the git tag `v<version>` after the registry digests match the manifest.

The GHCR tag `:<version>` is never overwritten. A fix is a new version.

See [Releasing a new version](https://github.com/keystone-codes/keystonectl/blob/main/docs/packaging-a-service.md#releasing-a-new-version) in the keystonectl packaging guide.
