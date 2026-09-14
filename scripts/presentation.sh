#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv-linux/bin/python" ]; then PY="$ROOT/.venv-linux/bin/python"
else PY=python3; fi
exec "$PY" "$ROOT/scripts/presentation.py" "$@"
