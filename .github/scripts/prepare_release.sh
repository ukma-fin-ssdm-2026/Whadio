#!/usr/bin/env bash
# Writes the next release into the working tree and prints its version; prints nothing when no
# commit since the last v* tag is releasable (cliff.toml decides which are).
set -euo pipefail

latest=$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*')
next=$(uv run --frozen git-cliff --bumped-version 2>/dev/null)
if [[ "$next" == "$latest" ]]; then
  exit 0
fi
version=${next#v}

uv version "$version" --no-sync >/dev/null
npm --prefix frontend version "$version" --no-git-tag-version --ignore-scripts >/dev/null
sed -i -E "s/^(  \"version\": )\"[^\"]+\"/\1\"${version}\"/" extension/manifest.json
# The API reads its version from the installed package, which `uv run` reinstalls first.
uv run --frozen whadio openapi >/dev/null
uv run --frozen git-cliff --unreleased --tag "$next" --prepend CHANGELOG.md 2>/dev/null

echo "$version"
