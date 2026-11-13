"""Isolated candidate orchestration over accepted A stages, B00/A04 and rc.5."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent
sys.path.insert(0,str(REPO/'a-stage-purchase-sidecars'))
__version__='0.2.0-business-loop-candidate'
