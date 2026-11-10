"""Source and windowed frozen entry; never prints exceptions or arguments."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from relay_auditor.desktop import main


if __name__ == '__main__':
    raise SystemExit(main())
