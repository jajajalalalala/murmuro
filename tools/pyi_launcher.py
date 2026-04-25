"""PyInstaller entrypoint for the Murmur.app bundle.

PyInstaller turns whatever script you hand it into a top-level `__main__`,
which breaks relative imports inside our package. So instead of pointing
PyInstaller at `src/murmur/__main__.py`, we point it here — this file
imports the package the normal way and dispatches to `main()`.
"""
from __future__ import annotations

import sys

from murmur.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
