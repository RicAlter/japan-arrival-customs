# -*- coding: utf-8 -*-
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import openpyxl
from openpyxl import Workbook

from jpmaterial.batch import run_batch
from jpmaterial.input import read_input
from jpmaterial.models import OverallStatus, ProductQuery
from jpmaterial.output import OutputError, build_summary, write_excel, write_json
from tests.util import build_engine


def make_input(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["CartonNo.", "ProductCode(JANCode)", "商品名称", "规格", "DescriptionofGoods", "材质"])
    ws.append(["A01", "4571608537527", "测试商品", "通常版", "テスト フィギュア 通常版", ""])
    ws.append(["A01", "4571608537527", "测试商品", "通常版", "テスト フィギュア 通常版", ""])
    ws.append(["A02", "4571608537527", "测试商品", "通常版", "テスト フィギュア 通常版", ""])
    ws.append(["A03", "", "无JAN商品", "", "JANなし", ""])
    wb.save(path)


class OutputTests(unittest.TestCase):
    def test_batch_duplicate_jan_one_record(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            inp = tmp / "input.xlsx"
            out = tmp / "out.xlsx"
            make_input(inp)
            engine, policies, *_ = build_engine(tmp)
            rows = read_input(inp)
            batch = run_batch(engine, rows)
            self.assertEqual(len(batch.results), 1)
            self.assertEqual(len(batch.results[0].input_rows), 3)
            self.assertEqual(batch.summary["input_rows"], 4)
            self.assertEqual(batch.summary["missing_jan"], 1)
            self.assertEqual(batch.summary["duplicate_rows_reused"], 2)
            write_excel(out, batch.results, batch.summary, input_path=str(inp), mode="offline_no_network", missing_rows=batch.missing_rows)
            wb = openpyxl.load_workbook(out, data_only=True)
            self.assertIn("查询结果", wb.sheetnames)
            self.assertIn("无法查询", wb.sheetnames)
            self.assertEqual(wb["无法查询"].max_row, 2)
            ws = wb["查询结果"]
            headers = [c.value for c in ws[1]]
            self.assertIn("日文材质原文", headers)
            self.assertIn("中文材质参考", headers)
            self.assertEqual(ws.max_row, 2)
            self.assertEqual(ws.cell(row=2, column=2).value, "4571608537527")
            # 原表未被修改
            self.assertTrue(inp.exists())
            wb.close()

    def test_refuse_overwrite_input(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            inp = tmp / "input.xlsx"
            make_input(inp)
            engine, *_ = build_engine(tmp)
            rows = read_input(inp)
            batch = run_batch(engine, rows)
            with self.assertRaises(OutputError):
                write_excel(inp, batch.results, batch.summary, input_path=str(inp), mode="offline_no_network")

    def test_json_schema(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            inp = tmp / "input.xlsx"
            make_input(inp)
            engine, *_ = build_engine(tmp)
            rows = read_input(inp)
            batch = run_batch(engine, rows)
            out = tmp / "out.json"
            write_json(out, batch.results, batch.summary, mode="offline_no_network", input_path=str(inp))
            import json
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertIn("disclaimer", data)
            self.assertTrue(data["results"])
            self.assertIn("status", data["results"][0])
