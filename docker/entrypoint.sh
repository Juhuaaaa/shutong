#!/bin/sh
# Run as root by default (most NAS media folders belong to root). With PUID and PGID set to a
# non-root id, create that user, make /config writable for it, and drop privileges.
# No arguments (or only options) starts the server; anything else runs as a command, e.g.
#   docker run --rm -v ./config:/config shutong shutong library list
set -e
mkdir -p "${SHUTONG_DATA:-/config}"
if [ $# -eq 0 ] || [ "${1#-}" != "$1" ]; then
  set -- shutong serve "$@"
fi
if [ -n "${PUID}" ] && [ -n "${PGID}" ] && [ "${PUID}" != "0" ]; then
  getent group "${PGID}" >/dev/null 2>&1 || groupadd -g "${PGID}" shutong
  getent passwd "${PUID}" >/dev/null 2>&1 || useradd -u "${PUID}" -g "${PGID}" -M -d "${SHUTONG_DATA:-/config}" -s /usr/sbin/nologin shutong
  chown -R "${PUID}:${PGID}" "${SHUTONG_DATA:-/config}"
  exec setpriv --reuid="${PUID}" --regid="${PGID}" --init-groups "$@"
fi
exec "$@"
