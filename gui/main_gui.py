# gui/main_gui.py
"""
Entry point script for the DAQ_CA GUI client.

Running this module launches the Qt based control panel defined in
`gui/main_window.py`.  It is deliberately lightweight – the heavy lifting
is performed inside `gui/main_window.py`.
"""

import sys
from pathlib import Path

# Ensure the repository root is on the Python path when the script is
# executed directly (e.g. `python gui/main_gui.py`).  This allows the
# import of the local `gui` package without installing the project.
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from gui.main_window import main

if __name__ == "__main__":
    main()
