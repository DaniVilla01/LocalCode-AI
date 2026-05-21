#!/usr/bin/env bash
set -euo pipefail

# Construye un binario local para Linux/macOS usando PyInstaller.
# Nota: en Linux genera binario Linux; en macOS genera binario macOS.
# Para .exe de Windows, ejecuta build_windows.bat en Windows.

cd "$(dirname "$0")"

python3 -m pip install -r requirements-build.txt
python3 -m PyInstaller --clean --noconfirm local-code-agent.spec

echo
echo "Binario generado en:"
echo "  $(pwd)/dist/local-code-agent"
echo
echo "Ejemplo:"
echo "  ./dist/local-code-agent --root /ruta/a/tu/proyecto --model qwen2.5-coder:7b"
