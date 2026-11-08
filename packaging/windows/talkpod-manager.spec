# PyInstaller spec for the Windows build. build.sh runs it in MSYS2 UCRT64.
# The gi hooks collect GTK 4 and libadwaita with their typelibs, the Adwaita icons and the GSettings schemas.
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
sys.path.insert(0, ROOT)                                # the app runs from the checkout, not installed

a = Analysis(
    [os.path.join(SPECPATH, "talkpod-manager.py")],
    pathex=[ROOT],
    datas=collect_data_files("talkpod_manager"),        # the icon and the bundled firmware
    hooksconfig={
        "gi": {
            "module-versions": {"Gtk": "4.0", "Gdk": "4.0", "Gsk": "4.0", "Adw": "1"},
            "icons": ["Adwaita", "hicolor"],
            "themes": [],
            "languages": ["en_US", "en_GB", "en_AU"],
        },
    },
    excludes=["tkinter", "pytest", "PyQt5", "PyQt6", "wx"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TalkpodManager",
    icon=os.path.join(SPECPATH, "talkpod-manager.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TalkpodManager", upx=False)
