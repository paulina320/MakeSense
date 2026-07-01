#!/usr/bin/env bash
set -euo pipefail

HOST_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$HOST_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "Virtual environment not found at $PYTHON." >&2
    echo "Create it and install requirements first." >&2
    exit 1
fi

if ! "$PYTHON" -m pip show pyinstaller >/dev/null 2>&1; then
    echo "PyInstaller is not installed." >&2
    echo "Run: .venv/bin/python -m pip install -r requirements-build.txt" >&2
    exit 1
fi

cd "$HOST_ROOT"
"$PYTHON" -m PyInstaller --noconfirm --clean makesense.spec

echo
echo "Build complete: dist/MakeSense/MakeSense"
