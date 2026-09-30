"""Start Django + its local observability dependency using the current Python env."""
import os
from pathlib import Path
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.execv(sys.executable, [sys.executable, str(root / "manage.py"), "runserver", *sys.argv[1:]])
