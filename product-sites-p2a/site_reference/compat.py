"""Load the pinned P1 contract without importing the arrival engine."""
import sys
from pathlib import Path

P1 = Path(__file__).resolve().parents[2] / 'product-library-p1'
if not P1.is_dir():
    raise RuntimeError('缺少同一仓库的P1合同组件，拒绝猜测替代接口')
sys.path.insert(0, str(P1))

from product_reference.core import Rejected
from product_reference.sites import validate_response
from product_reference.query import normalize
