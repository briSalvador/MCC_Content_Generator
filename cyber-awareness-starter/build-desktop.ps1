$ErrorActionPreference = "Stop"

python -m pip install -e ".[desktop,build]"
python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name CyberAwareness `
  --collect-data app `
  --collect-all webview `
  app/desktop.py

Copy-Item .env.example dist/CyberAwareness/.env.example -Force
Write-Host "Desktop app created in dist/CyberAwareness/"
