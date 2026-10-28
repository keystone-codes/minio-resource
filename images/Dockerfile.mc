# registry.access.redhat.com/ubi9/ubi-minimal:9.6
FROM registry.access.redhat.com/ubi9/ubi-minimal:9.6@sha256:34880b64c07f28f64d95737f82f891516de9a3b43583f39970f7bf8e4cfa48b7

ARG TARGETARCH
# Set by release-image.yml to the version being published (X.Y.Z); used only
# for the org.opencontainers.image.version label below.
ARG RELEASE_VERSION=0.0.0-dev

# Pick up HIGH/CRITICAL fixes already published for the base layer.
RUN microdnf upgrade -y && microdnf clean all

# keystone-minio, uid:gid 10001:10001, same account as minio-server. The
# image still defaults to root: provision.sh writes the per-consumer secret
# file into a directory keystonectl creates on the host under whatever
# uid runs the installer, and root is the only account guaranteed to be
# able to write there on every install. Pass `--user 10001:10001` (or
# `--user "$(id -u):$(id -g)"` to match the host, as the integration tests
# here do) to run this image as non-root where the operator has arranged
# for /out to be writable by that uid.
RUN groupadd --gid 10001 keystone-minio \
    && useradd --uid 10001 --gid 10001 --home-dir /nonexistent --no-create-home \
        --shell /sbin/nologin keystone-minio

COPY mc.linux-${TARGETARCH} /usr/bin/mc
COPY LICENSE.AGPL-3.0 /licenses/LICENSE.AGPL-3.0
COPY NOTICE /licenses/NOTICE
RUN chmod 755 /usr/bin/mc

ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    MC_CONFIG_DIR=/tmp/.mc

LABEL org.opencontainers.image.source="https://github.com/keystone-codes/minio-resource" \
      org.opencontainers.image.revision="RELEASE.2025-08-13T08-35-41Z" \
      org.opencontainers.image.version="${RELEASE_VERSION}" \
      org.opencontainers.image.title="mc" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"
ENTRYPOINT ["mc"]
