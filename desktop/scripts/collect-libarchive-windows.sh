#!/usr/bin/env bash
# Run in an MSYS2 UCRT64 shell with mingw-w64-ucrt-x86_64-libarchive installed (pacman verifies its packages).
# Copies libarchive and the DLLs it needs from MSYS2 into desktop/vendor/libarchive.
set -euo pipefail
target="$(dirname "$0")/../vendor/libarchive"
library="$MSYSTEM_PREFIX/bin/libarchive-13.dll"
mkdir -p "$target"
cp "$library" "$target/"
ldd "$library" | awk '/ucrt64/ { print $3 }' | sort -u | xargs -I{} cp {} "$target/"
ls -l "$target"
