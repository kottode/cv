#!/usr/bin/env bash
set -euo pipefail

# If user runs script with `sh install.sh` (dash/posix shell), re-exec under bash
# because script relies on bash-specific variables like BASH_SOURCE.
if [ -z "${BASH_VERSION:-}" ]; then
    if command -v bash >/dev/null 2>&1; then
        exec bash "$0" "$@"
    else
        printf 'Error: bash required to run installer.\n' >&2
        exit 1
    fi
fi

TARGET="${1:-$HOME/.local/bin/cv}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="$SOURCE_DIR/cv"
SOURCE_CORE_FILE="$SOURCE_DIR/cv_core.py"
SOURCE_PACKAGE_DIR="$SOURCE_DIR/cvapp"

if [ ! -f "$SOURCE_FILE" ]; then
    printf 'Error: cv script not found at %s\n' "$SOURCE_FILE" >&2
    exit 1
fi

if [ ! -f "$SOURCE_CORE_FILE" ]; then
    printf 'Error: cv core script not found at %s\n' "$SOURCE_CORE_FILE" >&2
    exit 1
fi

if [ ! -d "$SOURCE_PACKAGE_DIR" ]; then
    printf 'Error: cv package not found at %s\n' "$SOURCE_PACKAGE_DIR" >&2
    exit 1
fi

TARGET_DIR="$(dirname "$TARGET")"
mkdir -p "$TARGET_DIR"
cp "$SOURCE_FILE" "$TARGET"
cp "$SOURCE_CORE_FILE" "$TARGET_DIR/cv_core.py"
rm -rf "$TARGET_DIR/cvapp"
cp -R "$SOURCE_PACKAGE_DIR" "$TARGET_DIR/cvapp"
chmod +x "$TARGET"

printf 'Installed: %s\n' "$TARGET"
printf 'Ensure PATH contains: %s\n' "$TARGET_DIR"
