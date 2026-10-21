#!/usr/bin/env bash
# Publishes a GitHub release with the wheel and talkpod-manager.json (version, wheel name,
# SHA-256) for the in-app updater and scripts/install.sh.
#
# Usage: scripts/release.sh NOTES.md
# Bump __version__ in talkpod_manager/__init__.py and commit first.
set -euo pipefail
cd "$(dirname "$0")/.."
notes="${1:?usage: scripts/release.sh NOTES.md}"
[[ -f "$notes" ]] || { echo "no notes file: $notes" >&2; exit 2; }
version=$(python3 -c 'import re; print(re.search(r"__version__ = \"(.+?)\"", open("talkpod_manager/__init__.py").read()).group(1))')
if git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
  echo "tag v$version already exists" >&2; exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "commit your changes first" >&2; exit 1
fi
.venv/bin/python -m pytest -q
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
.venv/bin/python -m pip wheel -q --no-deps -w "$tmp" .
wheel=$(cd "$tmp" && ls talkpod_manager-"$version"-*.whl)
sha=$(sha256sum "$tmp/$wheel" | cut -d' ' -f1)
printf '{"version": "%s", "wheel": "%s", "sha256": "%s"}\n' "$version" "$wheel" "$sha" > "$tmp/talkpod-manager.json"
git tag -a "v$version" -m "Talkpod Manager $version"
git push origin main "v$version"
gh release create "v$version" "$tmp/$wheel" "$tmp/talkpod-manager.json" \
  --title "Talkpod Manager $version" --notes-file "$notes" --verify-tag
echo "released Talkpod Manager $version ($wheel, sha256 $sha)"
