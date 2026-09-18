#!/usr/bin/env sh
set -eu

python -m pip install -e ".[desktop,build]"
python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name CyberAwareness \
  --collect-data app \
  --collect-all webview \
  app/desktop.py

cp .env.example dist/CyberAwareness/.env.example
echo "Desktop app created in dist/CyberAwareness/"
