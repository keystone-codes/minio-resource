# registry.access.redhat.com/ubi9/ubi-minimal:9.6
FROM registry.access.redhat.com/ubi9/ubi-minimal:9.6@sha256:34880b64c07f28f64d95737f82f891516de9a3b43583f39970f7bf8e4cfa48b7

ARG TARGETARCH

# Pick up HIGH/CRITICAL fixes already published for the base layer.
RUN microdnf upgrade -y && microdnf clean all

COPY mc.linux-${TARGETARCH} /usr/bin/mc
COPY LICENSE.AGPL-3.0 /licenses/LICENSE.AGPL-3.0
RUN chmod 755 /usr/bin/mc

ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    MC_CONFIG_DIR=/tmp/.mc

LABEL org.opencontainers.image.source="https://github.com/keystone-codes/minio-resource" \
      org.opencontainers.image.revision="RELEASE.2025-08-13T08-35-41Z" \
      org.opencontainers.image.title="mc" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"
ENTRYPOINT ["mc"]
