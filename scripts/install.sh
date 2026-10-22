#!/usr/bin/env bash
# Installs Talkpod Manager for the current user: a Python venv in ~/.local/share/talkpod-manager,
# a launcher in ~/.local/bin, the desktop entry and the icon. No root needed except for missing
# system packages (GTK4 / libadwaita bindings), which it installs with apt.
#
#   From a checkout:  scripts/install.sh            installs that checkout
#   Anywhere:         curl -fsSL https://raw.githubusercontent.com/ssjrocks/talkpod-manager/main/scripts/install.sh | bash
#   Remove:           scripts/install.sh --uninstall  (keeps your backups in ~/Documents/Talkpod Manager)
set -euo pipefail

APP_ID=io.github.ssjrocks.TalkpodManager
REPO=ssjrocks/talkpod-manager
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
ROOT="$DATA/talkpod-manager"
VENV="$ROOT/venv"
BIN="$HOME/.local/bin"
DESKTOP="$DATA/applications/$APP_ID.desktop"
ICON="$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$ROOT"
  rm -f "$BIN/talkpod-manager" "$BIN/talkpod-firmware" "$DESKTOP" "$ICON"
  update-desktop-database -q "$DATA/applications" 2>/dev/null || true
  echo "Talkpod Manager removed (backups in ~/Documents/Talkpod Manager were kept)."
  exit 0
fi

need=()
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null \
  || need+=(python3-gi gir1.2-gtk-4.0 gir1.2-adw-1)
python3 -c 'import venv, ensurepip' 2>/dev/null || need+=(python3-venv)
command -v git >/dev/null || need+=(git)
if ((${#need[@]})); then
  echo "Installing system packages: ${need[*]}"
  sudo apt-get install -y "${need[@]}"
fi

# Install from this checkout when run from one, otherwise from the latest GitHub release.
src=""
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [[ -f "$here/../pyproject.toml" ]] && src="$(cd "$here/.." && pwd)"
fi

python3 -m venv --system-site-packages "$VENV"
touch "$VENV/talkpod-manager-venv"   # tells the in-app updater it may update this venv
"$VENV/bin/pip" install -q --upgrade pip

if [[ -n "$src" ]]; then
  echo "Installing from $src"
  "$VENV/bin/pip" install -q "$src"
else
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  read -r wheel_url sha < <(python3 - "$REPO" <<'EOF'
import json, sys, urllib.request
repo = sys.argv[1]
rel = json.load(urllib.request.urlopen(f"https://api.github.com/repos/{repo}/releases/latest"))
assets = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
info = json.load(urllib.request.urlopen(assets["talkpod-manager.json"]))
print(assets[info["wheel"]], info["sha256"])
EOF
)
  echo "Downloading $wheel_url"
  curl -fsSL -o "$tmp/$(basename "$wheel_url")" "$wheel_url"
  echo "$sha  $tmp/$(basename "$wheel_url")" | sha256sum -c --quiet
  "$VENV/bin/pip" install -q "$tmp/$(basename "$wheel_url")"
fi

mkdir -p "$BIN" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
cat > "$BIN/talkpod-manager" <<EOF
#!/bin/sh
exec "$VENV/bin/python" -m talkpod_manager "\$@"
EOF
chmod +x "$BIN/talkpod-manager"
printf '#!/bin/sh\nexec "%s/bin/python" -m talkpod_manager.firmware "$@"\n' "$VENV" > "$BIN/talkpod-firmware"
chmod +x "$BIN/talkpod-firmware"
pkg=$("$VENV/bin/python" -c 'import talkpod_manager, os; print(os.path.dirname(talkpod_manager.__file__))')
sed "s|^Exec=.*|Exec=$BIN/talkpod-manager %F|" "$pkg/data/$APP_ID.desktop" > "$DESKTOP"
cp "$pkg/data/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICON"
update-desktop-database -q "$DATA/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true

version=$("$VENV/bin/python" -c 'import talkpod_manager; print(talkpod_manager.__version__)')
echo "Installed Talkpod Manager $version. Start it from the app grid or run: talkpod-manager"
if ! id -nG | grep -qw dialout; then
  echo
  echo "To use the programming cable, add yourself to the dialout group, then log out and back in:"
  echo "  sudo usermod -aG dialout \$USER"
fi
