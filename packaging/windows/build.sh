#!/usr/bin/env bash
# Builds the Windows app (dist/TalkpodManager) and its setup program (dist/TalkpodManager-X.Y.Z-setup.exe).
# Runs in an MSYS2 UCRT64 shell from any folder; .github/workflows/windows.yml lists the packages it needs
# and runs it on GitHub's Windows machines. The setup program needs Inno Setup 6.
set -euo pipefail
cd "$(dirname "$0")/../.."
version=$(python -c 'import talkpod_manager; print(talkpod_manager.__version__)')

# CHIRP at the commit pyproject.toml pins (it isn't on PyPI); everything else comes from MSYS2.
chirp=$(python -c 'import tomllib; print(next(d for d in tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"] if d.startswith("chirp")))')
PIP_BREAK_SYSTEM_PACKAGES=1 python -m pip install -q --disable-pip-version-check "$chirp"

rm -rf dist/TalkpodManager
(cd packaging/windows && python -m PyInstaller --noconfirm --clean --log-level WARN \
    --distpath ../../dist --workpath ../../build/pyinstaller talkpod-manager.spec)

iscc="/c/Program Files (x86)/Inno Setup 6/ISCC.exe"
if [[ -x "$iscc" ]]; then
    # no MSYS2 path conversion: it would turn /DAppVersion into a file path
    MSYS2_ARG_CONV_EXCL='*' "$iscc" /Q "/DAppVersion=$version" "$(cygpath -w packaging/windows/setup.iss)"
    echo "built dist/TalkpodManager-$version-setup.exe"
else
    echo "Inno Setup isn't installed: built dist/TalkpodManager only" >&2
fi
