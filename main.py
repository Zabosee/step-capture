"""Einstiegspunkt: python main.py"""
import ctypes
import logging
import sys


def _enable_dpi_awareness() -> None:
    """Muss vor Tk/pynput laufen, damit Klick- und Screenshot-Koordinaten übereinstimmen."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # Per-Monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _enable_dpi_awareness()
    from process_recorder.gui import App
    App().mainloop()


if __name__ == "__main__":
    main()
