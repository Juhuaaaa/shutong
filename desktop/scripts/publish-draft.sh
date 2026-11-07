#!/usr/bin/env bash
# Usage: publish-draft.sh <run-id> <version>   e.g. publish-draft.sh 123456 0.1.0
# Takes the installers of a desktop-release run and makes a DRAFT release of the public downloads repository.
# Nothing is public until someone presses Publish there.
set -euo pipefail
run_id="$1"; version="$2"
public=Juhuaaaa/shutong-releases
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
gh run download "$run_id" --repo Juhuaaaa/shutong --dir "$work"
find "$work" -type f \( -name 'Shutong-*.dmg' -o -name 'Shutong-*.exe' \) -exec mv {} "$work/" \;
cd "$work"
shasum -a 256 Shutong-* > SHA256SUMS.txt
cat SHA256SUMS.txt
gh release create "desktop-v$version" Shutong-* SHA256SUMS.txt --repo "$public" --draft --title "书童 $version" \
  --notes "安装步骤和系统警告的处理方法见[安装教程](https://github.com/$public#readme)。"
