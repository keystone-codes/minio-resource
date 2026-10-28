#!/bin/sh
#

# If command starts with an option, prepend minio.
if [ "${1}" != "minio" ]; then
	if [ -n "${1}" ]; then
		set -- minio "$@"
	fi
fi

docker_switch_user() {
	if [ -n "${MINIO_USERNAME}" ] && [ -n "${MINIO_GROUPNAME}" ]; then
		if [ -n "${MINIO_UID}" ] && [ -n "${MINIO_GID}" ]; then
			chroot --userspec=${MINIO_UID}:${MINIO_GID} / "$@"
		else
			echo "${MINIO_USERNAME}:x:1000:1000:${MINIO_USERNAME}:/:/sbin/nologin" >>/etc/passwd
			echo "${MINIO_GROUPNAME}:x:1000" >>/etc/group
			chroot --userspec=${MINIO_USERNAME}:${MINIO_GROUPNAME} / "$@"
		fi
	else
		exec "$@"
	fi
}

# keystone-minio, created in the image at build time.
KEYSTONE_MINIO_UID=10001
KEYSTONE_MINIO_GID=10001

## DEPRECATED and unsupported - switch to user if applicable. Kept for
## operators who still set MINIO_USERNAME/MINIO_GROUPNAME (or the uid/gid
## pair) from before this image dropped privileges on its own.
if [ -n "${MINIO_USERNAME}" ] && [ -n "${MINIO_GROUPNAME}" ]; then
	docker_switch_user "$@"
	exit $?
fi

# 1.0.2+: when the image starts as root (the default, so an existing
# root-owned /data volume keeps working), chown /data to keystone-minio
# only if it is not already owned by that uid, then drop to it. A second
# start on the same volume is a stat, not a chown.
if [ "$(id -u)" = "0" ]; then
	if [ -d /data ]; then
		data_owner=$(stat -c '%u' /data 2>/dev/null)
		if [ "${data_owner}" != "${KEYSTONE_MINIO_UID}" ]; then
			chown -R "${KEYSTONE_MINIO_UID}:${KEYSTONE_MINIO_GID}" /data
		fi
	fi
	exec chroot --userspec="${KEYSTONE_MINIO_UID}:${KEYSTONE_MINIO_GID}" / "$@"
fi

# Already non-root (an operator set containers.server.user themselves).
exec "$@"
