#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ID="com.chrisotm.spxgamma"

echo "Removing SPX Dealer Gamma plasmoid..."
kpackagetool6 --type Plasma/Applet --remove "$PLUGIN_ID"
echo "Done."
