"""把 README.md 转成 Word 文档（README.docx）。

md 在编辑器里看着还行，但要发给别人、或者在手机上翻，Word 更省事。
Markdown 只用到有限的几种语法，这里手写个小转换器就够，不引额外的库。

用法：python tools/md_to_docx.py
改完 README.md 后重跑一次即可。
"""
from __future__ import annotations

import os
import re
import sys

from docx import Document
from docx.shared import Pt, RGBColor

# 行内标记：**粗体** 和 `等宽`
INLINE_RE = re.compile(r"\*\*(?P<bold>[^*]+)\*\*|`(?P<code>[^`]+)`")
MONO = "Consolas"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def add_runs(paragraph, text: str) -> None:
    """按行内标记把一段文字拆成带样式的 run。"""
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        if m.group("bold"):
            paragraph.add_run(m.group("bold")).bold = True
        else:
            run = paragraph.add_run(m.group("code"))
            run.font.name = MONO
            run.font.color.rgb = RGBColor(0x99, 0x33, 0x33)
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def is_separator_row(cells) -> bool:
    """表格的 |---|---| 分隔行。"""
    return all(set(c) <= set("-: ") and c for c in cells)


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def convert(md_path: str, docx_path: str) -> None:
    doc = Document()
    # 正文默认字号调小一点，中文用雅黑看着舒服些
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)

    lines = open(md_path, encoding="utf-8").read().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.strip().startswith("```"):               # 代码块
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                p = doc.add_paragraph()
                run = p.add_run(lines[i])
                run.font.name = MONO
                run.font.size = Pt(9)
                p.paragraph_format.space_after = Pt(0)
                i += 1
            i += 1
            continue

        if line.startswith("|"):                         # 表格
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = split_row(lines[i])
                if not is_separator_row(cells):
                    rows.append(cells)
                i += 1
            if not rows:
                continue
            table = doc.add_table(rows=len(rows), cols=len(rows[0]))
            table.style = "Table Grid"
            for r, cells in enumerate(rows):
                for c, text in enumerate(cells):
                    cell = table.cell(r, c)
                    cell.text = ""
                    add_runs(cell.paragraphs[0], text)
                    if r == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
            doc.add_paragraph()
            continue

        if line.startswith("#"):                         # 标题
            level = len(line) - len(line.lstrip("#"))
            doc.add_heading(line.lstrip("#").strip(), level=min(level, 4))
            i += 1
            continue

        if line.startswith("  - "):                      # 二级列表
            add_runs(doc.add_paragraph(style="List Bullet 2"), line[4:])
            i += 1
            continue

        if line.startswith("- ") or line.startswith("* "):   # 列表
            add_runs(doc.add_paragraph(style="List Bullet"), line[2:])
            i += 1
            continue

        if not line.strip():                             # 空行
            i += 1
            continue

        block = []                                       # 普通段落（连续行合一段）
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(
                ("|", "#", "- ", "  - ", "```")):
            block.append(lines[i].strip())
            i += 1
        add_runs(doc.add_paragraph(), " ".join(block))

    doc.save(docx_path)


def main() -> int:
    md = os.path.join(ROOT, "README.md")
    out = os.path.join(ROOT, "README.docx")
    if not os.path.exists(md):
        print(f"找不到 {md}")
        return 1
    convert(md, out)
    print(f"已生成 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
