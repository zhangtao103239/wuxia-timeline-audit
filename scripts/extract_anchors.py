#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic source-text inspection and anchor extraction for wuxia novels.

Reads a full-text novel, detects encoding and chapter structure, then scans a
keyword list in a single pass and reports every hit with its chapter and
verbatim context. No third-party dependencies; Python 3.8+.

Examples:
    python extract_anchors.py novel.txt --output anchors.md
    python extract_anchors.py novel.txt --list-chapters
    python extract_anchors.py novel.txt \
        --chapter-pattern '第(?P<num>[一二三四五六七八九十百]+)回\\s*(?P<title>\\S+)' \
        --keywords my_words.txt --keywords-mode replace
"""
from __future__ import annotations

import argparse
import bisect
import re
import sys
from pathlib import Path

ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5")

DEFAULT_PATTERNS = [
    ("网友整理版 第【N】段：第X章",
     r"第【(?P<num>\d+)】段：\s*第[一二三四五六七八九十百千零〇两]+章\s*(?P<title>\S+)"),
    ("章回体 第X回 回目",
     r"第(?P<num>[一二三四五六七八九十百千零〇两\d]+)回\s*(?P<title>\S+)"),
    ("现代分章 第X章 标题",
     r"第\s*(?P<num>\d+|[一二三四五六七八九十百千零〇两]+)\s*章\s*(?P<title>\S+)"),
    ("卷+章 卷X 第Y章 标题",
     r"卷[一二三四五六七八九十\d]+\s*第(?P<num>[一二三四五六七八九十百千零〇两\d]+)章\s*(?P<title>\S+)"),
]

# Generic starting vocabulary. Always extend it with work-specific terms
# (sects, techniques, place names, artifacts) via --keywords.
DEFAULT_KEYWORDS = [
    # season / weather
    "和风", "暮春", "初春", "初夏", "盛夏", "深秋", "隆冬", "新春", "残冬",
    "冰雪初销", "冰雪", "解冻", "酷暑", "天时", "春末", "秋末", "草长花秾",
    # calendar / relative time
    "腊月", "正月", "元夕", "清明", "中秋", "重九", "过年", "新年", "除夕",
    "三年后", "四个月后", "年后", "个月后", "年前", "年来", "数月", "半载",
    "数日", "十余日", "不一日", "当日", "次日", "翌日", "昨夜", "今晚",
    "第三日", "第七日", "百日", "早在一年之前", "每隔十天",
    # travel / distance
    "里路", "里许", "百里", "千里", "十来里", "相去不远", "疾驰", "兼程",
    "纵马", "雇船", "舟行", "舍舟登陆", "换骑", "渡江", "溯江", "东行",
    "北上", "南下", "连日连夜", "每天只睡", "行得", "不一日",
    # condition / power transfer
    "天下第一", "当世第一", "第一高手", "天下无敌", "不是敌手", "远非敌手",
    "联手", "已臻化境", "闭关", "面壁", "囚居", "地牢", "昏迷", "自宫",
    "逐出师门", "逐出门墙", "传位", "接任掌门", "气绝", "暴毙", "自尽",
    "圆寂", "遗命", "掌门", "令旗", "书信", "剑谱", "秘笈", "真气", "内力",
]

CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
      "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "廿": 20, "卅": 30}


def cn2num(raw):
    """Convert Chinese numerals (up to thousands) or ASCII digits to int."""
    if raw is None:
        return None
    s = raw.strip()
    if s.isdigit():
        return int(s)
    section, number, seen = 0, 0, False
    for ch in s:
        if ch in ("廿", "卅"):
            section += CN[ch]
            seen = True
        elif ch in CN:
            number = CN[ch]
            seen = True
        elif ch in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
            seen = True
        else:
            return None
    return section + number if seen else None


def read_text(path, encoding=None):
    raw = Path(path).read_bytes()
    candidates = [encoding] if encoding else list(ENCODINGS)
    for enc in candidates:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8 (replace)"


def find_chapters(text, custom=None):
    """Return (label, matches, numbers, titles) for the best chapter regex."""
    patterns = [("自定义", custom)] if custom else DEFAULT_PATTERNS
    best = None
    for label, pattern in patterns:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            print("正则无效 [%s]: %s" % (label, exc), file=sys.stderr)
            continue
        matches = list(rx.finditer(text))
        if not matches:
            continue
        numbers = []
        for m in matches:
            n = cn2num(m.groupdict().get("num"))
            if n is None:
                numbers = []
                break
            numbers.append(n)
        if not numbers:
            continue
        increasing = all(b > a for a, b in zip(numbers, numbers[1:]))
        score = (1 if increasing else 0, len(matches))
        if best is None or score > best[0]:
            titles = [(m.groupdict().get("title") or "").strip() for m in matches]
            best = (score, label, matches, numbers, titles)
    return best


def clean(s):
    s = s.replace("\u3000", "").replace("\r", "").replace("\n", "")
    s = re.sub(r"\(www\.[^)]*\)", "", s)
    return s.strip()


def load_keywords(spec, mode):
    if not spec:
        return list(dict.fromkeys(DEFAULT_KEYWORDS))
    p = Path(spec)
    if p.is_file():
        words = [l.strip() for l in p.read_text(encoding="utf-8-sig").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
    else:
        words = [w.strip() for w in re.split(r"[,，]", spec) if w.strip()]
    if mode == "replace":
        return list(dict.fromkeys(words))
    return list(dict.fromkeys(list(DEFAULT_KEYWORDS) + words))


def build_report(text, encoding, source, chapter_info, keywords, context, maxn):
    lines = ["# 原文体检与锚点报告", "",
             "- 文件：`%s`" % source,
             "- 编码：%s" % encoding,
             "- 字符数（含标点空白）：%s" % format(len(text), ",")]
    if chapter_info:
        label, matches, numbers, titles = chapter_info
        lines += ["- 章节结构：%s，共 %d 章" % (label, len(matches))]
    else:
        lines += ["- 章节结构：**未识别**（请传 `--chapter-pattern`；以下命中不标章号）"]
    lines += ["- 关键词数：%d" % len(keywords), "",
              "> 本报告只做定位。每条命中都须按证据分级核上下文："
              "A 硬锚点（原文逐字写明）／B 可推演（换算或估算）／C 无依据（删除）。", ""]

    starts = [m.start() for m in chapter_info[1]] if chapter_info else []
    nums = chapter_info[2] if chapter_info else []

    def chapter_of(pos):
        if not starts:
            return None
        i = bisect.bisect_right(starts, pos) - 1
        return nums[i] if i >= 0 else None

    if chapter_info:
        lines += ["## 章节结构", "", "| 章 | 名称 | 本段字符数 |", "|---|---|---|"]
        for i, (n, title) in enumerate(zip(chapter_info[2], chapter_info[3])):
            end = starts[i + 1] if i + 1 < len(starts) else len(text)
            lines.append("| %s | %s | %s |" % (n, title, format(end - starts[i], ",")))
        lines.append("")

    # One single pass over the text: longest keyword wins at each position.
    ordered = sorted(keywords, key=len, reverse=True)
    master = re.compile("|".join(re.escape(k) for k in ordered))
    buckets = {k: [] for k in ordered}
    for m in master.finditer(text):
        buckets[m.group(0)].append(m.start())

    lines += ["## 锚点命中", ""]
    for kw in keywords:
        hits = buckets.get(kw, [])
        if not hits:
            continue
        chapters = []
        for h in hits:
            c = chapter_of(h)
            if c is not None and c not in chapters:
                chapters.append(c)
        ch_label = "、".join(str(c) for c in chapters[:25])
        if len(chapters) > 25:
            ch_label += "…"
        lines += ["### %s（%d 次｜章节：%s）" % (kw, len(hits), ch_label or "—"), ""]
        for h in hits[:maxn]:
            before = clean(text[max(0, h - context):h])
            after = clean(text[h + len(kw):h + len(kw) + context])
            c = chapter_of(h)
            tag = "第 %s 章" % c if c is not None else "未分章"
            lines.append("- [%s] …%s**%s**%s…" % (tag, before, kw, after))
        if len(hits) > maxn:
            lines.append("- …另有 %d 处，未展开。" % (len(hits) - maxn))
        lines.append("")

    missing = [k for k in keywords if not buckets.get(k)]
    lines += ["## 未命中词（%d）" % len(missing), "",
              "、".join(missing) or "（无）", "",
              "---", "",
              "注：词表存在包含关系时按最长词优先计数，短词在此处可能少计；"
              "需精确计数时把该词单独用 `--keywords` 传入。"]
    return "\n".join(lines) + "\n"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="武侠小说原文体检与锚点提取")
    ap.add_argument("source", help="原文全文文件路径")
    ap.add_argument("--encoding", help="强制指定编码，默认自动检测")
    ap.add_argument("--chapter-pattern", help="自定义章节正则，须含命名组 num 与 title")
    ap.add_argument("--no-chapters", action="store_true", help="不解析章节，只做关键词检索")
    ap.add_argument("--list-chapters", action="store_true", help="只输出章节结构清单")
    ap.add_argument("--keywords", help="关键词文件路径（每行一词）或逗号分隔的词串")
    ap.add_argument("--keywords-mode", choices=("append", "replace"), default="append")
    ap.add_argument("--context", type=int, default=55, help="引文前后字数，默认 55")
    ap.add_argument("--max-per-keyword", type=int, default=3, help="每词展开条数，默认 3")
    ap.add_argument("--output", "-o", help="报告写入文件（默认输出到 stdout）")
    args = ap.parse_args()

    if not Path(args.source).is_file():
        print("文件不存在：%s" % args.source, file=sys.stderr)
        return 2
    text, encoding = read_text(args.source, args.encoding)
    chapter_info = None
    if not args.no_chapters:
        best = find_chapters(text, args.chapter_pattern)
        if best:
            chapter_info = (best[1], best[2], best[3], best[4])
        else:
            print("警告：未识别到章节结构，建议传 --chapter-pattern 或用 --no-chapters 降级。",
                  file=sys.stderr)

    if args.list_chapters:
        out = ["# 章节结构（%s｜%s）" % (Path(args.source).name, encoding), ""]
        if chapter_info:
            starts = [m.start() for m in chapter_info[1]]
            for i, (n, title) in enumerate(zip(chapter_info[2], chapter_info[3])):
                end = starts[i + 1] if i + 1 < len(starts) else len(text)
                out.append("%3d | %-12s | %s 字" % (n, title, format(end - starts[i], ",")))
        else:
            out.append("未识别到章节结构。")
        report = "\n".join(out) + "\n"
    else:
        keywords = load_keywords(args.keywords, args.keywords_mode)
        report = build_report(text, encoding, args.source, chapter_info, keywords,
                              args.context, args.max_per_keyword)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print("报告已写入：%s（%s 字符）" % (args.output, format(len(report), ",")))
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
