"""给编校和排产人员共享的文本/Markdown/JSON 报告。"""
from __future__ import annotations

import json
from typing import Any


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)


def _loc_line(locations: list[dict[str, Any]], roles: set[str] | None = None) -> str:
    parts = []
    for loc in locations:
        if roles and loc.get("role") not in roles:
            continue
        coordinate = loc.get("start_coordinate") or loc.get("coordinate")
        quote = loc.get("quote")
        if quote:
            parts.append(f"`{coordinate}` “{quote}”")
        else:
            parts.append(f"`{coordinate}`")
    return "<br>".join(parts)


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines: list[str] = []
    lines.append("# 包装声明校勘与排产核对报告")
    lines.append("")
    lines.append(f"- 资料包：`{summary['pack']}`")
    lines.append(f"- 核对日期：{summary['today']}")
    lines.append(
        f"- 声明 {summary['claim_count']} 条；印面 {summary['surface_count']} 条；"
        f"编校阻断项 {summary['editorial_blockers']} 个"
    )
    lines.append(f"- 当前可整单执行：{_ids(summary['executable_batch_ids'])}")
    lines.append(f"- 已发追溯：{_ids(summary['shipped_batch_ids'])}")
    lines.append(f"- 需渠道/库存处理或补印：{_ids(summary['needs_reprint_batch_ids'])}")
    if summary["partial_batch_ids"]:
        lines.append(f"- 仅可部分贴补：{_ids(summary['partial_batch_ids'])}")
    lines.append("")

    lines.append("## 一、编校需要修改的原语、译语和印面位置")
    lines.append("")
    for finding in report["editorial"]["findings"]:
        if finding["severity"] not in {"blocker", "warning"}:
            continue
        icon = "⛔" if finding["severity"] == "blocker" else "⚠️"
        lines.append(f"### {icon} {finding['code']} — {finding['title']}")
        lines.append("")
        lines.append(f"- 处理要求：{finding['required_action']}")
        if finding.get("rule"):
            lines.append(f"- 判定规则：{finding['rule']}")
        if finding.get("source_locations"):
            lines.append(f"- 原语位置：{_loc_line(finding['source_locations'])}")
        if finding.get("translation_locations"):
            lines.append(f"- 译语位置：{_loc_line(finding['translation_locations'])}")
        if finding.get("withdrawal_locations"):
            lines.append(f"- 撤回依据：{_loc_line(finding['withdrawal_locations'])}")
        if finding.get("locations"):
            related = [loc for loc in finding["locations"] if loc.get("role") != "withdrawal_notice"]
            if related:
                lines.append(f"- 相关印面/位置：{_loc_line(related)}")
        lines.append("")

    lines.append("## 二、声明与实际印刷区域对照")
    lines.append("")
    lines.append("### 2.1 声明要素登记")
    lines.append("")
    lines.append("| 声明 | 语言/市场 | 元数据范围 | 识别出的规范要素 |")
    lines.append("|---|---|---|---|")
    for claim in report.get("claim_register", []):
        facts = _claim_fact_labels(claim)
        raw_scope = claim.get("scope_canonical") or claim["row"].get("scope", "")
        lines.append(
            f"| `{claim['id']}` | {claim['lang']} / {claim['market']} | {raw_scope} | {facts} |"
        )
    lines.append("")
    lines.append("### 2.2 印面匹配")
    lines.append("")
    lines.append("| 印面 | 匹配声明 | 找到的原声明 | 说明 |")
    lines.append("|---|---|---|---|")
    for link in report["editorial"]["links"]:
        matches = ", ".join(
            f"{m['claim_id']}({m['score']})" for m in link["claim_matches"]
        ) or "—"
        sources = ", ".join(link["source_claim_ids"]) or "—"
        reasons = []
        for match in link["claim_matches"]:
            reasons.extend(match["reasons"])
        reason_text = ", ".join(dict.fromkeys(reasons)) or "证据不足"
        lines.append(f"| `{link['surface_id']}` | {matches} | {sources} | {reason_text} |")
    lines.append("")

    lines.append("## 三、排产批次核对")
    lines.append("")
    lines.append("| 批号 | 产品/批 | 市场 | 份数 | 承诺日 | 状态 | 结论 | 可整单执行 |")
    lines.append("|---|---|---|---:|---|---|---|---|")
    for batch in report["planning"]["batches"]:
        product_lot = f"{batch['product']} / {batch['lot']}"
        executable = _executable_label(batch)
        lines.append(
            f"| `{batch['id']}` | {product_lot} | {batch['market']} | {batch['qty']} | "
            f"{batch.get('promised') or '未承诺'} | {batch['stage']} | "
            f"{_decision_title(batch['decision'])} | {executable} |"
        )
    lines.append("")

    for batch in report["planning"]["batches"]:
        lines.append(f"### 批号 `{batch['id']}` — {_decision_title(batch['decision'])}")
        lines.append("")
        lines.append(f"- 订单：{batch['product']} / {batch['lot']}，{batch['market']}，{batch['qty']} 份")
        if batch.get("promised"):
            overdue = "（已超过承诺日）" if batch.get("overdue") else ""
            lines.append(f"- 承诺日期：{batch['promised']}{overdue}")
        lines.append(f"- 操作建议：{batch['action']}")
        if batch.get("effective_assets"):
            lines.append(f"- 实际组合：`{'|'.join(batch['effective_assets'])}`")
        elif batch.get("blocked_candidate"):
            candidate_ids = batch["blocked_candidate"].get("surface_ids", [])
            lines.append(f"- 最接近但不可执行的候选：`{'|'.join(candidate_ids)}`")
        if batch.get("covered_qty") is not None and batch.get("state") == "active":
            lines.append(
                f"- 当前可覆盖：{batch['covered_qty']}；缺口/补印：{batch['short_qty']}"
            )
        if batch.get("contact"):
            lines.append(f"- 收货方：{batch['contact']['destination']}")
        if batch.get("allocations"):
            alloc_text = ", ".join(
                f"{a['stock_id']}→{a['surface_id']}×{a['qty']}" for a in batch["allocations"]
            )
            lines.append(f"- 本次锁定库存：{alloc_text}")
        evaluation = batch.get("evaluation")
        if evaluation:
            visible = " / ".join(f"{item['id']}: {item['text']}" for item in evaluation["collated_text"])
            lines.append(f"- 叠贴后校勘文本：{visible}")
            for blocker in evaluation.get("blockers", []):
                lines.append(f"  - ⛔ {blocker['code']}：{blocker['message']}")
            for warning in evaluation.get("warnings", []):
                lines.append(f"  - ⚠️ {warning['code']}：{warning['message']}")
        if batch.get("held_text"):
            lines.append("- 已发批次手中文本：")
            for item in batch["held_text"]:
                lines.append(f"  - `{item['id']}`（第 {item['layer']} 层）：{item['text']}")
        lines.append("")

    lines.append("## 四、盒胚和印面可用性")
    lines.append("")
    lines.append("| 库存 | 印面 | 判定 | 市场 | 系列 | 批号 | 剩余 | 使用边界 |")
    lines.append("|---|---|---|---|---|---|---:|---|")
    for item in report["planning"].get("component_decisions", []):
        lines.append(
            f"| `{item['stock_id']}` | `{item['surface_id']}` | {_component_title(item['verdict'])} | "
            f"{item['market_scope']} | {','.join(item['series_scope']) or '—'} | "
            f"{','.join(item['lot_scope']) or '—'} | {item['remaining_qty']} | {item['usage']} |"
        )
    lines.append("")

    lines.append("## 五、分配后库存")
    lines.append("")
    lines.append("| 库存号 | 印面 | 登记渠道 | 原数量 | 剩余可分配 |")
    lines.append("|---|---|---|---:|---:|")
    for row in report["planning"]["stock"]:
        lines.append(
            f"| `{row['id']}` | `{row['item']}` | {row['region']} | {row['qty']} | {row['remaining_qty']} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_batch_text(report: dict[str, Any], batch_id: str) -> str:
    batch = next((b for b in report["planning"]["batches"] if b["id"] == batch_id), None)
    if not batch:
        raise KeyError(batch_id)
    lines = [
        f"批号 {batch['id']}",
        f"  订单: {batch['product']} / {batch['lot']} / {batch['market']} / {batch['qty']} 份",
        f"  阶段: {batch['stage']}",
        f"  结论: {_decision_title(batch['decision'])}",
        f"  可整单执行: {'是' if batch.get('executable') else '否'}",
        f"  建议: {batch['action']}",
    ]
    if batch.get("effective_assets"):
        lines.append(f"  组合: {'|'.join(batch['effective_assets'])}")
    elif batch.get("blocked_candidate"):
        candidate = batch["blocked_candidate"]
        lines.append(f"  最接近候选: {'|'.join(candidate.get('surface_ids', []))}")
        if candidate.get("region_blocked"):
            lines.append(f"  渠道阻断印面: {'|'.join(candidate.get('blocked_surfaces', []))}")
    if batch.get("allocations"):
        lines.append(
            "  锁定库存: "
            + ", ".join(f"{a['stock_id']}({a['surface_id']})×{a['qty']}" for a in batch["allocations"])
        )
    evaluation = batch.get("evaluation")
    if evaluation:
        lines.append("  可见文本:")
        for item in evaluation["collated_text"]:
            lines.append(f"    - {item['id']}: {item['text']}")
        for blocker in evaluation["blockers"]:
            lines.append(f"    [阻断] {blocker['code']}: {blocker['message']}")
        for warning in evaluation["warnings"]:
            lines.append(f"    [注意] {warning['code']}: {warning['message']}")
    if batch.get("contact"):
        lines.append(f"  联系: {batch['contact']['destination']}")
    return "\n".join(lines)


def _ids(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "无"


def _executable_label(batch: dict[str, Any]) -> str:
    if batch.get("state") == "shipped":
        return "已发出（仅追溯）"
    if batch.get("executable"):
        return "✅ 是"
    if batch.get("covered_qty"):
        return f"部分（{batch['covered_qty']}/{batch['qty']}）"
    return "❌ 否"


def _claim_fact_labels(claim: dict[str, Any]) -> str:
    kind_labels = {
        "series_gate": "系列排他限定",
        "series_scope": "系列范围",
        "voltage_permission": "兼容性",
        "voltage_only": "排除/仅可用电压",
        "voltage_mentioned": "电压表述",
        "withdrawn_voltage": "已撤回电压",
        "commercial_condition": "附带条件(适配器另购/不含)",
        "lot_scope": "批号范围",
        "withdrawal": "声明撤回",
    }
    labels = []
    for atom in claim.get("atoms", []):
        label = kind_labels.get(atom["kind"], atom["kind"])
        value = atom.get("value")
        if value and atom["kind"] != "withdrawal":
            labels.append(f"{label}:{value}")
        else:
            labels.append(label)
    return "；".join(dict.fromkeys(labels)) or "未识别到规范要素"


def _component_title(verdict: str) -> str:
    return {
        "box_blank_conditionally_usable": "盒胚可条件使用",
        "internal_proof_only": "仅内部核对/冗余签",
        "permanent_scope_patch": "永久范围补正贴",
        "stage_limited_insert": "分阶段箱内卡",
        "print_component": "印刷部件",
    }.get(verdict, verdict)


def _decision_title(decision: str) -> str:
    return {
        "quarantine_then_patch_release": "隔离后贴补放行",
        "release_existing_combo": "现有组合可放行",
        "kit_from_stock": "可用库存成套",
        "partial_patch_and_reprint": "部分贴补，余量补印",
        "stock_shortage_reprint": "合格方案但零库存，需补印",
        "channel_or_stock_blocked": "渠道/库存不可挪用",
        "reprint_required": "需补印/返印",
        "shipped_trace": "已发批次追溯",
    }.get(decision, decision)
