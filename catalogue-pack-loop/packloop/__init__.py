from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent
sys.path.insert(0,str(REPO/'business-loop'))
__version__='0.3.0-catalogue-pack-candidate'
