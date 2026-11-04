"""Windowed frozen entry point with an isolated distribution diagnostic."""
import json
import os
from pathlib import Path
import sys
import traceback


def run():
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from macro_studio.diagnostics import self_test
        return self_test(Path(sys.argv[2]))
    try:
        # Hold the installer's mutex while the frozen UI is open.
        mutex = None
        if getattr(sys, 'frozen', False):
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
            kernel.CreateMutexW.restype = ctypes.c_void_p
            mutex = kernel.CreateMutexW(None, False, 'WindowsMacroStudio.Desktop')
        from macro_studio.app import main
        main()
        return 0
    except Exception:
        folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'WindowsMacroStudio' / 'Logs'
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / 'startup-error.log'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, 'Impossible de démarrer Macro Studio.\nDétail : ' + str(log), 'Windows Macro Studio', 0x10)
        return 1


if __name__ == '__main__':
    sys.exit(run())
