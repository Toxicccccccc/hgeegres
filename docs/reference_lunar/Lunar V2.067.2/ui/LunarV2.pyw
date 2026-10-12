"""Windowless launcher for the Lunar V2 UI.

Double-click this file (or run `pythonw LunarV2.pyw`) to start the UI without a
console window. The `.pyw` extension is associated with pythonw.exe by default,
so no command prompt is shown.
"""

import os
import sys

# Ensure imports resolve regardless of where this is launched from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == "__main__":
    main()
