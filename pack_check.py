"""读取、校验并核对业务资料包。

不带子命令时保留最初的资料检查入口：输出各 TSV 的记录数。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 兼容 `python -I pack_check.py`：显式加入本脚本所在的受信任项目目录。
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pack_audit.api import audit_pack
from pack_audit.materials import DEFAULT_DATA, read_tables
from pack_audit.reporting import render_batch_text, render_markdown, to_json

__all__ = ["DEFAULT_DATA", "read_tables"]


def command_validate(directory: Path) -> None:
    for filename, rows in read_tables(directory).items():
        print(f"{filename}  共 {len(rows)} 条")


def command_audit(directory: Path, as_json: bool, today: str | None) -> None:
    report = audit_pack(directory, today=today)
    if as_json:
        print(to_json(report))
    else:
        print(render_markdown(report))


def command_batch(directory: Path, batch_id: str, as_json: bool, today: str | None) -> None:
    report = audit_pack(directory, today=today)
    batches = report["planning"]["batches"]
    exact = next((b for b in batches if b["id"] == batch_id), None)
    if exact is not None:
        matches = [exact]
        lookup = "id"
    else:
        matches = [b for b in batches if b.get("lot") == batch_id]
        lookup = "lot"

    if not matches:
        raise SystemExit(f"未知出货批号/产品批号：{batch_id}")

    if as_json:
        if lookup == "id":
            print(json.dumps(matches[0], ensure_ascii=False, indent=2))
        else:
            print(json.dumps(matches, ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(render_batch_text(report, b["id"]) for b in matches))


def command_report(directory: Path, out: Path, today: str | None) -> None:
    report = audit_pack(directory, today=today)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(to_json(report), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"已写入 {out / 'report.md'}")
    print(f"已写入 {out / 'report.json'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DATA, help="业务资料包路径")
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS：未在子命令后重复传入时，不要覆盖主解析器上的 --directory。
    common.add_argument("--directory", type=Path, default=argparse.SUPPRESS, help="业务资料包路径")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("validate", parents=[common], help="校验表结构和编号引用并输出条数")

    audit = subparsers.add_parser("audit", parents=[common], help="输出编校、版面和排产核对报告")
    audit.add_argument("--json", action="store_true", help="输出 JSON")
    audit.add_argument("--today", help="核对日期 YYYY-MM-DD，默认系统日期")

    batch = subparsers.add_parser("batch", parents=[common], help="查询某个出货批号的组合和可执行性")
    batch.add_argument("batch_id")
    batch.add_argument("--json", action="store_true", help="输出 JSON")
    batch.add_argument("--today", help="核对日期 YYYY-MM-DD，默认系统日期")

    report = subparsers.add_parser("report", parents=[common], help="同时写入 Markdown 和 JSON 共享报告")
    report.add_argument("--out", type=Path, default=Path("reports/latest"))
    report.add_argument("--today", help="核对日期 YYYY-MM-DD，默认系统日期")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in {None, "validate"}:
        command_validate(args.directory)
    elif args.command == "audit":
        command_audit(args.directory, args.json, args.today)
    elif args.command == "batch":
        command_batch(args.directory, args.batch_id, args.json, args.today)
    elif args.command == "report":
        command_report(args.directory, args.out, args.today)
    else:  # pragma: no cover - argparse 已保证
        parser.error("未知命令")


if __name__ == "__main__":
    main()
