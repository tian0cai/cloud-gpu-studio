#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npm run release:check
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'Commit all release changes before publishing.' >&2
  exit 1
fi
version="$(node -p "require('./package.json').version")"
tag="v$version"
if git rev-parse "$tag" >/dev/null 2>&1; then
  echo "Tag $tag already exists." >&2
  exit 1
fi
git tag -a "$tag" -m "Cloud GPU Studio $tag"
git push origin "$tag"
echo "Pushed $tag. GitHub Actions will build a draft release for review."
