#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v python3 >/dev/null || ! command -v iverilog >/dev/null; then
  echo "One-time setup required. Run in Terminal: brew install python icarus-verilog"
  read -r -p "Press Enter to close..."
  exit 1
fi
python3 server.py
