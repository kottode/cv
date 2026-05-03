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

TARGET="$HOME/.local/bin/cv"
FORCE=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --force)
            FORCE=1
            ;;
        *)
            TARGET="$1"
            ;;
    esac
    shift
done

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_CORE_FILE="$SOURCE_DIR/cv_core.py"
SOURCE_PACKAGE_DIR="$SOURCE_DIR/cvapp"
SOURCE_REQUIREMENTS="$SOURCE_DIR/requirements.txt"
SOURCE_REQUIREMENTS_ATS="$SOURCE_DIR/requirements-ats.txt"

if [ ! -f "$SOURCE_CORE_FILE" ]; then
    printf 'Error: cv core script not found at %s\n' "$SOURCE_CORE_FILE" >&2
    exit 1
fi

if [ ! -d "$SOURCE_PACKAGE_DIR" ]; then
    printf 'Error: cv package not found at %s\n' "$SOURCE_PACKAGE_DIR" >&2
    exit 1
fi

if [ ! -f "$SOURCE_REQUIREMENTS" ]; then
    printf 'Error: requirements file not found at %s\n' "$SOURCE_REQUIREMENTS" >&2
    exit 1
fi

if [ ! -f "$SOURCE_REQUIREMENTS_ATS" ]; then
    printf 'Error: ATS requirements file not found at %s\n' "$SOURCE_REQUIREMENTS_ATS" >&2
    exit 1
fi

TARGET_DIR="$(dirname "$TARGET")"
mkdir -p "$TARGET_DIR"
cp "$SOURCE_CORE_FILE" "$TARGET_DIR/cv_core.py"
rm -rf "$TARGET_DIR/cvapp"
cp -R "$SOURCE_PACKAGE_DIR" "$TARGET_DIR/cvapp"

RUNTIME_DIR="$TARGET_DIR/.cv-runtime"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEPS_HASH_FILE="$RUNTIME_DIR/.deps.sha256"

REQ_HASH="$(SOURCE_REQUIREMENTS="$SOURCE_REQUIREMENTS" SOURCE_REQUIREMENTS_ATS="$SOURCE_REQUIREMENTS_ATS" "$PYTHON_BIN" - <<'PY'
from __future__ import annotations
import hashlib
import os
from pathlib import Path
core = Path(os.environ["SOURCE_REQUIREMENTS"]).read_bytes()
ats = Path(os.environ["SOURCE_REQUIREMENTS_ATS"]).read_bytes()
print(hashlib.sha256(core + b"\n--ats--\n" + ats).hexdigest())
PY
)"

"$PYTHON_BIN" -m venv "$RUNTIME_DIR"

INSTALL_DEPS=1
if [ "$FORCE" -eq 0 ] && [ -f "$DEPS_HASH_FILE" ]; then
    CACHED_HASH="$(cat "$DEPS_HASH_FILE" 2>/dev/null || true)"
    if [ "$CACHED_HASH" = "$REQ_HASH" ]; then
        INSTALL_DEPS=0
    fi
fi

if [ "$INSTALL_DEPS" -eq 1 ]; then
    "$RUNTIME_DIR/bin/python" -m pip install --upgrade pip
    "$RUNTIME_DIR/bin/python" -m pip install -r "$SOURCE_REQUIREMENTS"
    "$RUNTIME_DIR/bin/python" -m pip install -r "$SOURCE_REQUIREMENTS_ATS"
    printf '%s' "$REQ_HASH" > "$DEPS_HASH_FILE"
fi

"$RUNTIME_DIR/bin/python" -m compileall -q "$TARGET_DIR/cvapp" "$TARGET_DIR/cv_core.py"

cat > "$TARGET" <<EOF
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$SCRIPT_DIR/.cv-runtime/bin/python" "\$SCRIPT_DIR/cv_core.py" "\$@"
EOF

chmod +x "$TARGET"

printf 'Installed: %s\n' "$TARGET"
printf 'Ensure PATH contains: %s\n' "$TARGET_DIR"
