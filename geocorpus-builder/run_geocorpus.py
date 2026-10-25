"""GeoCorpus Builder — standalone launcher.

Double-click: web GUI at http://localhost:8501
Command line: GeoCorpusBuilder.exe init|build|query|...
"""

import sys
import os
import traceback
from pathlib import Path


def _pause():
    try:
        input("Press Enter to exit...")
    except Exception:
        pass


def _find_gui_py():
    if getattr(sys, 'frozen', False):
        meipass = Path(sys._MEIPASS)
        for sub in ["geocorpus_builder/gui.py", "gui.py"]:
            p = meipass / sub
            if p.exists():
                return p
        for f in meipass.glob("*/gui.py"):
            return f
        for f in meipass.glob("*/*/gui.py"):
            return f
        print("Bundle contents (top level):")
        for item in sorted(meipass.iterdir()):
            print(f"  {item.name}")
        return None
    else:
        p = Path(__file__).parent / "src" / "geocorpus_builder" / "gui.py"
        return p if p.exists() else None


def _start_gui():
    gui_py = None
    try:
        gui_py = _find_gui_py()
        if gui_py is None:
            print("ERROR: gui.py not found in bundle")
            print(f"sys._MEIPASS = {getattr(sys, '_MEIPASS', 'N/A')}")
            _pause()
            return

        print(f"GeoCorpus Builder GUI starting... (found: {gui_py})")
        print("Open http://localhost:8501 in your browser")
        print("Press Ctrl+C in this window to stop.")
        print()

        sys.argv = ["streamlit", "run", str(gui_py),
                    "--global.developmentMode=false",
                    "--server.headless=true"]
        from streamlit.web import cli as stcli
        stcli.main()
    except SystemExit:
        pass
    except Exception:
        traceback.print_exc()
        _pause()


def main():
    try:
        if getattr(sys, 'frozen', False):
            sys.path.insert(0, sys._MEIPASS)

        is_gui = len(sys.argv) <= 1 or sys.argv[1] in ("gui", "--gui")

        if is_gui:
            _start_gui()
        else:
            from geocorpus_builder.main import cli as _cli
            _cli(standalone_mode=False)
    except Exception:
        traceback.print_exc()
        _pause()


if __name__ == "__main__":
    main()
