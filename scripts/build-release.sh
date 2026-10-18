#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npm run release:check
npm ci
if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
  if [[ -f work/keys/updater.key ]]; then
    export TAURI_SIGNING_PRIVATE_KEY="$PWD/work/keys/updater.key"
  else
    echo 'Set TAURI_SIGNING_PRIVATE_KEY to the updater private key path or contents.' >&2
    exit 1
  fi
fi
npm run tauri build -- --bundles app,dmg
echo 'Signed application and update archive are in src-tauri/target/release/bundle/macos; installer DMG is in src-tauri/target/release/bundle/dmg.'
