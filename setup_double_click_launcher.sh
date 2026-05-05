#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_MAIN="$APP_DIR/smb_manager_ui.py"

if [[ ! -f "$APP_MAIN" ]]; then
  echo "Error: smb_manager_ui.py not found in $APP_DIR"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is not installed"
  exit 1
fi

LAUNCHER_DIR="$HOME/.local/bin"
LAUNCHER_PATH="$LAUNCHER_DIR/smb-manager-ui"
mkdir -p "$LAUNCHER_DIR"

cat > "$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$APP_DIR"
exec python3 "$APP_MAIN"
EOF
chmod +x "$LAUNCHER_PATH"

APP_DIR_ESCAPED="${APP_DIR// /\\ }"

DESKTOP_ENTRY_DIR="$HOME/.local/share/applications"
DESKTOP_ENTRY_PATH="$DESKTOP_ENTRY_DIR/smb-manager-ui.desktop"
mkdir -p "$DESKTOP_ENTRY_DIR"

cat > "$DESKTOP_ENTRY_PATH" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Samba Management Suite
Comment=Manage Samba shares with a GUI
Exec=$LAUNCHER_PATH
Path=$APP_DIR_ESCAPED
Terminal=false
Categories=Network;System;
StartupNotify=true
EOF
chmod +x "$DESKTOP_ENTRY_PATH"

DESKTOP_DIR=""
if command -v xdg-user-dir >/dev/null 2>&1; then
  DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
fi
if [[ -z "$DESKTOP_DIR" ]]; then
  DESKTOP_DIR="$HOME/Desktop"
fi

if [[ -d "$DESKTOP_DIR" ]]; then
  cp "$DESKTOP_ENTRY_PATH" "$DESKTOP_DIR/Samba Management Suite.desktop"
  chmod +x "$DESKTOP_DIR/Samba Management Suite.desktop"
  echo "Desktop shortcut created at: $DESKTOP_DIR/Samba Management Suite.desktop"
else
  echo "Desktop folder not found; app menu entry still created at: $DESKTOP_ENTRY_PATH"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOP_ENTRY_DIR" >/dev/null 2>&1 || true
fi

echo "Launcher installed."
echo "Run from app menu: Samba Management Suite"
echo "Or run command: smb-manager-ui"
