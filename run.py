import subprocess
import sys
import time
from pathlib import Path

WATCH_FILES = [
    "main.py",
    "config.py",
    "shared.py",
    "telegram_handlers.py",
    "x_handlers.py",
    "facebook_handlers.py",
]


def get_mtimes():
    return {f: Path(f).stat().st_mtime for f in WATCH_FILES if Path(f).exists()}


def main():
    while True:
        print("\n=== Uruchamiam main.py ===\n")
        proc = subprocess.Popen([sys.executable, "main.py"])
        mtimes = get_mtimes()

        try:
            while proc.poll() is None:
                time.sleep(1)
                new_mtimes = get_mtimes()
                if new_mtimes != mtimes:
                    changed = [f for f in WATCH_FILES if new_mtimes.get(f) != mtimes.get(f)]
                    print(f"\n=== Zmiana w: {', '.join(changed)} — restartuję ===\n")
                    proc.terminate()
                    proc.wait(timeout=5)
                    break
            else:
                code = proc.returncode
                if code != 0:
                    print(f"\n=== Crash (kod {code}), restartuję za 3s ===\n")
                    time.sleep(3)
                else:
                    break
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
            break


if __name__ == "__main__":
    main()
