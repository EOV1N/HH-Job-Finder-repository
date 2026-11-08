#!/usr/bin/env python3
"""Запуск: python run.py [--data-dir PATH] [--no-auto] [--screenshots DIR]."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# config.py вычисляет пути при импорте, поэтому --data-dir обрабатывается заранее.
argv = sys.argv[1:]
for i, arg in enumerate(argv):
    if arg == "--data-dir" and i + 1 < len(argv):
        os.environ["HHF_DATA_DIR"] = str(Path(argv[i + 1]).expanduser().resolve())
    elif arg.startswith("--data-dir="):
        os.environ["HHF_DATA_DIR"] = str(Path(arg.split("=", 1)[1]).expanduser().resolve())

from hhfinder.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
