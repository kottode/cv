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

have_noto_sans_font() {
    if ! command -v fc-list >/dev/null 2>&1; then
        return 1
    fi
    local font_families
    font_families="$(fc-list : family 2>/dev/null || true)"
    [[ "$font_families" == *"Noto Sans"* ]]
}

ensure_pdf_deps() {
    HAVE_XCOLOR=0
    HAVE_LUALATEX=0
    HAVE_NOTO_FONT=0

    if command -v lualatex >/dev/null 2>&1; then
        HAVE_LUALATEX=1
    fi

    if command -v kpsewhich >/dev/null 2>&1; then
        if kpsewhich xcolor.sty >/dev/null 2>&1; then
            HAVE_XCOLOR=1
        fi
    fi

    if have_noto_sans_font; then
        HAVE_NOTO_FONT=1
    fi

    if [ "$HAVE_XCOLOR" -eq 1 ] \
        && [ "$HAVE_LUALATEX" -eq 1 ] \
        && [ "$HAVE_NOTO_FONT" -eq 1 ]; then
        return 0
    fi

    printf 'Installing PDF dependencies (lualatex, LaTeX styles, and Noto fonts)...\n'

    if [ "$(uname -s)" != "Linux" ]; then
        printf 'Error: lualatex missing. Install TeX (lualatex) and re-run install.sh.\n' >&2
        exit 1
    fi

    SUDO_BIN="sudo"
    if command -v sudo >/dev/null 2>&1; then
        if sudo -n true >/dev/null 2>&1; then
            SUDO_BIN="sudo -n"
        fi
    else
        printf 'Error: sudo required to install TeX packages.\n' >&2
        exit 1
    fi

    if command -v apt-get >/dev/null 2>&1; then
        $SUDO_BIN apt-get install -y texlive-latex-base texlive-latex-recommended texlive-luatex fonts-noto-core
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO_BIN dnf install -y texlive texlive-collection-latexrecommended texlive-noto noto-sans-fonts
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO_BIN pacman -Sy --noconfirm texlive-basic texlive-latexextra noto-fonts
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO_BIN zypper --non-interactive install texlive-latex texlive-xcolor texlive-noto google-noto-sans-fonts
    else
        printf 'Error: unsupported package manager. Install lualatex manually and re-run install.sh.\n' >&2
        exit 1
    fi

    if ! command -v lualatex >/dev/null 2>&1; then
        printf 'Error: lualatex installation failed. Install LuaTeX packages and re-run install.sh.\n' >&2
        exit 1
    fi

    if command -v kpsewhich >/dev/null 2>&1; then
        if ! kpsewhich xcolor.sty >/dev/null 2>&1; then
            printf 'Error: xcolor.sty missing after TeX install. Install LaTeX recommended packages and re-run install.sh.\n' >&2
            exit 1
        fi
    fi

    if command -v fc-list >/dev/null 2>&1; then
        if ! have_noto_sans_font; then
            fc-cache -f >/dev/null 2>&1 || true
        fi
        if ! have_noto_sans_font; then
            printf 'Error: Noto Sans font missing after install. Install system Noto Sans fonts and re-run install.sh.\n' >&2
            exit 1
        fi
    else
        printf 'Warning: fc-list not found, could not verify Noto Sans system font.\n' >&2
    fi

}

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
ensure_pdf_deps
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
