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
    handlers = [logging.StreamHandler()]
    try:                                    # Protokolldatei für Fehlersuche (die exe hat keine Konsole)
        import os
        from logging.handlers import RotatingFileHandler
        log_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ProcessRecorder")
        os.makedirs(log_dir, exist_ok=True)
        handlers.append(RotatingFileHandler(os.path.join(log_dir, "log.txt"), maxBytes=512_000,
                                            backupCount=2, encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _enable_dpi_awareness()
    try:                                    # comtypes-Cache einmal im Hauptthread erzeugen; parallele
        import uiautomation  # noqa: F401   # Imports in den Worker-Threads scheitern sonst beim Erststart
    except Exception:
        pass
    from process_recorder.gui import App
    App().mainloop()


if __name__ == "__main__":
    main()
