"""按实物合规、渠道、库存和承诺优先级生成排产方案。"""
from __future__ import annotations

import itertools
from datetime import date
from typing import Any

from .physical import collated_text, hidden_coverage, parse_id_list, visible_surface_ids
from .textfacts import canonical_series


def build_stock_index(tables: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    rows = []
    for row in tables["stock.tsv"]:
        rows.append({**row, "qty": int(row["qty"])})
    return rows


def region_allows(stock_region: str, market: str) -> bool:
    region = (stock_region or "").strip()
    return region in {"通用", "全部", "所有市场", "global", "all", "*"} or region == market


def channel_for_market(
    tables: dict[str, list[dict[str, str]]], market: str
) -> dict[str, str] | None:
    for row in tables["sales_channels.tsv"]:
        if row["market"] == market:
            return row
    return None


def derive_requirements(
    order: dict[str, str], claims: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    series = canonical_series(order.get("product"))
    market = order.get("market", "")
    forbidden_voltages: set[str] = set()
    required_voltages: set[str] = set()
    withdrawal_ids: list[str] = []

    for cid, claim in claims.items():
        claim_series = set(claim["statement"]["series"]) if "statement" in claim else set(claim["series"])
        if series and claim_series and series not in claim_series:
            continue
        if claim.get("market") not in {market, "通用", ""}:
            # 通用原声明仍可作为依据；其他市场的本地声明不参与。
            if claim.get("market") != market:
                continue

        if claim.get("withdrawals"):
            for withdrawal in claim["withdrawals"]:
                if withdrawal.get("target_series") and withdrawal["target_series"] != series:
                    continue
                forbidden_voltages.update(withdrawal.get("target_voltages", []))
                required_voltages.update(withdrawal.get("allowed_voltages", []))
                withdrawal_ids.append(cid)

        # 非撤回声明中的 only 电压是当前要求；必须确认该电压子句确实覆盖本系列，
        # 避免把同一份多系列原声明中乙系列的规则错套到甲系列。
        for atom in claim.get("atoms", []):
            if atom["kind"] != "voltage_only":
                continue
            clause = next(
                (
                    clause
                    for clause in claim.get("clauses", [])
                    if clause["start"] <= atom["start"] < clause["end"]
                ),
                None,
            )
            clause_series = [
                other["value"]
                for other in claim.get("atoms", [])
                if other["kind"] in {"series_scope", "series_gate"}
                and clause is not None
                and clause["start"] <= other["start"] < clause["end"]
            ]
            if clause_series and series not in clause_series:
                continue
            required_voltages.add(atom["value"])

    # 如果 only 电压恰好也是撤回目标（异常资料），以撤回为准。
    required_voltages -= forbidden_voltages
    if not required_voltages:
        # 保守兜底：同系列没有有效声明时不臆造电压。
        required_voltages = set()

    return {
        "series": series,
        "market": market,
        "forbidden_voltages": sorted(forbidden_voltages),
        "required_voltages": sorted(required_voltages),
        "withdrawal_claim_ids": sorted(set(withdrawal_ids)),
    }


def _claim_has_condition_for_series(
    claim: dict[str, Any], series: str | None, market: str
) -> bool:
    if claim.get("market") not in {market, "通用", ""}:
        return False
    condition_atoms = [a for a in claim["atoms"] if a["kind"] == "commercial_condition"]
    if not condition_atoms:
        return False

    for condition in condition_atoms:
        clause = next(
            (
                clause
                for clause in claim.get("clauses", [])
                if clause["start"] <= condition["start"] < clause["end"]
            ),
            None,
        )
        nearby_series = [
            atom["value"]
            for atom in claim["atoms"]
            if atom["kind"] in {"series_scope", "series_gate"}
            and clause is not None
            and clause["start"] <= atom["start"] < clause["end"]
        ]
        if nearby_series:
            if series in nearby_series:
                return True
            continue
        # 条件句本身没有系列时，回退到声明元数据/整份声明的系列。
        if series is None or claim.get("scope_canonical") == series or series in claim.get("series", []):
            return True
    return False


def evaluate_route(
    order: dict[str, str],
    surface_ids: list[str],
    surfaces: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    requirements = derive_requirements(order, claims)
    series = requirements["series"]
    lot = (order.get("lot") or "").strip()
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    unknown = [sid for sid in surface_ids if sid not in surfaces]
    if unknown:
        blockers.append({"code": "UNKNOWN_SURFACE", "message": f"未知印面：{'|'.join(unknown)}"})

    unique_ids = list(dict.fromkeys(surface_ids))
    hidden = hidden_coverage(unique_ids, surfaces)
    visible_ids = visible_surface_ids(unique_ids, surfaces)
    durable_outer_ids = [
        sid
        for sid in visible_ids
        if not surfaces[sid]["removable"] and surfaces[sid]["visible_stage"] != "opening"
    ]
    opening_ids = [sid for sid in visible_ids if surfaces[sid]["visible_stage"] == "opening"]

    durable_atoms = [
        atom
        for sid in durable_outer_ids
        for atom in surfaces[sid]["statement"]["atoms"]
    ]
    durable_keys = {f'{a["kind"]}:{a["value"]}' for a in durable_atoms}
    durable_series = {a["value"] for a in durable_atoms if a["kind"] in {"series_scope", "series_gate"}}
    visible_lots = {
        atom["value"]
        for sid in visible_ids
        for atom in surfaces[sid]["statement"]["atoms"]
        if atom["kind"] == "lot_scope"
    }
    visible_series = {
        atom["value"]
        for sid in visible_ids
        for atom in surfaces[sid]["statement"]["atoms"]
        if atom["kind"] in {"series_scope", "series_gate"}
    }
    condition_ids = [
        sid
        for sid in unique_ids
        if any(a["kind"] == "commercial_condition" for a in surfaces[sid]["statement"]["atoms"])
    ]

    if series:
        wrong_series = sorted(s for s in visible_series if s != series)
        if wrong_series:
            blockers.append(
                {
                    "code": "SERIES_MISMATCH",
                    "message": f"印面系列 {','.join(wrong_series)} 与订单产品 {series} 不符",
                }
            )
        if series not in durable_series:
            blockers.append(
                {
                    "code": "MISSING_DURABLE_SERIES_LIMIT",
                    "message": "永久外贴文本中没有与订单匹配的系列范围",
                }
            )

    if lot and visible_lots and lot not in visible_lots:
        blockers.append(
            {
                "code": "LOT_MISMATCH",
                "message": f"印面批号限定 {','.join(sorted(visible_lots))} 不覆盖订单批号 {lot}",
            }
        )

    durable_voltages = {
        atom["value"]
        for atom in durable_atoms
        if atom["kind"] in {"voltage_permission", "voltage_only", "voltage_mentioned"}
    }
    for voltage in requirements["forbidden_voltages"]:
        if voltage in durable_voltages:
            blockers.append(
                {
                    "code": "WITHDRAWN_VOLTAGE_VISIBLE",
                    "message": f"已撤回的 {voltage} 主张仍在叠贴后的永久外层可见",
                }
            )

    if requirements["required_voltages"]:
        if not (set(requirements["required_voltages"]) & durable_voltages):
            blockers.append(
                {
                    "code": "MISSING_CURRENT_VOLTAGE_STATEMENT",
                    "message": "永久外层缺少当前有效的电压/兼容性表述",
                }
            )

    # 任何永久外层上的正向兼容句，都必须在同一永久外层带有系列限定。
    has_permission = any(a["kind"] == "voltage_permission" for a in durable_atoms)
    has_series_gate = any(a["kind"] == "series_gate" and a["value"] == series for a in durable_atoms)
    if has_permission and not has_series_gate:
        blockers.append(
            {
                "code": "DETACHED_COMPATIBILITY_PROMISE",
                "message": "永久外层有兼容主张，但同阶段永久文本缺少系列限定",
            }
        )

    # 同一外层若出现互斥电压规则，不能靠原稿顺序豁免；必须显式覆盖隐藏。
    only_voltages = {a["value"] for a in durable_atoms if a["kind"] == "voltage_only"}
    if len(only_voltages) > 1:
        blockers.append(
            {
                "code": "CONFLICTING_VOLTAGE_TEXT",
                "message": f"叠贴后同时可见互斥电压文本：{','.join(sorted(only_voltages))}",
            }
        )

    applicable_condition = any(
        _claim_has_condition_for_series(claim, series, order["market"])
        for claim in claims.values()
    )
    if applicable_condition and not condition_ids:
        warnings.append(
            {
                "code": "MISSING_CONDITION_TEXT",
                "message": "原声明含附带条件，但组合中没有对应印面；需业务/法规确认是否阻断",
            }
        )
    elif applicable_condition and any(sid in opening_ids for sid in condition_ids):
        warnings.append(
            {
                "code": "CONDITION_ONLY_AFTER_OPENING",
                "message": "附带条件仅在开箱后可见，不能补回销售外层已断开的限定",
            }
        )

    return {
        "compliant": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "requirements": requirements,
        "surface_ids": unique_ids,
        "visible_surface_ids": visible_ids,
        "durable_outer_ids": durable_outer_ids,
        "opening_ids": opening_ids,
        "hidden_coverage": hidden,
        "collated_text": collated_text(unique_ids, surfaces),
    }


def _subset_options(candidate_ids: list[str], max_size: int = 3) -> list[tuple[str, ...]]:
    options: list[tuple[str, ...]] = [()]
    n = len(candidate_ids)
    if n <= 10:
        sizes = range(1, n + 1)
    else:
        sizes = range(1, min(max_size, n) + 1)
    for size in sizes:
        options.extend(itertools.combinations(candidate_ids, size))
    return options


def _stock_supply_for_surface(
    sid: str, market: str, stock_rows: list[dict[str, Any]], remaining: dict[str, int]
) -> list[dict[str, Any]]:
    supply = []
    for row in stock_rows:
        if row["item"] != sid:
            continue
        available = remaining[row["id"]]
        supply.append(
            {
                "stock_id": row["id"],
                "qty_available": available,
                "region": row["region"],
                "region_eligible": region_allows(row["region"], market),
            }
        )
    # 优先消耗本市场/登记渠道库存，保留通用库存给其他渠道。
    supply.sort(key=lambda item: (0 if item["region"] == market else 1, item["stock_id"]))
    return supply


def plan_batches(
    pack: dict[str, Any],
    surfaces: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    tables = pack["tables"]
    stock_rows = build_stock_index(tables)
    remaining = {row["id"]: row["qty"] for row in stock_rows}
    batches_out: list[dict[str, Any]] = []
    reservations: list[dict[str, Any]] = []

    dispatch_rows = tables["dispatch.tsv"]

    def build_options_for_order(order: dict[str, str]) -> list[dict[str, Any]]:
        market = order["market"]
        qty = int(order["qty"])
        existing = parse_id_list(order.get("assets", ""))
        stage = order.get("stage", "")
        is_shipped = "已发" in stage or "签收" in stage

        options: list[dict[str, Any]] = []

        def add_option(kind: str, base_ids: list[str], additions: list[str]) -> None:
            surface_ids = list(dict.fromkeys(base_ids + additions))
            evaluation = evaluate_route(order, surface_ids, surfaces, claims)
            sourcing = []
            region_blockers = []
            total_available = qty
            for sid in surface_ids:
                # 已装好的资产不占用当前在库数量。
                if sid in existing:
                    sourcing.append({"surface_id": sid, "already_installed": True})
                    continue
                supply = _stock_supply_for_surface(sid, market, stock_rows, remaining)
                eligible = [item for item in supply if item["region_eligible"]]
                if not eligible:
                    if supply:
                        region_blockers.append(sid)
                    else:
                        region_blockers.append(sid)
                    total_available = 0
                    sourcing.append(
                        {
                            "surface_id": sid,
                            "required": qty,
                            "eligible": False,
                            "supply": supply,
                        }
                    )
                    continue
                available_qty = sum(item["qty_available"] for item in eligible)
                total_available = min(total_available, available_qty)
                sourcing.append(
                    {
                        "surface_id": sid,
                        "required": qty,
                        "eligible": True,
                        "available_qty": available_qty,
                        "supply": eligible,
                    }
                )

            options.append(
                {
                    "kind": kind,
                    "additions": additions,
                    "evaluation": evaluation,
                    "sourcing": sourcing,
                    "region_blocked": bool(region_blockers),
                    "blocked_surfaces": region_blockers,
                    "currently_coverable_qty": min(qty, max(0, total_available)),
                    "component_count": len([s for s in surface_ids if s not in existing]),
                }
            )

        # 已存在实物组合：先评估原状，再搜索追加永久贴补。
        if existing:
            add_option("existing_combo", existing, [])
            candidate_additions = [
                sid
                for sid, profile in surfaces.items()
                if sid not in existing
                and profile["kind"] == "sticker_or_label"
                and not profile["removable"]
            ]
            for additions in _subset_options(candidate_additions, max_size=2):
                if not additions:
                    continue
                add_option("add_permanent_patch", existing, list(additions))

        # 待排/无资产：搜索在库底盒 + 永久外贴组合。
        if not is_shipped and (not existing or "待排" in stage):
            base_surfaces = [
                row["item"]
                for row in stock_rows
                if surfaces[row["item"]]["kind"] == "base_box"
            ]
            base_surfaces = list(dict.fromkeys(base_surfaces))
            candidate_stickers = [
                row["item"]
                for row in stock_rows
                if surfaces[row["item"]]["kind"] == "sticker_or_label"
                and surfaces[row["item"]]["permanent_outer"]
            ]
            candidate_stickers = list(dict.fromkeys(candidate_stickers))
            for base_id in base_surfaces:
                for sticker_set in _subset_options(candidate_stickers, max_size=2):
                    add_option("new_stock_combo", [base_id], list(sticker_set))

        return options

    # 先处理已发批次：只做追溯，不参与库存分配。
    active_orders = []
    for order in dispatch_rows:
        stage = order.get("stage", "")
        if "已发" in stage or "签收" in stage:
            evaluation = evaluate_route(
                order, parse_id_list(order.get("assets", "")), surfaces, claims
            )
            channel = channel_for_market(tables, order["market"])
            batches_out.append(
                _shipped_batch(order, evaluation, channel, pack)
            )
        else:
            active_orders.append(order)

    def priority_key(order: dict[str, str]):
        promised = order.get("promised", "")
        return (
            0 if promised else 1,
            promised or "9999-12-31",
            order["id"],
        )

    for order in sorted(active_orders, key=priority_key):
        qty = int(order["qty"])
        existing = parse_id_list(order.get("assets", ""))
        options = build_options_for_order(order)
        compliant_options = [opt for opt in options if opt["evaluation"]["compliant"]]
        region_options = [opt for opt in compliant_options if not opt["region_blocked"]]

        # 同一优先级内优先：能覆盖更多数量、追加件更少、无需新底盒。
        region_options.sort(
            key=lambda opt: (
                -opt["currently_coverable_qty"],
                opt["component_count"],
                0 if opt["kind"] == "existing_combo" else 1,
                len(opt["additions"]),
                "|".join(opt["evaluation"]["surface_ids"]),
            )
        )

        chosen = region_options[0] if region_options else None
        allocations: list[dict[str, Any]] = []
        covered_qty = 0
        if chosen:
            covered_qty = min(qty, chosen["currently_coverable_qty"])
            if covered_qty > 0:
                for source in chosen["sourcing"]:
                    if source.get("already_installed"):
                        continue
                    left_to_pick = covered_qty
                    for supply in source["supply"]:
                        if left_to_pick <= 0:
                            break
                        pick = min(left_to_pick, supply["qty_available"])
                        if pick <= 0:
                            continue
                        remaining[supply["stock_id"]] -= pick
                        allocation = {
                            "batch_id": order["id"],
                            "stock_id": supply["stock_id"],
                            "surface_id": source["surface_id"],
                            "qty": pick,
                            "region": supply["region"],
                        }
                        allocations.append(allocation)
                        reservations.append(allocation)
                        left_to_pick -= pick

        full_executable = bool(chosen and covered_qty == qty and qty > 0)
        promised_date = _parse_date(order.get("promised"))
        overdue = bool(promised_date and promised_date < today)

        if chosen and full_executable:
            if chosen["kind"] == "add_permanent_patch":
                decision = "quarantine_then_patch_release"
                action = "先隔离，再按分配数量贴永久覆盖层；覆盖并复核后投放订单市场。"
            elif chosen["kind"] == "existing_combo":
                decision = "release_existing_combo"
                action = "现有组合通过校勘，可按承诺渠道放行。"
            else:
                decision = "kit_from_stock"
                action = "按分配的底盒和市场贴纸成套后发出。"
        elif chosen and covered_qty > 0:
            decision = "partial_patch_and_reprint"
            action = "可用库存先贴补/成套一部分，不足数量安排补印；不得把同一库存再承诺给其他单。"
        elif chosen and covered_qty == 0:
            decision = "stock_shortage_reprint"
            action = "文字和渠道组合可合规，但当前可用库存为 0；应补印/入库后再执行。"
        elif compliant_options and not region_options:
            decision = "channel_or_stock_blocked"
            action = "文字组合本身可校勘通过，但缺少该市场可用的在库贴纸；不得挪用其他渠道登记库存，应补印/调拨。"
        else:
            decision = "reprint_required"
            action = "没有能在实物叠贴后完整保留当前主张的组合；隔离并返印或制作新的永久贴。"

        channel = channel_for_market(tables, order["market"])
        blocked_option = None
        if not chosen:
            # 保留最接近的失败方案，便于说明是渠道、批号还是文字问题。
            compliant_but_blocked = [opt for opt in compliant_options if opt["region_blocked"]]
            if compliant_but_blocked:
                blocked_option = sorted(
                    compliant_but_blocked,
                    key=lambda opt: (-opt["currently_coverable_qty"], opt["component_count"]),
                )[0]
            elif options:
                blocked_option = sorted(
                    options,
                    key=lambda opt: (
                        len(opt["evaluation"]["blockers"]),
                        opt["region_blocked"],
                        -opt["component_count"],
                        "|".join(opt["evaluation"]["surface_ids"]),
                    ),
                )[0]

        batches_out.append(
            {
                "id": order["id"],
                "state": "active",
                "product": order["product"],
                "lot": order["lot"],
                "market": order["market"],
                "qty": qty,
                "promised": order.get("promised", ""),
                "promised_date": order.get("promised", ""),
                "overdue": overdue,
                "stage": order["stage"],
                "existing_assets": existing,
                "decision": decision,
                "action": action,
                "executable": full_executable,
                "covered_qty": covered_qty if chosen else 0,
                "short_qty": qty - (covered_qty if chosen else 0),
                "allocations": allocations,
                "effective_assets": chosen["evaluation"]["surface_ids"] if chosen else existing,
                "evaluation": (chosen or blocked_option or {}).get("evaluation"),
                "blocked_candidate": _summarize_option(blocked_option) if blocked_option else None,
                "chosen_option": _summarize_option(chosen) if chosen else None,
                "channel": channel,
                "priority": {
                    "promised": bool(order.get("promised")),
                    "rank_key": list(priority_key(order)),
                },
            }
        )

    batches_out.sort(key=lambda b: b["id"])
    stock_view = [
        {**row, "remaining_qty": remaining[row["id"]]}
        for row in stock_rows
    ]
    component_decisions = _build_component_decisions(stock_rows, surfaces, remaining, reservations)
    return {
        "today": today.isoformat(),
        "batches": batches_out,
        "reservations": reservations,
        "stock": stock_view,
        "component_decisions": component_decisions,
    }


def _build_component_decisions(
    stock_rows: list[dict[str, Any]],
    surfaces: dict[str, dict[str, Any]],
    remaining: dict[str, int],
    reservations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decisions = []
    for row in stock_rows:
        sid = row["item"]
        profile = surfaces[sid]
        statement = profile["statement"]
        allocated = sum(a["qty"] for a in reservations if a["stock_id"] == row["id"])

        if profile["kind"] == "base_box":
            verdict = "box_blank_conditionally_usable"
            usage = "底盒/盒胚仍可使用，但裸盒不得承担已断开或已撤回的主张；必须叠加完整合格的永久覆盖层。"
        elif profile["removable"] and any(a["kind"] == "series_gate" for a in statement["atoms"]):
            verdict = "internal_proof_only"
            usage = "可作为印厂核对线索或冗余短签；限定被揭掉后不能独立承担合规作用。"
        elif profile["permanent_outer"] and statement["series"] and any(
            a["kind"] in {"voltage_only", "voltage_permission"} for a in statement["atoms"]
        ):
            verdict = "permanent_scope_patch"
            usage = "可在市场、系列、批号和数量匹配时作为永久范围/补正层。"
        elif profile["kind"] == "insert_card":
            verdict = "stage_limited_insert"
            usage = "随盒可见但通常只在开箱阶段出现，不能补回外层销售阶段缺失的限定。"
        else:
            verdict = "print_component"
            usage = "按实际叠贴文本和渠道范围核对后使用。"

        decisions.append(
            {
                "stock_id": row["id"],
                "surface_id": sid,
                "sku": profile["row"].get("sku", ""),
                "kind": profile["kind"],
                "verdict": verdict,
                "usage": usage,
                "market_scope": row["region"],
                "series_scope": statement["series"],
                "lot_scope": statement["lots"],
                "qty": row["qty"],
                "allocated_qty": allocated,
                "remaining_qty": remaining[row["id"]],
            }
        )
    return decisions


def _summarize_option(option: dict[str, Any] | None) -> dict[str, Any] | None:
    if not option:
        return None
    evaluation = option["evaluation"]
    return {
        "kind": option["kind"],
        "surface_ids": evaluation["surface_ids"],
        "additions": option["additions"],
        "compliant": evaluation["compliant"],
        "blockers": evaluation["blockers"],
        "warnings": evaluation["warnings"],
        "region_blocked": option["region_blocked"],
        "blocked_surfaces": option["blocked_surfaces"],
        "currently_coverable_qty": option["currently_coverable_qty"],
    }


def _shipped_batch(
    order: dict[str, str],
    evaluation: dict[str, Any],
    channel: dict[str, str] | None,
    pack: dict[str, Any],
) -> dict[str, Any]:
    compliant = evaluation["compliant"]
    if compliant:
        follow_up = "record_only"
        contact_action = "归档该批文字组合；如后续收到声明改版，按市场追溯同号批次。"
    else:
        follow_up = "contact_customer"
        contact_action = "立即联系该市场收货方，隔离未售库存并评估贴补、退换或召回。"
    return {
        "id": order["id"],
        "state": "shipped",
        "product": order["product"],
        "lot": order["lot"],
        "market": order["market"],
        "qty": int(order["qty"]),
        "promised": order.get("promised", ""),
        "stage": order["stage"],
        "existing_assets": parse_id_list(order.get("assets", "")),
        "effective_assets": evaluation["surface_ids"],
        "executable": False,
        "already_executed": True,
        "compliant_record": compliant,
        "decision": "shipped_trace",
        "follow_up": follow_up,
        "action": contact_action,
        "contact": {
            "market": order["market"],
            "channel_record_id": channel["id"] if channel else None,
            "destination": f"{order['market']}渠道收货方（资料未提供具体单位/联系人）",
        },
        "held_text": evaluation["collated_text"],
        "evaluation": evaluation,
        "channel": channel,
        "allocations": [],
        "covered_qty": int(order["qty"]),
        "short_qty": 0,
    }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
