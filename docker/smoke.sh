#!/bin/sh
# Smoke-test an image: health, web UI deep link, 401 without login, bsdtar, PUID/PGID.
# Usage: docker/smoke.sh <image>
set -eu
image="$1"
name="shutong-smoke-$$"
port=18899
cleanup() { docker rm -f "$name" "$name-uid" >/dev/null 2>&1 || true; }
trap cleanup EXIT

wait_healthy() {
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$2/api/auth/status" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  docker logs "$1"
  echo "container $1 did not come up" >&2
  return 1
}

docker run -d --name "$name" -p "$port:8899" "$image" >/dev/null
wait_healthy "$name" "$port"
curl -fsS "http://127.0.0.1:$port/api/auth/status" | grep -q '"configured"'
curl -fsS "http://127.0.0.1:$port/libraries/1/review" | grep -q '<div id="app">'
test "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/api/libraries")" = 401
docker exec "$name" bsdtar --version >/dev/null
docker exec "$name" test -f /config/shutong.db
# A command after the image name runs instead of the server.
docker run --rm "$image" shutong --help | grep -q serve

docker run -d --name "$name-uid" -e PUID=1000 -e PGID=1000 -p "$((port + 1)):8899" "$image" >/dev/null
wait_healthy "$name-uid" "$((port + 1))"
# The slim image has no ps: find the server process through /proc ([ ] keeps the grep from matching itself).
uid=$(docker exec "$name-uid" sh -c 'for p in /proc/[0-9]*; do if tr "\0" " " < "$p/cmdline" 2>/dev/null | grep -q "bin/shutong[ ]serve"; then stat -c %u "$p"; break; fi; done')
test "$uid" = 1000
test "$(docker exec "$name-uid" stat -c %u /config/shutong.db)" = 1000

docker image inspect "$image" --format 'image size: {{.Size}} bytes'
echo "smoke ok"
