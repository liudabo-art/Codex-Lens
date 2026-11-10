"""Standalone subproject entry: never imports the parent launch/runtime paths."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from relay_auditor.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
