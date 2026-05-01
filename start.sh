#!/usr/bin/env bash
# Murmuro setup + run script.
# - Installs uv if missing
# - Pins Python via .python-version
# - Creates an isolated venv
# - Installs the project + GUI extras
# - Launches Murmuro
#
# Usage:
#   ./start.sh                  # set up (if needed) and launch GUI
#   ./start.sh --cli            # set up (if needed) and launch CLI mode
#   ./start.sh --setup-only     # only install + sync, don't launch
#   ./start.sh --reset          # wipe .venv and reinstall from scratch

set -euo pipefail

cd "$(dirname "$0")"

LAUNCH_MODE="gui"
SETUP_ONLY=0
RESET=0

for arg in "$@"; do
    case "$arg" in
        --cli) LAUNCH_MODE="cli" ;;
        --setup-only) SETUP_ONLY=1 ;;
        --reset) RESET=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

# 1. Install uv if missing.
if ! command -v uv >/dev/null 2>&1; then
    echo "[start.sh] uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # uv installs to ~/.local/bin; make sure it's on PATH for this shell.
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "[start.sh] uv: $(uv --version)"

# 2. Reset venv if requested.
if [[ $RESET -eq 1 ]]; then
    echo "[start.sh] --reset: removing .venv"
    rm -rf .venv
fi

# 3. Ensure pinned Python is installed.
PINNED_PYTHON="$(cat .python-version 2>/dev/null || echo 3.11)"
echo "[start.sh] target Python: $PINNED_PYTHON"
uv python install "$PINNED_PYTHON" >/dev/null

# 4. Create venv (and recreate it if it was made with the wrong Python version).
#    Bug history: an earlier .venv created from system Python (e.g. 3.9.6) was
#    silently reused by uv pip, then dependency resolution failed with
#    "Python>=3.10" violations. Always verify the existing venv matches.
need_create=0
if [[ ! -d .venv ]]; then
    need_create=1
elif [[ ! -x .venv/bin/python ]]; then
    echo "[start.sh] .venv exists but has no python binary — recreating"
    rm -rf .venv
    need_create=1
else
    current_ver="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "unknown")"
    if [[ "$current_ver" != "$PINNED_PYTHON" ]]; then
        echo "[start.sh] existing .venv has Python $current_ver, pinned is $PINNED_PYTHON — recreating"
        rm -rf .venv
        need_create=1
    fi
fi

if [[ $need_create -eq 1 ]]; then
    echo "[start.sh] creating .venv with Python $PINNED_PYTHON"
    uv venv --python "$PINNED_PYTHON"
fi

# 5. Install project + GUI extras (idempotent). We pass --python explicitly so
#    uv ignores any ambient VIRTUAL_ENV / system Python and installs into our venv.
echo "[start.sh] installing project + GUI deps (this may take a few minutes the first time)..."
uv pip install --python .venv/bin/python -e ".[gui]"

# Optional: also install the openai extra if user has set OPENAI_API_KEY
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    echo "[start.sh] OPENAI_API_KEY detected — installing [openai] extra"
    uv pip install --python .venv/bin/python -e ".[openai]"
fi

if [[ $SETUP_ONLY -eq 1 ]]; then
    echo "[start.sh] setup complete. Run ./start.sh to launch."
    exit 0
fi

# 6. Launch.
if [[ "$LAUNCH_MODE" == "cli" ]]; then
    echo "[start.sh] launching CLI mode..."
    exec .venv/bin/murmuro --cli
else
    echo "[start.sh] launching GUI..."
    exec .venv/bin/murmuro
fi
