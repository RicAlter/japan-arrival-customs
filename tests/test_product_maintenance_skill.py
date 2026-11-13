import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workbuddy" / "japan-arrival-customs" / "scripts"))

from arrival_core.product_library import ProductLibrary


class ProductMaintenanceSkillTests(unittest.TestCase):
    def test_maintenance_skill_is_the_shared_database_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            database = directory / "product-library.sqlite3"
            library = ProductLibrary.create(database)
            queue = {"kind": "product_maintenance_queue", "queue_id": "queue-test",
                     "library": {"path": str(database.resolve()), "sha256": hashlib.sha256(database.read_bytes()).hexdigest()},
                     "records": [{"sheet": "queue", "row": 1, "code": "4900000000001", "japanese_name": "テスト商品",
                                  "version": "通常版", "internal_name": "测试中文名", "customs_name": "测试申报品名",
                                  "category": "玩具", "channel": "", "yd": "", "packaging_label": ""}],
                     "confirmation": {"kind": "product_maintenance_queue", "queue_id": "queue-test", "reference": "test"}}
            queue_path = directory / "queue.json"; queue_path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
            runner = ROOT / "workbuddy" / "japan-arrival-product-library" / "scripts" / "run.py"
            result = subprocess.run([sys.executable, str(runner), "--library", str(database), "apply-queue", "--file", str(queue_path)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(library.lookup("4900000000001", japanese_name="テスト商品", version="通常版")["candidates"]["internal_name"], "测试中文名")


if __name__ == "__main__":
    unittest.main()
