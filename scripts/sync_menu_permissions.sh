#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

if [ ! -f "manage.py" ]; then
  echo "manage.py not found under $ROOT_DIR"
  exit 1
fi

./venv/bin/python manage.py check_permission_sync --apply
