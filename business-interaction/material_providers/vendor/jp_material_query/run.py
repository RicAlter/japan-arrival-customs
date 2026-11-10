# -*- coding: utf-8 -*-
"""便捷入口：python run.py ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jpmaterial.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
