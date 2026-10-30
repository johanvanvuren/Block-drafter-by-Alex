#!/usr/bin/env bash

# ==============================================================================
# Block Drafter by Alex — macOS 1-Click Desktop Launcher
# ==============================================================================

# Move to the folder where this script lives
cd "$(dirname "$0")" || exit 1

echo "====================================================="
echo "   Block Drafter by Alex — Launching on macOS        "
echo "====================================================="

# 1. Check if Python 3 is installed
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "❌ Error: Python 3 was not found on this Mac."
    echo ""
    echo "Please download and install Python 3 (free) from:"
    echo "👉 https://www.python.org/downloads/macos/"
    echo ""
    echo "After installing Python, run this file again."
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

echo "✓ Python detected: $(python3 --version)"

# 2. Create isolated virtual environment if it doesn't exist yet
if [ ! -d ".venv_mac" ]; then
    echo "Setting up isolated virtual environment (.venv_mac)..."
    python3 -m venv .venv_mac
fi

# 3. Activate environment
source .venv_mac/bin/activate

# 4. Check and install dependencies automatically
echo "Verifying graphics and drafting dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 5. Launch the application GUI
echo "Starting Block Drafter..."
python3 main.py

# Keep terminal open if app exits with an error
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "Application exited with code $EXIT_CODE."
    read -n 1 -s -r -p "Press any key to close..."
fi
