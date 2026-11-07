#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Structural validation for the two deliverables of wuxia-timeline-audit.

Checks chapter coverage, table column consistency, per-paragraph time /
geography-power tags, and cross-document agreement. Structural only: verbatim
quotation checking and fact verification remain manual steps.

Examples:
    python validate_deliverables.py --table 时间线.md --synopsis 简写.md --chapters 40
    python validate_deliverables.py --table 时间线.md --chapters 40 --require-geo-power --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def table_cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(cells):
    return bool(cells) and all(re.fullmatch(r"[-: ]+", c or "-") for c in cells)


def analyze_table(text, expected_cols, chapters):
    lines = [l for l in text.splitlines() if l.strip().startswith("|")]
    parsed = [table_cells(l) for l in lines]
    parsed = [c for c in parsed if not is_separator(c)]
    if not parsed:
        return {"ok": False, "error": "未找到表格", "rows": 0}
    rows = parsed[1:]  # first row is the header
    bad_cols = [i + 2 for i, r in enumerate(rows) if len(r) != expected_cols]
    nums = []
    for r in rows:
        if len(r) >= 2:
            m = re.search(r"\d+", r[1])
            if m:
                nums.append(int(m.group()))
    covered = set(nums)
    missing = [n for n in range(1, chapters + 1) if n not in covered]
    extras = sorted(covered - set(range(1, chapters + 1)))
    split_rows = len(nums) - len(set(nums))
    return {
        "ok": not bad_cols and not missing and not extras,
        "rows": len(rows),
        "expected_cols": expected_cols,
        "bad_col_rows": bad_cols,
        "chapter_numbers": sorted(covered),
        "missing_chapters": missing,
        "unexpected_chapters": extras,
        "split_rows": max(0, split_rows),
        "header": parsed[0],
    }


def analyze_synopsis(text, chapters, require_geo):
    bold = [l for l in text.splitlines() if l.startswith("**")]
    # A plot paragraph starts with the canonical **〔time〕 tag, or at least
    # names a chapter. "前史" paragraphs carry no chapter number but still
    # must be checked for tags, so include them via the **〔 prefix.
    plot_idx = {i for i, l in enumerate(bold)
                if l.startswith("**〔") or re.search(r"第\s*\d+\s*回", l)}
    plot = [bold[i] for i in sorted(plot_idx)]
    other_bold = [l[:70] for i, l in enumerate(bold) if i not in plot_idx]
    no_time = [l[:70] for l in plot if "〔" not in l]
    no_geo = [l[:70] for l in plot if "【" not in l] if require_geo else []
    nums = set(int(x) for x in re.findall(r"第\s*(\d+)\s*回", "\n".join(plot)))
    missing = [n for n in range(1, chapters + 1) if n not in nums]
    extras = sorted(nums - set(range(1, chapters + 1)))
    return {
        "ok": not missing and not extras and not no_time and not no_geo,
        "plot_paragraphs": len(plot),
        "other_bold_lines": other_bold,
        "missing_time_tags": no_time,
        "missing_geo_power_tags": no_geo,
        "chapter_numbers": sorted(nums),
        "missing_chapters": missing,
        "unexpected_chapters": extras,
        "require_geo_power": require_geo,
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="时间线对照表与剧情简写的结构校验")
    ap.add_argument("--table", help="时间线对照表 md")
    ap.add_argument("--synopsis", help="剧情简写 md")
    ap.add_argument("--chapters", type=int, required=True, help="原文章节总数 N")
    ap.add_argument("--expected-cols", type=int, default=4, help="对照表列数，默认 4")
    ap.add_argument("--require-geo-power", action="store_true",
                    help="要求简写每段都带【】地理／实力标记")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    result, checks = {}, []

    if args.table:
        if not Path(args.table).is_file():
            print("文件不存在：%s" % args.table, file=sys.stderr)
            return 2
        t = analyze_table(read(args.table), args.expected_cols, args.chapters)
        result["table"] = t
        checks += [
            ("对照表列数一致（%d 列）" % args.expected_cols, not t.get("bad_col_rows")),
            ("对照表覆盖 1..%d 章" % args.chapters, not t.get("missing_chapters")),
            ("对照表无越界章号", not t.get("unexpected_chapters")),
        ]
    if args.synopsis:
        if not Path(args.synopsis).is_file():
            print("文件不存在：%s" % args.synopsis, file=sys.stderr)
            return 2
        s = analyze_synopsis(read(args.synopsis), args.chapters, args.require_geo_power)
        result["synopsis"] = s
        checks += [
            ("简写覆盖 1..%d 章" % args.chapters, not s["missing_chapters"]),
            ("简写无越界章号", not s["unexpected_chapters"]),
            ("剧情段均带〔时间〕标记", not s["missing_time_tags"]),
        ]
        if args.require_geo_power:
            checks.append(("剧情段均带【地理｜实力】标记", not s["missing_geo_power_tags"]))
    if args.table and args.synopsis:
        a = set(result["table"].get("chapter_numbers", []))
        b = set(result["synopsis"]["chapter_numbers"])
        result["cross_document"] = {
            "table_only": sorted(a - b),
            "synopsis_only": sorted(b - a),
        }
        checks.append(("两份文档章节集合一致", a == b))
    if not (args.table or args.synopsis):
        print("至少传 --table 或 --synopsis", file=sys.stderr)
        return 2

    result["checks"] = [{"name": n, "pass": bool(v)} for n, v in checks]
    result["pass"] = all(v for _, v in checks)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=== 交付物结构校验（章节总数 %d）===" % args.chapters)
        if "table" in result:
            t = result["table"]
            print("对照表：数据行 %d｜拆分行 %d｜列数异常 %d｜缺章 %s" %
                  (t["rows"], t["split_rows"], len(t["bad_col_rows"]),
                   t["missing_chapters"] or "无"))
        if "synopsis" in result:
            s = result["synopsis"]
            print("剧情简写：剧情段 %d｜缺〔〕%d｜缺【】%d｜缺章 %s" %
                  (s["plot_paragraphs"], len(s["missing_time_tags"]),
                   len(s["missing_geo_power_tags"]), s["missing_chapters"] or "无"))
            for x in s["missing_time_tags"][:5]:
                print("   缺时间标签：%s" % x)
            for x in s["missing_geo_power_tags"][:5]:
                print("   缺地理/实力标签：%s" % x)
        print("---")
        for n, v in checks:
            print("  [%s] %s" % ("PASS" if v else "FAIL", n))
        print("结论：%s" % ("PASS" if result["pass"] else "FAIL"))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
