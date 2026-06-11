#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$SCRIPT_DIR/../package"

echo "Upgrading SPX Dealer Gamma plasmoid..."
kpackagetool6 --type Plasma/Applet --upgrade "$PACKAGE_DIR"
echo "Done."
