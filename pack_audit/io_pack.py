"""资料包读取、稳定行号和 TSV 坐标。"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .materials import DEFAULT_DATA, read_tables

TABLE_FILES = {
    "claims": "claims.tsv",
    "print_surfaces": "print_surfaces.tsv",
    "dispatch": "dispatch.tsv",
    "stock": "stock.tsv",
    "sales_channels": "sales_channels.tsv",
}


def load_pack(directory: Path | str = DEFAULT_DATA) -> dict[str, Any]:
    directory = Path(directory)
    tables = read_tables(directory)
    line_numbers: dict[str, dict[str, int]] = {}
    raw_lines: dict[str, list[str]] = {}
    headers: dict[str, list[str]] = {}

    for filename in TABLE_FILES.values():
        path = directory / filename
        lines = path.read_text(encoding="utf-8").splitlines()
        raw_lines[filename] = lines
        headers[filename] = lines[0].split("\t")
        line_numbers[filename] = {}
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, delimiter="\t")
            for row in reader:
                line_numbers[filename][row["id"]] = reader.line_num

    return {
        "directory": directory,
        "tables": tables,
        "line_numbers": line_numbers,
        "raw_lines": raw_lines,
        "headers": headers,
    }


def location(
    pack: dict[str, Any],
    table: str,
    row_id: str,
    field: str | None = "text",
    span: dict[str, int] | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    filename = TABLE_FILES.get(table, table if table.endswith(".tsv") else f"{table}.tsv")
    row_number = pack["line_numbers"][filename][row_id]
    line = pack["raw_lines"][filename][row_number - 1]
    header = pack["headers"][filename]
    result: dict[str, Any] = {
        "file": filename,
        "row": row_number,
        "id": row_id,
    }
    if role:
        result["role"] = role
    if field:
        col_index = header.index(field)
        raw_fields = line.split("\t")
        # 资料约定不使用会包含制表符的引号字段；若遇到引号，仍给出字段内偏移。
        field_start_col = sum(len(part) + 1 for part in raw_fields[:col_index]) + 1
        result["field"] = field
        result["tsv_col"] = field_start_col
        result["coordinate"] = f"{filename}:{row_number}:{field_start_col}"
        if span:
            abs_col = field_start_col + span["start"]
            result["char_start"] = span["start"]
            result["char_end"] = span["end"]
            result["start_coordinate"] = f"{filename}:{row_number}:{abs_col}"
            result["quote"] = span.get("quote") if isinstance(span, dict) else None
            if result.get("quote") is None:
                result["quote"] = raw_fields[col_index][span["start"] : span["end"]]
    else:
        result["coordinate"] = f"{filename}:{row_number}"
    return result
