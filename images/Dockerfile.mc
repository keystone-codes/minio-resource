FROM registry.access.redhat.com/ubi9/ubi-minimal:9.6

ARG TARGETARCH

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
