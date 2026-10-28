#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Сначала: bash setup.sh"; exit 1; }
exec .venv/bin/python app.py
