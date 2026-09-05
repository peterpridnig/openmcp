#!/usr/bin/env bash
# Recreate the local virtualenv (.venv) and install requirements.txt into it.
# Usage: ./setup.sh [--force]   (--force removes an existing .venv first)
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
REQS="requirements.txt"

case "${1:-}" in
    -f|--force)
        echo "Removing existing $VENV"
        rm -rf "$VENV"
        ;;
    "")
        ;;
    *)
        echo "Usage: $0 [--force]" >&2
        exit 2
        ;;
esac

if [[ ! -f "$REQS" ]]; then
    echo "ERROR: $REQS not found next to setup.sh" >&2
    exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
    echo "Creating virtualenv in $VENV"
    python3 -m venv "$VENV"
fi

echo "Installing requirements into $VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$REQS"

"$VENV/bin/python" - <<'EOF'
import importlib.metadata

print("OK: mcp", importlib.metadata.version("mcp"), "importable")
EOF

echo "Done. Activate with: source $VENV/bin/activate"