"""规则抽取和物理叠贴测试。"""
import unittest

from pack_audit.physical import build_surface_index, visible_surface_ids
from pack_audit.textfacts import extract_statement


class TextFactsTest(unittest.TestCase):
    def test_extracts_chinese_split_claims(self):
        statement = extract_statement("仅甲系列支持 24 V 适配器，需另购。乙系列仅可用 12 V。")
        keys = set(statement["atom_keys"])
        self.assertIn("series_gate:A", keys)
        self.assertIn("voltage_permission:24V", keys)
        self.assertIn("commercial_condition:adapter_not_included_or_separate", keys)
        self.assertIn("series_scope:B", keys)
        self.assertIn("voltage_only:12V", keys)

    def test_extracts_spanish_fragments(self):
        p2 = extract_statement("Solo serie A")
        self.assertIn("series_gate:A", p2["atom_keys"])

        p4 = extract_statement("Solo 12 V. Serie A, lote V8.")
        self.assertIn("voltage_only:12V", p4["atom_keys"])
        self.assertIn("series_scope:A", p4["atom_keys"])
        self.assertIn("lot_scope:V8", p4["atom_keys"])

        p5 = extract_statement("Adaptador no incluido")
        self.assertIn("commercial_condition:adapter_not_included_or_separate", p5["atom_keys"])

    def test_withdrawal_separates_old_and_transition_voltage(self):
        statement = extract_statement(
            "甲 24 V 声明撤回，甲批 V8 可按包装更新后的 12 V 文字销售。"
        )
        withdrawal = statement["withdrawals"][0]
        self.assertEqual(withdrawal["target_voltages"], ["24V"])
        self.assertEqual(withdrawal["target_series"], "A")
        self.assertEqual(withdrawal["allowed_voltages"], ["12V"])
        self.assertEqual(withdrawal["transition_lots"], ["V8"])


class PhysicalCollationTest(unittest.TestCase):
    def test_hides_covered_base_text(self):
        from pack_audit.api import audit_pack

        report = audit_pack(today="2026-11-24")
        # 直接从默认资料构造索引。
        from pack_audit.io_pack import load_pack

        pack = load_pack()
        surfaces = build_surface_index(pack["tables"])
        self.assertEqual(visible_surface_ids(["P1", "P3"], surfaces), ["P3"])
        self.assertEqual(visible_surface_ids(["P1", "P2", "P4"], surfaces), ["P2", "P4"])

        d2 = next(b for b in report["planning"]["batches"] if b["id"] == "D2")
        text_ids = [item["id"] for item in d2["held_text"]]
        self.assertEqual(text_ids, ["P3"])


if __name__ == "__main__":
    unittest.main()
