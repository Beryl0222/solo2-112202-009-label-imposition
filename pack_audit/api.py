"""对外的资料包审计入口。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .analysis import build_claim_index, build_editorial_findings, link_claims
from .io_pack import load_pack
from .physical import build_surface_index
from .planning import plan_batches
from .materials import DEFAULT_DATA


def audit_pack(
    directory: Path | str = DEFAULT_DATA,
    today: date | str | None = None,
) -> dict[str, Any]:
    directory = Path(directory)
    if isinstance(today, str):
        today = date.fromisoformat(today)

    pack = load_pack(directory)
    claims = build_claim_index(pack["tables"])
    surfaces = build_surface_index(pack["tables"])
    links = link_claims(claims, surfaces)
    editorial_findings = build_editorial_findings(pack, claims, surfaces, links)
    plan = plan_batches(pack, surfaces, claims, today=today)

    batches = plan["batches"]
    summary = {
        "pack": str(directory),
        "today": plan["today"],
        "claim_count": len(claims),
        "surface_count": len(surfaces),
        "editorial_blockers": sum(f["severity"] == "blocker" for f in editorial_findings),
        "executable_batch_ids": [b["id"] for b in batches if b.get("executable")],
        "shipped_batch_ids": [b["id"] for b in batches if b.get("state") == "shipped"],
        "needs_reprint_batch_ids": [
            b["id"]
            for b in batches
            if b.get("state") == "active"
            and b.get("decision")
            in {"reprint_required", "channel_or_stock_blocked", "stock_shortage_reprint"}
        ],
        "partial_batch_ids": [b["id"] for b in batches if b.get("decision") == "partial_patch_and_reprint"],
    }

    return {
        "summary": summary,
        "claim_register": list(claims.values()),
        "surface_register": list(surfaces.values()),
        "editorial": {
            "findings": editorial_findings,
            "links": links,
        },
        "planning": plan,
    }
