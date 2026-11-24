"""新稿件、数量变化和库存争用的重复判断测试。"""
import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from pack_audit import audit_pack
from pack_audit.materials import DEFAULT_DATA


class ReimportScenarioTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "materials"
        shutil.copytree(DEFAULT_DATA, self.directory)

    def tearDown(self):
        self.temporary.cleanup()

    def _set_stock_qty(self, stock_id: str, qty: int):
        path = self.directory / "stock.tsv"
        with path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source, delimiter="\t"))
            fieldnames = source and None
        for row in rows:
            if row["id"] == stock_id:
                row["qty"] = str(qty)
        with path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=list(rows[0].keys()), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

    def _set_surface_text(self, surface_id: str, text: str):
        path = self.directory / "print_surfaces.tsv"
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, delimiter="\t")
            fieldnames = reader.fieldnames
            rows = list(reader)
        for row in rows:
            if row["id"] == surface_id:
                row["text"] = text
        with path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

    def _append_dispatch(self, row: dict[str, str]):
        path = self.directory / "dispatch.tsv"
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, delimiter="\t")
            fieldnames = reader.fieldnames
            rows = list(reader)
        rows.append(row)
        with path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

    def test_half_patch_stock_changes_full_execution(self):
        self._set_stock_qty("I3", 30)
        report = audit_pack(self.directory, today="2026-11-24")
        d1 = next(b for b in report["planning"]["batches"] if b["id"] == "D1")
        self.assertFalse(d1["executable"])
        self.assertEqual(d1["decision"], "partial_patch_and_reprint")
        self.assertEqual(d1["covered_qty"], 30)
        self.assertEqual(d1["short_qty"], 30)
        self.assertEqual(d1["allocations"][0]["qty"], 30)

    def test_zero_patch_stock_means_reprint(self):
        self._set_stock_qty("I3", 0)
        report = audit_pack(self.directory, today="2026-11-24")
        d1 = next(b for b in report["planning"]["batches"] if b["id"] == "D1")
        self.assertFalse(d1["executable"])
        self.assertEqual(d1["decision"], "stock_shortage_reprint")
        self.assertEqual(d1["covered_qty"], 0)
        self.assertEqual(d1["short_qty"], 60)

    def test_promised_order_reserves_contested_stock_before_unpromised(self):
        self._set_stock_qty("I3", 70)
        self._append_dispatch(
            {
                "id": "D5",
                "product": "甲",
                "lot": "V8",
                "market": "南区",
                "qty": "20",
                "promised": "",
                "stage": "待排",
                "assets": "",
            }
        )
        report = audit_pack(self.directory, today="2026-11-24")
        batches = {b["id"]: b for b in report["planning"]["batches"]}

        self.assertTrue(batches["D1"]["executable"])
        d5 = batches["D5"]
        self.assertFalse(d5["executable"])
        self.assertEqual(d5["covered_qty"], 10)
        self.assertEqual(d5["short_qty"], 10)

        i3_reservations = [a for a in report["planning"]["reservations"] if a["stock_id"] == "I3"]
        self.assertEqual(sum(a["qty"] for a in i3_reservations), 70)
        by_batch = {a["batch_id"]: a["qty"] for a in i3_reservations}
        self.assertEqual(by_batch, {"D1": 60, "D5": 10})

    def test_changed_artwork_relot_moves_usability_to_new_batch(self):
        self._set_surface_text("P4", "Solo 12 V. Serie A, lote V9.")
        report = audit_pack(self.directory, today="2026-11-24")
        batches = {b["id"]: b for b in report["planning"]["batches"]}

        self.assertFalse(batches["D1"]["executable"])
        self.assertEqual(batches["D1"]["blocked_candidate"]["blockers"][0]["code"], "LOT_MISMATCH")
        self.assertTrue(batches["D4"]["executable"])
        p4_allocation = next(a for a in batches["D4"]["allocations"] if a["surface_id"] == "P4")
        self.assertEqual(p4_allocation["qty"], 40)

    def test_other_market_cannot_use_region_locked_sticker(self):
        self._append_dispatch(
            {
                "id": "D6",
                "product": "乙",
                "lot": "W9",
                "market": "北区",
                "qty": "5",
                "promised": "2026-11-30",
                "stage": "待排",
                "assets": "",
            }
        )
        report = audit_pack(self.directory, today="2026-11-24")
        d6 = next(b for b in report["planning"]["batches"] if b["id"] == "D6")
        self.assertFalse(d6["executable"])
        self.assertEqual(d6["decision"], "channel_or_stock_blocked")
        self.assertEqual(d6["blocked_candidate"]["surface_ids"], ["P1", "P3"])


if __name__ == "__main__":
    unittest.main()
