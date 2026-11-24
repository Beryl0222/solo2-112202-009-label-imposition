"""声明、译语、印面之间的对照和编校结论。"""
from __future__ import annotations

from typing import Any

from .io_pack import location
from .physical import build_surface_index
from .textfacts import canonical_series, extract_statement, find_literal_span, loose_key


def build_claim_index(tables: dict[str, list[dict[str, str]]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in tables["claims.tsv"]:
        statement = extract_statement(row["text"])
        scope_canonical = canonical_series(row.get("scope"))
        # 元数据 scope 是权威范围；文本没有明确抽取出系列时用它补齐。
        series = statement["series"] or ([scope_canonical] if scope_canonical else [])
        index[row["id"]] = {
            "id": row["id"],
            "row": row,
            **statement,
            "series": series,
            "scope_canonical": scope_canonical,
            "market": row.get("market", ""),
            "lang": row.get("lang", ""),
            "parent": row.get("parent", ""),
        }
    return index


def _score_link(claim: dict[str, Any], surface: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    claim_keys = set(claim["atom_keys"])
    surface_keys = set(surface["statement"]["atom_keys"])
    claim_series = set(claim["series"])
    surface_series = set(surface["statement"]["series"])
    if claim_series and surface_series and not (claim_series & surface_series):
        return 0, ["series_conflict"]

    if claim["lang"] == surface["row"]["lang"]:
        score += 1
        reasons.append("same_language")

    # 文本连续包含是最强的翻译/断行证据。
    fragment = surface["row"]["text"].strip().rstrip(".。 ")
    if fragment and find_literal_span(claim["row"]["text"], fragment):
        score += 5
        reasons.append("exact_text_fragment")
    else:
        for key in surface_keys & claim_keys:
            kind, value = key.split(":", 1)
            if kind in {"voltage_permission", "voltage_only"}:
                score += 3
                reasons.append(f"voltage:{value}")
            elif kind in {"series_gate", "series_scope"}:
                score += 2
                reasons.append(f"series:{value}")
            elif kind == "commercial_condition":
                score += 3
                reasons.append("condition")
            elif kind == "lot_scope":
                score += 2
                reasons.append(f"lot:{value}")

    surface_voltages = set(surface["statement"]["voltages"])
    claim_voltages = set(claim["voltages"])
    if surface_voltages & claim_voltages and not any(r.startswith("voltage:") for r in reasons):
        score += 2
        reasons.append("voltage_value")

    surface_series = set(surface["statement"]["series"])
    claim_series = set(claim["series"])
    if surface_series & claim_series and "series" not in " ".join(reasons):
        score += 1
        reasons.append("series_value")

    # C4 类撤回/过渡声明没有对应的新品牌译文行，但明确许可 P4 类补救文字。
    for withdrawal in claim.get("withdrawals", []):
        allowed = set(withdrawal.get("allowed_voltages", []))
        lots = set(withdrawal.get("transition_lots", []))
        if allowed & set(surface["statement"]["voltages"]):
            score += 3
            reasons.append("transition_voltage")
        if lots & set(surface["statement"]["lots"]):
            score += 2
            reasons.append("transition_lot")
        if withdrawal.get("target_series") in surface["statement"]["series"]:
            score += 1
            reasons.append("transition_series")

    return score, reasons


def link_claims(
    claims: dict[str, dict[str, Any]], surfaces: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for sid, surface in surfaces.items():
        matches = []
        for cid, claim in claims.items():
            score, reasons = _score_link(claim, surface)
            if score >= 5:
                matches.append({"claim_id": cid, "score": score, "reasons": reasons})
        matches.sort(key=lambda item: (-item["score"], item["claim_id"]))

        # 若命中译文/子声明，再通过 parent 找到品牌原语。
        source_ids: list[str] = []
        for match in matches:
            parent = claims[match["claim_id"]].get("parent")
            if parent and parent not in {m["claim_id"] for m in matches} and parent not in source_ids:
                source_ids.append(parent)

        links.append(
            {
                "surface_id": sid,
                "claim_matches": matches,
                "source_claim_ids": source_ids,
            }
        )
    return links


def _atom_span(statement: dict[str, Any], kind_prefix: str, value: str | None = None) -> dict[str, Any] | None:
    for atom in statement["atoms"]:
        if atom["kind"].startswith(kind_prefix) and (value is None or atom.get("value") == value):
            return atom
    return None


def _clause_span_for_atom(statement: dict[str, Any], atom: dict[str, Any] | None) -> dict[str, int] | None:
    if not atom:
        return None
    for clause in statement["clauses"]:
        if clause["start"] <= atom["start"] < clause["end"]:
            return {"start": clause["start"], "end": clause["end"], "quote": clause["text"]}
    return {"start": atom["start"], "end": atom["end"], "quote": atom["quote"]}


def _linked_claim_ids(link: dict[str, Any]) -> list[str]:
    return [m["claim_id"] for m in link["claim_matches"]] + link["source_claim_ids"]


def build_editorial_findings(
    pack: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    surfaces: dict[str, dict[str, Any]],
    links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    link_by_surface = {link["surface_id"]: link for link in links}

    # 1. 找到“兼容性在一个区域、系列限定在另一个可消失区域”的断行。
    for sid, surface in surfaces.items():
        compatibility_atom = next(
            (a for a in surface["statement"]["atoms"] if a["kind"] == "voltage_permission"),
            None,
        )
        if not compatibility_atom:
            continue
        linked_claim_ids = [
            match["claim_id"]
            for match in link_by_surface[sid]["claim_matches"]
            if any(a["kind"] == "series_gate" for a in claims[match["claim_id"]]["atoms"])
        ]
        if not linked_claim_ids or any(a["kind"] == "series_gate" for a in surface["statement"]["atoms"]):
            continue

        expected_series = None
        for cid in linked_claim_ids:
            gate = _atom_span(claims[cid], "series_gate")
            if gate:
                expected_series = gate["value"]
                break

        gate_surfaces = [
            other_id
            for other_id, other in surfaces.items()
            if any(
                a["kind"] == "series_gate" and (expected_series is None or a.get("value") == expected_series)
                for a in other["statement"]["atoms"]
            )
        ]
        ephemeral_gates = [gid for gid in gate_surfaces if surfaces[gid]["removable"]]
        permanent_gates = [gid for gid in gate_surfaces if not surfaces[gid]["removable"]]

        if ephemeral_gates and not permanent_gates:
            gid = ephemeral_gates[0]
            gate_atom = _atom_span(surfaces[gid]["statement"], "series_gate")
            locations = [
                location(pack, "print_surfaces", sid, "text", compatibility_atom, "detached_compatibility"),
                location(pack, "print_surfaces", gid, "text", gate_atom, "ephemeral_series_limit"),
            ]
            source_locations = []
            translation_locations = []
            withdrawal_locations = []
            for cid in linked_claim_ids:
                claim = claims[cid]
                gate = _atom_span(claim, "series_gate", expected_series)
                clause_span = _clause_span_for_atom(claim, gate or compatibility_atom)
                loc = location(pack, "claims", cid, "text", clause_span, "translated_claim" if claim["lang"] != "zh" else "source_claim")
                if claim["lang"] == "zh":
                    source_locations.append(loc)
                else:
                    translation_locations.append(loc)
                if claim["parent"] and claim["parent"] in claims:
                    parent = claims[claim["parent"]]
                    parent_gate = _atom_span(parent, "series_gate", expected_series)
                    parent_span = _clause_span_for_atom(parent, parent_gate)
                    source_locations.append(location(pack, "claims", parent["id"], "text", parent_span, "source_claim"))

            # C4 撤回声明作为额外依据。
            for cid, claim in claims.items():
                if claim["withdrawals"] and expected_series in claim["series"]:
                    wspan = claim["withdrawals"][0]["span"]
                    withdrawal_locations.append(location(pack, "claims", cid, "text", wspan, "withdrawal_notice"))

            findings.append(
                {
                    "code": "EPHEMERAL_QUALIFIER",
                    "severity": "blocker",
                    "title": "兼容性与系列限定被拆开，且限定位于可揭/可撕区域",
                    "surface_ids": [sid, gid],
                    "claim_ids": linked_claim_ids,
                    "locations": locations,
                    "source_locations": _dedupe_locations(source_locations),
                    "translation_locations": _dedupe_locations(translation_locations),
                    "withdrawal_locations": _dedupe_locations(withdrawal_locations),
                    "rule": "按限定消失后的到盒文本判定；可移除价格签只能作为印厂内部核对线索，不能承担合规限定。",
                    "required_action": "把完整兼容/限定句移到永久外贴，或用永久层完整覆盖旧句；不得依赖可撕价格签。",
                }
            )

    # 2. 已撤回主张仍出现在印面。
    for cid, claim in claims.items():
        for withdrawal in claim["withdrawals"]:
            for voltage in withdrawal["target_voltages"]:
                affected = []
                for sid, surface in surfaces.items():
                    for atom in surface["statement"]["atoms"]:
                        if (
                            atom["kind"] == "voltage_permission"
                            and atom["value"] == voltage
                            and not surface["covers"]
                        ):
                            affected.append((sid, atom))
                if not affected:
                    continue
                withdrawal_location = location(
                    pack, "claims", cid, "text", withdrawal["span"], "withdrawal_notice"
                )
                locs = [withdrawal_location]
                old_claim_locations = []
                for other_id, other in claims.items():
                    atom = next(
                        (
                            a
                            for a in other["atoms"]
                            if a["kind"] == "voltage_permission" and a["value"] == voltage
                        ),
                        None,
                    )
                    if atom:
                        span = _clause_span_for_atom(other, atom)
                        role = "source_claim" if other["lang"] == "zh" else "translated_claim"
                        old_claim_locations.append(location(pack, "claims", other_id, "text", span, role))
                for sid, atom in affected:
                    locs.append(location(pack, "print_surfaces", sid, "text", atom, "withdrawn_print_text"))
                findings.append(
                    {
                        "code": "WITHDRAWN_CLAIM_ON_PLATE",
                        "severity": "blocker",
                        "title": f"{voltage} 主张已撤回，但旧文字仍在未被覆盖的共版区域",
                        "claim_ids": [cid],
                        "surface_ids": [sid for sid, _ in affected],
                        "locations": locs,
                        "source_locations": [x for x in old_claim_locations if x.get("role") == "source_claim"],
                        "translation_locations": [x for x in old_claim_locations if x.get("role") == "translated_claim"],
                        "withdrawal_locations": [withdrawal_location],
                        "rule": "已完成印刷但未签收时，按实际市场和物理补救决定隔离、贴补或返印。",
                        "required_action": "隔离旧盒；用含当前电压、系列和批号范围的永久贴完整覆盖，或返印。",
                    }
                )

    # 3. 可接受的永久覆盖补正。
    for sid, surface in surfaces.items():
        if surface["kind"] != "sticker_or_label" or surface["removable"] or not surface["covers"]:
            continue
        has_voltage_rule = any(a["kind"] == "voltage_only" for a in surface["statement"]["atoms"])
        has_series = bool(surface["statement"]["series"])
        if has_voltage_rule and has_series:
            findings.append(
                {
                    "code": "ACCEPTED_PERMANENT_CORRECTION",
                    "severity": "ok",
                    "title": "永久覆盖层包含电压和系列范围，可作为贴补候选",
                    "surface_ids": [sid],
                    "locations": [location(pack, "print_surfaces", sid, "text")],
                    "covers": surface["covers"],
                    "lots": surface["statement"]["lots"],
                    "rule": "必须完整覆盖错误句，并在同一外盒销售阶段保留全部限定。",
                    "required_action": "仅在市场、系列、批号和库存数量匹配时贴补放行。",
                }
            )

    # 4. 开箱阶段才出现的附带条件。
    for link in links:
        sid = link["surface_id"]
        surface = surfaces[sid]
        condition_atom = next(
            (a for a in surface["statement"]["atoms"] if a["kind"] == "commercial_condition"), None
        )
        if not condition_atom:
            continue
        findings.append(
            {
                "code": "CONDITION_STAGE_VISIBILITY",
                "severity": "notice" if surface["visible_stage"] == "opening" else "ok",
                "title": "附带条件已与原声明对上，但可见阶段不同",
                "surface_ids": [sid],
                "claim_ids": _linked_claim_ids(link),
                "locations": [location(pack, "print_surfaces", sid, "text", condition_atom, "condition_text")],
                "visible_stage": surface["visible_stage"],
                "rule": "箱内卡可随盒到达顾客，但不能补回外盒在摆货/付款阶段已经断开的系列限定。",
                "required_action": "按市场披露窗口确认是否需在外层同步；校勘时保留阶段证据。",
            }
        )

    # 5. 批号限定提示。
    for sid, surface in surfaces.items():
        if surface["statement"]["lots"]:
            atom = next(a for a in surface["statement"]["atoms"] if a["kind"] == "lot_scope")
            findings.append(
                {
                    "code": "LOT_SCOPED_PRINT",
                    "severity": "notice",
                    "title": "印面文字带批号范围，不能跨批号通用",
                    "surface_ids": [sid],
                    "locations": [location(pack, "print_surfaces", sid, "text", atom, "lot_scope")],
                    "lots": surface["statement"]["lots"],
                    "required_action": "排产时逐批号匹配；V8 文字不能默认用于 V9。",
                }
            )

    # 6. 重复印面文字：保留位置，提示按实际层级/覆盖关系校勘。
    grouped: dict[str, list[str]] = {}
    for sid, surface in surfaces.items():
        key = loose_key(surface["row"]["text"])
        if key:
            grouped.setdefault(key, []).append(sid)
    for sids in grouped.values():
        if len(sids) < 2:
            continue
        findings.append(
            {
                "code": "DUPLICATE_PRINT_TEXT",
                "severity": "notice",
                "title": "多个印面出现相同或仅大小写/重音不同的文字",
                "surface_ids": sids,
                "locations": [location(pack, "print_surfaces", sid, "text") for sid in sids],
                "required_action": "确认是否为有意重复；若层级重叠，以叠贴后仍可见的顶层文本为准。",
            }
        )

    return _dedupe_findings(findings)


def _dedupe_locations(locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for loc in locations:
        key = (loc["file"], loc["row"], loc.get("field"), loc.get("char_start"), loc.get("char_end"), loc.get("role"))
        if key not in seen:
            seen.add(key)
            result.append(loc)
    return result


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for finding in findings:
        key = (finding["code"], tuple(finding.get("surface_ids", [])), tuple(finding.get("claim_ids", [])))
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result
