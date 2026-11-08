"""The Windows build's entry point (PyInstaller freezes this)."""

import sys

from talkpod_manager.app import main

sys.exit(main())
