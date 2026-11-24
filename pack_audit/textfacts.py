"""声明、版面文字中的规范化事实抽取。

资料是合成业务文本，这里采用可解释的规则而不是外部模型，便于编校在报告中
看到每个结论对应的原文区间。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

VOLT_RE = re.compile(r"(\d{1,3})\s*[Vv](?![A-Za-z0-9])")
LOT_RE = re.compile(r"\b([A-Z]\d{1,4})\b")
WITHDRAW_RE = re.compile(r"撤回|撤销|废止|停止使用|retirad[oa]?|withdraw(?:n|al)?|revoc", re.IGNORECASE)
COMPAT_RE = re.compile(r"兼容|支持|适配|compatible|compatibilidade|support", re.IGNORECASE)
ONLY_VOLT_RE = re.compile(
    r"仅可用|只能用|只可用|仅支持\s*\d|s[óo]lo\s+(?:adaptador(?:es)?\s+)?(?:de\s+)?\d+\s*V|"
    r"only\s+(?:\d+\s*V|power|voltage)",
    re.IGNORECASE,
)
SERIES_GATE_RES = [
    re.compile(r"仅\s*甲\s*系列|只有\s*甲\s*系列|仅限?\s*甲(?:系列)?|甲系列?\s*专属"),
    re.compile(r"仅\s*乙\s*系列|只有\s*乙\s*系列|仅限?\s*乙(?:系列)?|乙系列?\s*专属"),
    re.compile(r"s[óo]lo\s+serie\s+([AB])", re.IGNORECASE),
    re.compile(r"s[óo]lo\s+([AB])(?![A-Za-z0-9])"),
    re.compile(r"only\s+([AB])[-\s]?series?", re.IGNORECASE),
    re.compile(r"([AB])[-\s]?series?\s+only", re.IGNORECASE),
    re.compile(r"only\s+([AB])(?![A-Za-z0-9])", re.IGNORECASE),
]
SERIES_ANY_RES = [
    (re.compile(r"甲"), "A"),
    (re.compile(r"乙"), "B"),
    (re.compile(r"(?:serie|series)\s+([AB])", re.IGNORECASE), None),
    (re.compile(r"([AB])\s*(?:系列|系)", re.IGNORECASE), None),
    (re.compile(r"([AB])[-\s]?series?", re.IGNORECASE), None),
    (re.compile(r"(?<![A-Za-z0-9])([AB])(?![A-Za-z0-9])"), None),
]
ADAPTER_RES = [
    re.compile(r"adaptador\s+no\s+inclu[ií]do", re.IGNORECASE),
    re.compile(r"adapter\s+(?:is\s+)?not\s+included", re.IGNORECASE),
    re.compile(r"adapt(?:er|or)\s+not\s+included", re.IGNORECASE),
    re.compile(r"适配器[^。；;！!？?]*(?:需另购|另购|单独购|不包含|未附带|自备)"),
    re.compile(r"(?:需另购|另购|单独购|自备)[^。；;！!？?]*适配器"),
]
CLAUSE_SPLIT_RE = re.compile(r"[^。！？!?.;；\n]+(?:[。！？!?.;；]*)")


def strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def loose_key(text: str) -> str:
    """生成用于跨大小写、重音和空白比较的键。"""
    text = strip_accents(text).casefold()
    return re.sub(r"[^0-9a-z一-鿿]+", "", text)


def span_dict(text: str, start: int, end: int, kind: str | None = None, value: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "start": start,
        "end": end,
        "quote": text[start:end],
    }
    if kind is not None:
        result["kind"] = kind
    if value is not None:
        result["value"] = value
    return result


def find_literal_span(text: str, fragment: str, occurrence: int = 0) -> dict[str, int] | None:
    """按忽略大小写的字面量查找片段，返回原文字符区间。"""
    if not fragment:
        return None
    pattern = re.compile(re.escape(fragment), re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if occurrence >= len(matches):
        return None
    match = matches[occurrence]
    return {"start": match.start(), "end": match.end()}


def find_loose_span(text: str, fragment: str) -> dict[str, int] | None:
    """在允许大小写/重音差异时查找连续原文。

    先做直接忽略大小写匹配；找不到时返回 fragment 中最长实词的位置，供人工
    校对定位。报告中的 quote 始终来自原始资料。
    """
    direct = find_literal_span(text, fragment)
    if direct:
        return direct
    folded_text = strip_accents(text).casefold()
    folded_fragment = strip_accents(fragment).casefold()
    index = folded_text.find(folded_fragment)
    if index >= 0:
        return {"start": index, "end": index + len(fragment)}
    words = [w for w in re.split(r"\s+", fragment.strip()) if len(w) >= 4]
    for word in sorted(words, key=len, reverse=True):
        match = re.search(re.escape(word), text, re.IGNORECASE)
        if match:
            return {"start": match.start(), "end": match.end()}
    return None


def canonical_series(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value in {"甲", "A", "a"}:
        return "A"
    if value in {"乙", "B", "b"}:
        return "B"
    match = re.search(r"([AB])", value, re.IGNORECASE)
    return match.group(1).upper() if match else None


def clause_spans(text: str) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    for match in CLAUSE_SPLIT_RE.finditer(text):
        raw = match.group(0)
        left_trim = len(raw) - len(raw.lstrip())
        right_trim = len(raw) - len(raw.rstrip())
        start = match.start() + left_trim
        end = match.end() - right_trim
        if start < end:
            clauses.append({"start": start, "end": end, "text": text[start:end]})
    return clauses


def _series_in_clause(clause: str) -> tuple[str | None, dict[str, int] | None, bool]:
    """返回系列、区间、是否为排他限定。"""
    for index, pattern in enumerate(SERIES_GATE_RES):
        match = pattern.search(clause)
        if match:
            if index == 0:
                value = "A"
            elif index == 1:
                value = "B"
            else:
                value = canonical_series(match.group(1))
            if value:
                return value, {"start": match.start(), "end": match.end()}, True

    for pattern, fixed in SERIES_ANY_RES:
        match = pattern.search(clause)
        if match:
            value = fixed or canonical_series(match.group(1))
            if value:
                return value, {"start": match.start(), "end": match.end()}, False
    return None, None, False


def extract_statement(text: str) -> dict[str, Any]:
    """抽取一段文本中的全部规范事实和对应区间。"""
    atoms: list[dict[str, Any]] = []
    series_values: list[str] = []
    voltage_values: list[str] = []
    lot_values: list[str] = []
    withdrawals: list[dict[str, Any]] = []
    clauses = clause_spans(text)

    for clause in clauses:
        clause_text = clause["text"]
        base = clause["start"]

        series, series_span, gated = _series_in_clause(clause_text)
        if series and series_span:
            series_values.append(series)
            abs_span = {"start": base + series_span["start"], "end": base + series_span["end"]}
            atoms.append(
                span_dict(
                    text,
                    abs_span["start"],
                    abs_span["end"],
                    "series_gate" if gated else "series_scope",
                    series,
                )
            )

        for match in VOLT_RE.finditer(clause_text):
            voltage = f"{int(match.group(1))}V"
            voltage_values.append(voltage)
            start = base + match.start()
            end = base + match.end()
            if WITHDRAW_RE.search(clause_text):
                kind = "withdrawn_voltage"
            elif ONLY_VOLT_RE.search(clause_text):
                kind = "voltage_only"
            elif COMPAT_RE.search(clause_text):
                kind = "voltage_permission"
            elif re.search(r"s[óo]lo|only|仅|只", clause_text, re.IGNORECASE):
                kind = "voltage_only"
            else:
                kind = "voltage_mentioned"
            atoms.append(span_dict(text, start, end, kind, voltage))

        for match in LOT_RE.finditer(clause_text):
            lot = match.group(1).upper()
            # 电压写法如 24 V 不会被 LOT_RE 命中；这里仍排除电压紧邻片段。
            lot_values.append(lot)
            start = base + match.start()
            end = base + match.end()
            atoms.append(span_dict(text, start, end, "lot_scope", lot))

        for pattern in ADAPTER_RES:
            match = pattern.search(clause_text)
            if match:
                start = base + match.start()
                end = base + match.end()
                atoms.append(
                    span_dict(text, start, end, "commercial_condition", "adapter_not_included_or_separate")
                )
                break

        withdraw_match = WITHDRAW_RE.search(clause_text)
        if withdraw_match:
            # 中文资料常写作“24 V 声明撤回，……更新后的 12 V……”。
            # 撤回词之前的电压是被撤回对象；撤回词之后的电压通常是过渡/替代方案。
            prefix = clause_text[: withdraw_match.start()]
            prefix_voltages = [f"{int(m.group(1))}V" for m in VOLT_RE.finditer(prefix)]
            full_voltages = [f"{int(m.group(1))}V" for m in VOLT_RE.finditer(clause_text)]
            after_keyword_abs = base + withdraw_match.end()
            tail = text[after_keyword_abs:]
            tail_voltages = {f"{int(m.group(1))}V" for m in VOLT_RE.finditer(tail)}
            target_voltages = prefix_voltages or [v for v in full_voltages if v not in tail_voltages]
            target_series, target_span, _ = _series_in_clause(prefix)
            if target_series is None:
                target_series, _, _ = _series_in_clause(clause_text)
            w_start = base + withdraw_match.start()
            w_end = base + withdraw_match.end()
            withdrawals.append(
                {
                    "span": {"start": w_start, "end": w_end, "quote": text[w_start:w_end]},
                    "target_voltages": sorted(set(target_voltages)),
                    "target_series": target_series,
                    "clause_start": clause["start"],
                    "clause_end": clause["end"],
                }
            )
            atoms.append(span_dict(text, w_start, w_end, "withdrawal", "claim_withdrawn"))

    # C4 这类过渡声明中，撤回词之后的许可电压/批号属于补救路径。
    for withdrawal in withdrawals:
        tail = text[withdrawal["span"]["end"] :]
        withdrawal["allowed_voltages"] = [f"{int(m.group(1))}V" for m in VOLT_RE.finditer(tail)]
        withdrawal["transition_lots"] = [m.group(1).upper() for m in LOT_RE.finditer(tail)]

        # 整句曾因包含撤回词而统一标成 withdrawn_voltage；这里把过渡句中的
        # 替代电压改回普通/排他电压，避免报告误称新电压也被撤回。
        target_set = set(withdrawal["target_voltages"])
        for atom in atoms:
            if atom["kind"] != "withdrawn_voltage" or atom["value"] in target_set:
                continue
            clause = next(
                (c for c in clauses if c["start"] <= atom["start"] < c["end"]),
                None,
            )
            clause_text = clause["text"] if clause else text
            atom["kind"] = "voltage_only" if ONLY_VOLT_RE.search(clause_text) else "voltage_mentioned"

    return {
        "text": text,
        "series": sorted(set(series_values)),
        "voltages": sorted(set(voltage_values), key=lambda x: int(x[:-1])),
        "lots": sorted(set(lot_values)),
        "atoms": atoms,
        "withdrawals": withdrawals,
        "clauses": clauses,
        "atom_keys": sorted({f'{a["kind"]}:{a["value"]}' for a in atoms}),
    }


def atom_keys(statement: dict[str, Any], kinds: set[str] | None = None) -> set[str]:
    keys = set(statement["atom_keys"])
    if kinds is not None:
        keys = {key for key in keys if key.split(":", 1)[0] in kinds}
    return keys
