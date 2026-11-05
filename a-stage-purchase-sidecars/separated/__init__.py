"""Main workbook without purchasing helper columns; separate query snapshots."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent
sys.path.insert(0,str(REPO/'a-stage-first-phase'))
__version__='0.1.1-purchase-sidecars'
