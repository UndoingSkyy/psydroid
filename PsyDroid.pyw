import ctypes
import traceback

from psydroid import paths

try:
    from psydroid.ui.app import main
    main()
except Exception:
    paths.DATA.mkdir(parents=True, exist_ok=True)
    paths.CRASH_LOG.write_text(traceback.format_exc())
    ctypes.windll.user32.MessageBoxW(None, f"PsyDroid crashed. Details are in {paths.CRASH_LOG}", "PsyDroid", 0x10)
