#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$SCRIPT_DIR/../package"
PLUGIN_ID="com.chrisotm.spxgamma"

echo "Reloading plasmoid for development..."

# Install if absent, upgrade if present
if kpackagetool6 --type Plasma/Applet --list 2>/dev/null | grep -q "$PLUGIN_ID"; then
    kpackagetool6 --type Plasma/Applet --upgrade "$PACKAGE_DIR"
else
    kpackagetool6 --type Plasma/Applet --install "$PACKAGE_DIR"
fi

# plasmoidviewer is the dev tool of choice; fall back to plasmawindowed.
if command -v plasmoidviewer >/dev/null 2>&1; then
    echo "Launching plasmoidviewer..."
    exec plasmoidviewer -a "$PACKAGE_DIR" -l floating -f planar
elif command -v plasmawindowed >/dev/null 2>&1; then
    echo "plasmoidviewer not found; launching plasmawindowed..."
    exec plasmawindowed "$PLUGIN_ID"
else
    echo "Neither plasmoidviewer nor plasmawindowed found."
    echo "Add the widget manually from the Plasma widget browser."
fi
