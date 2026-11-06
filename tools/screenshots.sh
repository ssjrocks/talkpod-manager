#!/usr/bin/env bash
# Renders the README's screenshots into docs/screenshots: the test image, as read from a radio with
# the bundled Talkpod Super Firmware, and the sample pictures in tools/screenshot-data.
#
# Usage: tools/screenshots.sh
set -euo pipefail
cd "$(dirname "$0")/.."
version=$(.venv/bin/python -c 'from talkpod_manager.firmware_catalog import TSF; print(TSF.version)')
out=build/screenshots
mkdir -p "$out"
GDK_BACKEND=x11 xvfb-run -a -s "-screen 0 1400x1800x24" .venv/bin/python tools/screenshot.py \
    tests/data/a36se-fw126-uhf-cb.img "$out" tools/screenshot-data/logo.png tools/screenshot-data/splash.gif "$version" \
    | grep -v "^saved" || true
for pair in "1-channels channels" "2-edit-channel edit-channel" "3-settings settings" "4-logo boot-logo" \
            "4-splash boot-splash" "5-plan channel-plan" "7-firmware flash-firmware" "8-eventlog event-log"; do
    set -- $pair
    cp "$out/$1.png" "docs/screenshots/$2.png"
done
echo "docs/screenshots: Talkpod Super Firmware $version"
