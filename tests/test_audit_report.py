"""样例资料包的编校结论测试。"""
import json
import unittest

from pack_audit import audit_pack
from pack_audit.io_pack import load_pack
from pack_audit.analysis import build_claim_index, link_claims
from pack_audit.physical import build_surface_index
from pack_audit.reporting import render_markdown, to_json


class EditorialAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit_pack(today="2026-11-24")
        cls.pack = load_pack()
        cls.claims = build_claim_index(cls.pack["tables"])
        cls.surfaces = build_surface_index(cls.pack["tables"])
        cls.links = link_claims(cls.claims, cls.surfaces)

    def test_links_disconnected_and_translated_fragments(self):
        by_surface = {link["surface_id"]: link for link in self.links}
        self.assertIn("C2", [m["claim_id"] for m in by_surface["P1"]["claim_matches"]])
        self.assertIn("C2", [m["claim_id"] for m in by_surface["P2"]["claim_matches"]])
        self.assertIn("C2", [m["claim_id"] for m in by_surface["P5"]["claim_matches"]])
        self.assertIn("C3", [m["claim_id"] for m in by_surface["P3"]["claim_matches"]])
        self.assertIn("C4", [m["claim_id"] for m in by_surface["P4"]["claim_matches"]])
        self.assertIn("C1", by_surface["P1"]["source_claim_ids"])

    def test_reports_exact_source_translation_and_print_locations(self):
        findings = self.report["editorial"]["findings"]
        finding = next(f for f in findings if f["code"] == "EPHEMERAL_QUALIFIER")

        source = finding["source_locations"][0]
        translation = finding["translation_locations"][0]
        self.assertEqual((source["file"], source["row"], source["field"]), ("claims.tsv", 2, "text"))
        self.assertIn("仅甲系列支持 24 V", source["quote"])
        self.assertEqual((translation["file"], translation["row"]), ("claims.tsv", 3))
        self.assertIn("Compatible con 24 V", translation["quote"])

        roles = {loc.get("role"): loc for loc in finding["locations"]}
        self.assertEqual(roles["detached_compatibility"]["id"], "P1")
        self.assertEqual(roles["ephemeral_series_limit"]["id"], "P2")
        self.assertIn("start_coordinate", roles["detached_compatibility"])

    def test_sample_batch_decisions(self):
        batches = {b["id"]: b for b in self.report["planning"]["batches"]}

        d1 = batches["D1"]
        self.assertTrue(d1["executable"])
        self.assertEqual(d1["decision"], "quarantine_then_patch_release")
        self.assertEqual(d1["effective_assets"], ["P1", "P2", "P4"])
        self.assertEqual(d1["allocations"][0]["stock_id"], "I3")
        self.assertEqual(d1["allocations"][0]["qty"], 60)

        d2 = batches["D2"]
        self.assertEqual(d2["state"], "shipped")
        self.assertFalse(d2["executable"])
        self.assertTrue(d2["compliant_record"])
        self.assertEqual(d2["contact"]["market"], "南区")
        self.assertEqual([x["id"] for x in d2["held_text"]], ["P3"])

        d3 = batches["D3"]
        self.assertFalse(d3["executable"])
        self.assertEqual(d3["decision"], "channel_or_stock_blocked")
        self.assertIn("P3", d3["blocked_candidate"]["surface_ids"])
        self.assertTrue(d3["blocked_candidate"]["region_blocked"])

        d4 = batches["D4"]
        self.assertFalse(d4["executable"])
        self.assertEqual(d4["decision"], "reprint_required")
        self.assertIn("P4", d4["blocked_candidate"]["surface_ids"])
        self.assertEqual(
            d4["blocked_candidate"]["blockers"][0]["code"], "LOT_MISMATCH"
        )

    def test_stock_is_reserved_once(self):
        stock = {row["id"]: row for row in self.report["planning"]["stock"]}
        self.assertEqual(stock["I3"]["remaining_qty"], 0)
        total_reserved_i3 = sum(
            a["qty"]
            for a in self.report["planning"]["reservations"]
            if a["stock_id"] == "I3"
        )
        self.assertEqual(total_reserved_i3, 60)

    def test_markdown_and_json_report_render(self):
        markdown = render_markdown(self.report)
        self.assertIn("包装声明校勘与排产核对报告", markdown)
        self.assertIn("claims.tsv:2:", markdown)
        json.loads(to_json(self.report))


if __name__ == "__main__":
    unittest.main()
