#!/usr/bin/env bash
# Linux / macOS: bash setup.sh, затем bash run.sh
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt
echo "Готово. Запускай: bash run.sh"
