#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$SCRIPT_DIR/../package"

echo "Installing SPX Dealer Gamma plasmoid..."
kpackagetool6 --type Plasma/Applet --install "$PACKAGE_DIR"
echo "Done. Add the widget from the widget browser or run:"
echo "  plasmawindowed com.chrisotm.spxgamma"
