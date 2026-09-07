#!/usr/bin/env python3
"""Optional report export. Default plain layout preserves author content and links.
Explicit gs/bridgewater styles retain legacy branded layouts.
Requires python-docx, officecli and local Chrome for PDF conversion.
Validation runs before creating a deliverable; it is not a truth certification.
"""

import argparse
import json
import os
import re
import subprocess
import shutil
import sys
import tempfile
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# --- 1. Markdown 结构解析器 ---

def parse_markdown(md_text):
    lines = md_text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("# "):
            blocks.append({"type": "title", "text": line[2:].strip()})
            i += 1
            continue
        if line.startswith("调研时间：") or line.startswith("调研日期：") or line.startswith("调查窗口："):
            blocks.append({"type": "meta", "text": line})
            i += 1
            continue
        if line.startswith("## "):
            blocks.append({"type": "h1", "text": line[3:].strip()})
            i += 1
            continue
        if line.startswith("### "):
            blocks.append({"type": "h2", "text": line[4:].strip()})
            i += 1
            continue
        if line.startswith("#### "):
            blocks.append({"type": "h3", "text": line[5:].strip()})
            i += 1
            continue
        if line.startswith("|") and "|" in line:
            t_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                t_lines.append(lines[i].strip())
                i += 1
            rows = []
            for tl in t_lines:
                cells = [c.strip() for c in tl.strip("|").split("|")]
                if len(cells) >= 2 and not all(set(c) <= {'-', ':', ' '} for c in cells):
                    rows.append(cells)
            if rows:
                blocks.append({"type": "table", "rows": rows})
            continue
        if line.startswith("```"):
            code_lines = []
            lang = line[3:].strip()
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            blocks.append({"type": "code", "lang": lang, "lines": code_lines})
            continue
        if line in ("---", "***", "___"):
            i += 1
            continue
        if re.match(r"^(\*|\-|\d+\.)\s+", line):
            m = re.match(r"^(\*|\-|\d+\.)\s+(.*)", line)
            blocks.append({"type": "list_item", "bullet": m.group(1), "text": m.group(2)})
            i += 1
            continue
        blocks.append({"type": "p", "text": line})
        i += 1
    return blocks

def add_runs(p, text, font_name, size_pt, color_rgb, bold_color_rgb=None):
    parts = re.split(r'(\*\*.*?\*\*)', text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            r = p.add_run(part[2:-2])
            r.font.name = font_name
            r.bold = True
            r.font.size = Pt(size_pt)
            r.font.color.rgb = bold_color_rgb if bold_color_rgb else color_rgb
        else:
            if not part:
                continue
            sub_parts = re.split(r'(\[.*?\]\(.*?\)|https?://[^\s]+)', part)
            for sp in sub_parts:
                if sp.startswith("http://") or sp.startswith("https://"):
                    r = p.add_run(sp)
                    r.font.name = "Arial"
                    r.font.size = Pt(size_pt - 0.5)
                    r.font.color.rgb = RGBColor(70, 130, 180)
                else:
                    r = p.add_run(sp)
                    r.font.name = font_name
                    r.font.size = Pt(size_pt)
                    r.font.color.rgb = color_rgb

# --- 2. 动态关键指标提炼算法（绝无硬编码） ---

def extract_dynamic_kpi_stats(blocks, md_text):
    """从 Markdown 正文与执行摘要中动态提炼 3 个关键高价值数字指标及标签"""
    stats = []
    
    # 优先从执行摘要和前瞻行动列表中抽取带数字的要点
    candidates = []
    for b in blocks:
        if b["type"] == "list_item":
            txt = b["text"]
            # 匹配百分比、金额、区间等关键指标
            m_num = re.search(r'(\d+[\.\d]*\s*万[^\s，。]*|\d+[\.\d]*%\s*[-至~]\s*\d+[\.\d]*%|\d+[\.\d]*%[\+]?|[£€$]\s*[\d,]+[\+]?|约\s*[六七八九五四三二一\d]+成)', txt)
            m_bold = re.search(r'\*\*(.*?)\*\*', txt)
            if m_num and m_bold:
                num_str = m_num.group(1).strip()
                label_str = m_bold.group(1).split("：")[0].split(":")[0].strip()[:14]
                # 清洗描述
                clean_desc = re.sub(r'\*\*.*?\*\*', '', txt).strip("：: ，。")[:36]
                candidates.append((num_str, label_str, clean_desc))
    
    # 如果列表项不够，从段落里找
    if len(candidates) < 3:
        for b in blocks:
            if b["type"] == "p":
                txt = b["text"]
                matches = re.finditer(r'(\d+[\.\d]*\s*万[^\s，。]*|\d+[\.\d]*%\s*[-至~]\s*\d+[\.\d]*%|\d+[\.\d]*%[\+]?|[£€$]\s*[\d,]+[\+]?|约\s*[六七八九五四三二一\d]+成)', txt)
                for m in matches:
                    num_str = m.group(1).strip()
                    # 取数字周围的上下文作为简述
                    start = max(0, m.start() - 10)
                    end = min(len(txt), m.end() + 25)
                    snippet = txt[start:end].replace("**", "").strip()
                    candidates.append((num_str, "关键量化基准", snippet))
                    if len(candidates) >= 6:
                        break
                        
    # 选取去重后的前 3 个
    seen_nums = set()
    for num, lbl, desc in candidates:
        if num not in seen_nums and len(num) >= 2:
            seen_nums.add(num)
            stats.append((num, lbl, desc))
            if len(stats) == 3:
                break
                
    return stats

# --- 3. 风格匹配与自动判定 ---

def detect_best_style(inv_dir: Path) -> str:
    brief_p = inv_dir / "research_brief.yaml"
    if not brief_p.exists():
        return "gs"
    text = brief_p.read_text(encoding="utf-8").lower()
    if any(k in text for k in ["macro-finance", "索罗斯", "自反性", "对冲策略", "资产配置", "利率", "美债", "央行", "宏观"]):
        return "bridgewater"
    return "gs"

def resolve_status_label(inv_dir: Path, default_label: str = "Evidence-Bounded Analysis") -> str:
    contract_path = inv_dir / "report_contract.json"
    if contract_path.exists():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            overall = contract.get("overall_status", "")
            status_map = {
                "COMPLETE_DESCRIPTIVE": "Descriptive – Evidence Bounded",
                "COMPLETE_MECHANISTIC": "Mechanistic – Conditional",
                "COMPLETE_CAUSAL": "Causal – High Conviction",
                "PARTIAL_WITH_BOUNDED_CLAIMS": "Bounded Analysis – Conditional",
                "DATA_ACCESS_REQUIRED": "Exploratory – Data Access Required",
                "GAP_REPORT": "Gap Report – Insufficient Evidence"
            }
            return status_map.get(overall, default_label)
        except Exception:
            pass
    return default_label

# --- 4. 高盛投行风格生成器（动态版） ---

def render_goldman_sachs_docx(blocks, title_str, meta_str, out_docx: Path, dynamic_stats=None):
    doc = docx.Document()
    for s in doc.sections:
        s.top_margin = Inches(0.8)
        s.bottom_margin = Inches(0.8)
        s.left_margin = Inches(0.85)
        s.right_margin = Inches(0.85)
        s.header.is_linked_to_previous = False
        
        hp = s.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = hp.add_run("GLOBAL INVESTMENT RESEARCH ｜ STRATEGY & DECISION ANALYSIS")
        r.font.name = "Arial"
        r.font.size = Pt(7.5)
        r.font.color.rgb = RGBColor(120, 120, 120)
        
        fp = s.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fr = fp.add_run("Goldman Sachs & Co. LLC ｜ Global Research Group — Strictly Confidential")
        fr.font.name = "Arial"
        fr.font.size = Pt(7.5)
        fr.font.color.rgb = RGBColor(150, 150, 150)

    F_EN = "Calibri"
    F_ZH = "Microsoft YaHei"
    C_NAVY = RGBColor(10, 37, 64)
    C_STEEL = RGBColor(70, 130, 180)
    C_DARK = RGBColor(30, 41, 59)
    C_GRAY = RGBColor(100, 116, 139)
    C_TEXT = RGBColor(40, 40, 40)

    # 1. 动态机构抬头信息条
    header_tbl = doc.add_table(rows=1, cols=2)
    header_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    c_left = header_tbl.cell(0, 0)
    c_right = header_tbl.cell(0, 1)
    c_left.width = Inches(4.6)
    c_right.width = Inches(2.2)
    
    p_org = c_left.paragraphs[0]
    r_org = p_org.add_run(f"EXECUTIVE RESEARCH & STRATEGIC BRIEFING\n")
    r_org.font.name = "Arial"
    r_org.bold = True
    r_org.font.size = Pt(8.5)
    r_org.font.color.rgb = C_NAVY
    
    # 动态副标题从 meta 提炼
    clean_meta = meta_str if meta_str else "Observation Window: 2026-2031 ｜ Quantitative & Decision Analysis"
    r_sub = p_org.add_run(clean_meta[:65])
    r_sub.font.name = "Arial"
    r_sub.font.size = Pt(8)
    r_sub.font.color.rgb = C_GRAY
    
    p_meta = c_right.paragraphs[0]
    p_meta.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    # 动态状态头：读取 report_contract 动态判定，避免硬编码
    inv_dir = out_docx.parent
    header_label = resolve_status_label(inv_dir, default_label="Evidence-Bounded Analysis")
    r_m = p_meta.add_run(f"Strategic Research Group\n{header_label}\nComprehensive Due Diligence")
    table_index = 1
    batch_ops = [
        {"command": "set", "path": f"/body/tbl[{table_index}]/tr[1]/tc[1]", "props": {"border.bottom": "single;12;0A2540", "border.top": "none", "border.left": "none", "border.right": "none", "padding.bottom": 80}},
        {"command": "set", "path": f"/body/tbl[{table_index}]/tr[1]/tc[2]", "props": {"border.bottom": "single;12;0A2540", "border.top": "none", "border.left": "none", "border.right": "none", "padding.bottom": 80}},
    ]
    table_index += 1

    # 2. 标题
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(14)
    p_title.paragraph_format.space_after = Pt(6)
    r_t = p_title.add_run(title_str)
    r_t.font.name = F_ZH
    r_t.bold = True
    r_t.font.size = Pt(20)
    r_t.font.color.rgb = C_NAVY

    # 3. 动态核心指标橱窗（如果有 3 个指标则渲染，否则跳过）
    if dynamic_stats and len(dynamic_stats) == 3:
        stat_tbl = doc.add_table(rows=1, cols=3)
        stat_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for idx, (num, label, desc) in enumerate(dynamic_stats):
            cell = stat_tbl.cell(0, idx)
            cell.width = Inches(2.26)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            r_num = p.add_run(f"{num}\n")
            r_num.font.name = "Arial"
            r_num.bold = True
            r_num.font.size = Pt(16)
            r_num.font.color.rgb = C_NAVY
            r_lbl = p.add_run(f"{label}\n")
            r_lbl.font.name = F_ZH
            r_lbl.bold = True
            r_lbl.font.size = Pt(9)
            r_lbl.font.color.rgb = C_DARK
            r_desc = p.add_run(desc)
            r_desc.font.name = F_ZH
            r_desc.font.size = Pt(7.5)
            r_desc.font.color.rgb = C_GRAY
            
            batch_ops.append({
                "command": "set", "path": f"/body/tbl[{table_index}]/tr[1]/tc[{idx+1}]",
                "props": {"fill": "F8FAFC", "border.all": "single;4;E2E8F0", "padding.top": 120, "padding.bottom": 120, "padding.left": 100, "padding.right": 100}
            })
        table_index += 1
        doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # 4. 100% 完整正文遍历
    h1_count = 1
    for block in blocks:
        b_type = block["type"]
        if b_type in ("title", "meta"):
            continue
        elif b_type == "h1":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(16)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.keep_with_next = True
            
            r_num = p.add_run(f"{h1_count:02d} /  ")
            r_num.font.name = "Arial"
            r_num.bold = True
            r_num.font.size = Pt(13)
            r_num.font.color.rgb = C_STEEL
            
            r_txt = p.add_run(block["text"])
            r_txt.font.name = F_ZH
            r_txt.bold = True
            r_txt.font.size = Pt(13)
            r_txt.font.color.rgb = C_NAVY
            h1_count += 1
        elif b_type == "h2":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(11)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(block["text"])
            r.font.name = F_ZH
            r.bold = True
            r.font.size = Pt(11.5)
            r.font.color.rgb = C_DARK
        elif b_type == "h3":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(block["text"])
            r.font.name = F_ZH
            r.bold = True
            r.font.size = Pt(10.5)
            r.font.color.rgb = C_DARK
        elif b_type == "p":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2.5)
            p.paragraph_format.space_after = Pt(4.5)
            p.paragraph_format.line_spacing = 1.25
            add_runs(p, block["text"], F_ZH, 9.5, C_TEXT, C_NAVY)
        elif b_type == "list_item":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.left_indent = Inches(0.2)
            p.paragraph_format.line_spacing = 1.25
            bullet_str = block["bullet"]
            if bullet_str in ("-", "*"):
                r_b = p.add_run("•  ")
                r_b.font.name = "Arial"
                r_b.bold = True
                r_b.font.size = Pt(9.5)
                r_b.font.color.rgb = C_STEEL
            else:
                r_b = p.add_run(bullet_str + " ")
                r_b.font.name = "Arial"
                r_b.bold = True
                r_b.font.size = Pt(9.5)
                r_b.font.color.rgb = C_NAVY
            add_runs(p, block["text"], F_ZH, 9.5, C_TEXT, C_NAVY)
        elif b_type == "table":
            rows = block["rows"]
            tbl = doc.add_table(rows=len(rows), cols=len(rows[0]))
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            cur_idx = table_index
            table_index += 1
            for r_idx, row in enumerate(rows):
                for c_idx, val in enumerate(row):
                    cell = tbl.cell(r_idx, c_idx)
                    p = cell.paragraphs[0]
                    p.paragraph_format.line_spacing = 1.15
                    if r_idx == 0:
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        r = p.add_run(val)
                        r.font.name = F_ZH
                        r.bold = True
                        r.font.size = Pt(8.5)
                        r.font.color.rgb = RGBColor(255, 255, 255)
                        batch_ops.append({
                            "command": "set", "path": f"/body/tbl[{cur_idx}]/tr[1]/tc[{c_idx+1}]",
                            "props": {"fill": "0A2540", "border.top": "none", "border.left": "none", "border.right": "none", "border.bottom": "single;12;457B9D", "padding.top": 90, "padding.bottom": 90, "padding.left": 100, "padding.right": 100}
                        })
                    else:
                        r = p.add_run(val)
                        r.font.name = F_ZH
                        r.font.size = Pt(8.5)
                        if "★" in val:
                            r.bold = True
                            r.font.color.rgb = RGBColor(217, 119, 6)
                        elif "£" in val or "€" in val or "万" in val or "%" in val:
                            r.bold = True
                            r.font.color.rgb = C_NAVY
                        else:
                            r.font.color.rgb = C_TEXT
                        bg_col = "F8FAFC" if r_idx % 2 == 1 else "FFFFFF"
                        batch_ops.append({
                            "command": "set", "path": f"/body/tbl[{cur_idx}]/tr[{r_idx+1}]/tc[{c_idx+1}]",
                            "props": {"fill": bg_col, "border.top": "none", "border.left": "none", "border.right": "none", "border.bottom": "single;4;E2E8F0", "padding.top": 70, "padding.bottom": 70, "padding.left": 100, "padding.right": 100}
                        })
            doc.add_paragraph().paragraph_format.space_after = Pt(6)

    doc.save(out_docx)
    if batch_ops:
        subprocess.run(["officecli", "batch", str(out_docx), "--commands", json.dumps(batch_ops, ensure_ascii=False), "--json"], capture_output=True)

# --- 5. 桥水备忘录风格生成器（动态版） ---

def render_bridgewater_docx(blocks, title_str, meta_str, out_docx: Path):
    doc = docx.Document()
    for s in doc.sections:
        s.top_margin = Inches(0.85)
        s.bottom_margin = Inches(0.85)
        s.left_margin = Inches(0.95)
        s.right_margin = Inches(0.95)
        s.header.is_linked_to_previous = False
        
        hp = s.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = hp.add_run("MEMORANDUM  ｜  STRATEGY & DECISION COMMITTEE")
        r.font.name = "Georgia"
        r.font.size = Pt(7.5)
        r.font.color.rgb = RGBColor(100, 100, 100)
        
        fp = s.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fr = fp.add_run("Strictly Private & Confidential — For Decision Makers Only")
        fr.font.name = "Georgia"
        fr.font.size = Pt(7.5)
        fr.font.color.rgb = RGBColor(140, 140, 140)

    F_EN = "Georgia"
    F_ZH = "SimSun"
    C_BLACK = RGBColor(17, 24, 39)
    C_GRAY = RGBColor(75, 85, 99)
    C_TEXT = RGBColor(31, 41, 55)

    p_memo = doc.add_paragraph()
    p_memo.paragraph_format.space_before = Pt(4)
    p_memo.paragraph_format.space_after = Pt(2)
    r_m = p_memo.add_run("MEMORANDUM")
    r_m.font.name = F_EN
    r_m.bold = True
    r_m.font.size = Pt(24)
    r_m.font.color.rgb = C_BLACK

    memo_tbl = doc.add_table(rows=1, cols=2)
    memo_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    c1 = memo_tbl.cell(0, 0)
    c2 = memo_tbl.cell(0, 1)
    c1.width = Inches(3.3)
    c2.width = Inches(3.3)
    
    p1 = c1.paragraphs[0]
    p1.paragraph_format.line_spacing = 1.2
    # 动态提取日期：优先取“数据截至”后的日期，否则取最后一个日期，避免取到调查窗口起点2024
    m_data_cutoff = re.search(r'数据截至[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})', meta_str)
    if m_data_cutoff:
        date_display = m_data_cutoff.group(1)
    else:
        dates = re.findall(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})', meta_str)
        date_display = dates[-1] if dates else "31 August 2026"

    # 动态状态：从 report_contract 读取 overall_status，避免硬编码 High Conviction
    inv_dir = out_docx.parent
    status_label = resolve_status_label(inv_dir, default_label="Bounded Analysis – Conditional")

    r_to = p1.add_run(f"TO:       Executive Strategy & Decision Committee\nFROM:   Global Macro & Outbound Research\nDATE:   {date_display}")
    r_to.font.name = F_EN
    r_to.font.size = Pt(8.5)
    r_to.font.color.rgb = C_GRAY

    p2 = c2.paragraphs[0]
    p2.paragraph_format.line_spacing = 1.2
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    clean_subj = title_str if len(title_str) <= 32 else (title_str[:30] + "...")
    r_subj = p2.add_run(f"SUBJECT:  {clean_subj}\nFRAMEWORK: Causal Mechanisms & Decision Triggers\nSTATUS:     {status_label}")

    table_index = 1
    batch_ops = [
        {"command": "set", "path": f"/body/tbl[{table_index}]/tr[1]/tc[1]", "props": {"border.top": "single;12;111827", "border.bottom": "single;12;111827", "border.left": "none", "border.right": "none", "padding.top": 60, "padding.bottom": 60}},
        {"command": "set", "path": f"/body/tbl[{table_index}]/tr[1]/tc[2]", "props": {"border.top": "single;12;111827", "border.bottom": "single;12;111827", "border.left": "none", "border.right": "none", "padding.top": 60, "padding.bottom": 60}},
    ]
    table_index += 1
    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    roman_numerals = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
    h1_count = 0

    for block in blocks:
        b_type = block["type"]
        if b_type in ("title", "meta"):
            continue
        elif b_type == "h1":
            rom = roman_numerals[h1_count] if h1_count < len(roman_numerals) else str(h1_count+1)
            h1_count += 1
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(15)
            p.paragraph_format.space_after = Pt(5)
            p.paragraph_format.keep_with_next = True
            r_rom = p.add_run(f"{rom}.  ")
            r_rom.font.name = F_EN
            r_rom.bold = True
            r_rom.font.size = Pt(12)
            r_rom.font.color.rgb = C_BLACK
            r_txt = p.add_run(block["text"])
            r_txt.font.name = F_ZH
            r_txt.bold = True
            r_txt.font.size = Pt(12)
            r_txt.font.color.rgb = C_BLACK
        elif b_type == "h2":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(block["text"])
            r.font.name = F_ZH
            r.bold = True
            r.font.size = Pt(11)
            r.font.color.rgb = C_BLACK
        elif b_type == "h3":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(block["text"])
            r.font.name = F_ZH
            r.bold = True
            r.font.size = Pt(10)
            r.font.color.rgb = C_GRAY
        elif b_type == "p":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(4.5)
            p.paragraph_format.line_spacing = 1.25
            add_runs(p, block["text"], F_ZH, 9.5, C_TEXT, C_BLACK)
        elif b_type == "list_item":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.left_indent = Inches(0.18)
            p.paragraph_format.line_spacing = 1.25
            bullet_str = block["bullet"]
            r_b = p.add_run("•  " if bullet_str in ("-", "*") else (bullet_str + " "))
            r_b.font.name = F_EN
            r_b.bold = True
            r_b.font.size = Pt(9.5)
            r_b.font.color.rgb = C_BLACK
            add_runs(p, block["text"], F_ZH, 9.5, C_TEXT, C_BLACK)
        elif b_type == "table":
            rows = block["rows"]
            tbl = doc.add_table(rows=len(rows), cols=len(rows[0]))
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            cur_idx = table_index
            table_index += 1
            for r_idx, row in enumerate(rows):
                for c_idx, val in enumerate(row):
                    cell = tbl.cell(r_idx, c_idx)
                    p = cell.paragraphs[0]
                    p.paragraph_format.line_spacing = 1.15
                    if r_idx == 0:
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        r = p.add_run(val)
                        r.font.name = F_ZH
                        r.bold = True
                        r.font.size = Pt(8.5)
                        r.font.color.rgb = RGBColor(255, 255, 255)
                        batch_ops.append({
                            "command": "set", "path": f"/body/tbl[{cur_idx}]/tr[1]/tc[{c_idx+1}]",
                            "props": {"fill": "111827", "border.top": "single;12;111827", "border.bottom": "single;12;111827", "border.left": "none", "border.right": "none", "padding.top": 80, "padding.bottom": 80, "padding.left": 100, "padding.right": 100}
                        })
                    else:
                        r = p.add_run(val)
                        r.font.name = F_ZH
                        r.font.size = Pt(8.5)
                        if "★" in val or "£" in val or "€" in val or "万" in val or "%" in val:
                            r.bold = True
                        r.font.color.rgb = C_TEXT
                        batch_ops.append({
                            "command": "set", "path": f"/body/tbl[{cur_idx}]/tr[{r_idx+1}]/tc[{c_idx+1}]",
                            "props": {"fill": "FFFFFF", "border.top": "none", "border.left": "none", "border.right": "none", "border.bottom": "single;4;D1D5DB", "padding.top": 60, "padding.bottom": 60, "padding.left": 100, "padding.right": 100}
                        })
            doc.add_paragraph().paragraph_format.space_after = Pt(6)

    doc.save(out_docx)
    if batch_ops:
        subprocess.run(["officecli", "batch", str(out_docx), "--commands", json.dumps(batch_ops, ensure_ascii=False), "--json"], capture_output=True)

# --- 6. 统一导出引擎 ---

def render_plain_docx(blocks, out_docx):
    """Preserve the author's content without invented branding, KPIs or boilerplate."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    document = docx.Document()
    normal = document.styles['Normal']
    normal.font.name = 'Arial'
    normal.font.size = Pt(11)
    normal.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.2
    def inline(p, text):
        for piece in re.split(r'(\[[^\]]+\]\(https?://[^\s)]+\)|\*\*.*?\*\*)', text):
            match = re.fullmatch(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', piece)
            if match:
                link = OxmlElement('w:hyperlink')
                link.set(qn('r:id'), p.part.relate_to(match[2], RT.HYPERLINK, is_external=True))
                run = OxmlElement('w:r'); props = OxmlElement('w:rPr')
                color = OxmlElement('w:color'); color.set(qn('w:val'), '245B8A'); props.append(color)
                run.append(props); node = OxmlElement('w:t'); node.text = match[1]; run.append(node)
                link.append(run); p._p.append(link)
            else:
                run = p.add_run(piece[2:-2] if piece.startswith('**') and piece.endswith('**') else piece)
                run.bold = piece.startswith('**') and piece.endswith('**')
    for block in blocks:
        kind = block['type']
        if kind == 'table':
            rows = block['rows']; table = document.add_table(rows=len(rows), cols=max(map(len, rows)))
            table.style = 'Table Grid'
            for i, row in enumerate(rows):
                for j, value in enumerate(row): inline(table.cell(i,j).paragraphs[0], value)
        elif kind == 'code':
            # Preserve diagram source instead of silently dropping it; visual rendering is separate.
            inline(document.add_paragraph(), '\n'.join(block['lines']))
        else:
            level = {'title': 0, 'h1': 1, 'h2': 2, 'h3': 3}.get(kind)
            p = document.add_heading('', level=level) if level is not None else document.add_paragraph()
            if kind == 'list_item':
                p.style = 'List Number' if block['bullet'][0].isdigit() else 'List Bullet'
            inline(p, block.get('text',''))
    document.save(str(out_docx))


def convert_docx_to_pdf(docx_path: Path, pdf_path: Path):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp_html:
        tmp_html_path = Path(tmp_html.name)
    try:
        proc = subprocess.run(["officecli", "view", str(docx_path), "html"], capture_output=True, text=True, check=True)
        tmp_html_path.write_text(proc.stdout, encoding="utf-8")
        chrome_cmd = [
            CHROME_PATH,
            "--headless",
            "--disable-gpu",
            f"--print-to-pdf={pdf_path}",
            "--print-to-pdf-no-header",
            str(tmp_html_path)
        ]
        subprocess.run(chrome_cmd, capture_output=True, text=True, check=True)
    finally:
        if tmp_html_path.exists():
            tmp_html_path.unlink()

def export_single_report(inv_dir: Path, report_md: Path, style_choice="auto", copy_to_desktop=False):
    """导出单份 Markdown 报告为 Word/PDF（内部复用）。"""
    if report_md.resolve().parent != inv_dir.resolve():
        print("[FAIL] 报告必须位于被校验调查目录内", file=sys.stderr)
        return 1
    md_text = report_md.read_text(encoding="utf-8")
    blocks = parse_markdown(md_text)
    
    title_str = "深度调查战略报告"
    meta_str = ""
    for b in blocks:
        if b["type"] == "title":
            title_str = b["text"]
        elif b["type"] == "meta":
            meta_str = b["text"]
            
    dynamic_stats = extract_dynamic_kpi_stats(blocks, md_text)
    
    resolved_style = "plain" if style_choice == "auto" else style_choice
    # Validate the actual file before creating deliverables. Export is never a way around review.
    try:
        from tools.validate import speak
    except ImportError:
        from validate import speak
    if speak(inv_dir, report_md.name).errors:
        return 1

    # 输出文件名与报告名联动：final_report.md -> final_report.docx/pdf；final_report_brief.md -> final_report_brief.docx/pdf
    stem = report_md.stem  # 不含后缀
    out_docx = inv_dir / f"{stem}.docx"
    out_pdf = inv_dir / f"{stem}.pdf"
    
    if resolved_style == "plain":
        render_plain_docx(blocks, out_docx)
    elif resolved_style == "bridgewater":
        render_bridgewater_docx(blocks, title_str, meta_str, out_docx)
    else:
        render_goldman_sachs_docx(blocks, title_str, meta_str, out_docx, dynamic_stats=dynamic_stats)
        
    convert_docx_to_pdf(out_docx, out_pdf)
    print(f"[OK] 研报 Word 生成完毕: {out_docx}")
    print(f"[OK] 研报 PDF 生成完毕: {out_pdf}")
    
    # 文件夹内部生成具名最终交付件
    variant = "" if stem == "final_report" else f"_{stem}"
    named_pdf = inv_dir / f"{inv_dir.name}{variant}_最终交付研报.pdf"
    named_docx = inv_dir / f"{inv_dir.name}{variant}_最终交付研报.docx"
    try:
        shutil.copy2(out_pdf, named_pdf)
        shutil.copy2(out_docx, named_docx)
        print(f"[OK] 目录内最终交付件已生成: {named_pdf.name}")
    except OSError as exc:
        print(f"[FAIL] 交付件复制失败: {exc}", file=sys.stderr)
        return 1
    
    if copy_to_desktop:
        desktop = Path("/Users/qiaozhi/Desktop")
        # both 时桌面文件带上 brief/full 区分，单文件时保持兼容旧命名
        suffix = f"_{stem}" if stem != "final_report" else ""
        dt_pdf = desktop / f"{inv_dir.name}{suffix}_最终交付研报.pdf"
        dt_docx = desktop / f"{inv_dir.name}{suffix}_最终交付研报.docx"
        subprocess.run(["cp", str(out_pdf), str(dt_pdf)], check=True)
        subprocess.run(["cp", str(out_docx), str(dt_docx)], check=True)
        print(f"[OK] 已将最终交付件同步至桌面:\n  • {dt_pdf}\n  • {dt_docx}")
    return 0

def export_investigation_report(inv_dir: Path, style_choice="auto", copy_to_desktop=False, report_file=None, export_all=False):
    inv_dir = Path(inv_dir).resolve()
    # --all：同时导出 brief/full（若存在）以及默认 final_report.md
    if export_all:
        candidates = []
        for name in ["final_report_brief.md", "final_report_full.md", "final_report.md"]:
            p = inv_dir / name
            if p.exists():
                candidates.append(p)
        if not candidates:
            print(f"[FAIL] 未找到任何报告文件: {inv_dir}/final_report*.md", file=sys.stderr)
            return 1
        ret = 0
        for p in candidates:
            print(f"[INFO] 正在导出: {p.name}")
            r = export_single_report(inv_dir, p, style_choice, copy_to_desktop)
            ret = ret or r
        return ret
    # --file：导出指定文件
    if report_file:
        report_md = inv_dir / report_file if not Path(report_file).is_absolute() else Path(report_file)
        # 若传入的是相对路径且不在 inv_dir 下，尝试按文件名在 inv_dir 中查找
        if not report_md.exists():
            report_md = inv_dir / Path(report_file).name
        if not report_md.exists():
            print(f"[FAIL] 未找到报告文件: {report_md}", file=sys.stderr)
            return 1
        return export_single_report(inv_dir, report_md, style_choice, copy_to_desktop)
    # 默认：final_report.md（兼容存量）
    report_md = inv_dir / "final_report.md"
    if not report_md.exists():
        print(f"[FAIL] 未找到报告文件: {report_md}", file=sys.stderr)
        return 1
    return export_single_report(inv_dir, report_md, style_choice, copy_to_desktop)
def main():
    parser = argparse.ArgumentParser(description="一键将调研报告导出为高定研报 PDF 与 Word（支持 brief/detailed 双版本）")
    parser.add_argument("inv_dir", type=str, help="调查目录 (如 investigations/ai-pm-grad-school-roi-2026)")
    parser.add_argument("--style", choices=["auto", "plain", "gs", "bridgewater"], default="auto", help="排版风格（auto/plain 为朴素正文；机构风格需显式指定）")
    parser.add_argument("--to-desktop", action="store_true", default=False, help="同步拷贝一份至桌面")
    parser.add_argument("--file", dest="report_file", type=str, default=None, help="指定报告文件名（如 final_report_brief.md / final_report_full.md），默认 final_report.md")
    parser.add_argument("--all", dest="export_all", action="store_true", default=False, help="同时导出目录下所有报告变体（final_report.md + final_report_brief.md + final_report_full.md）")
    args = parser.parse_args()
    
    sys.exit(export_investigation_report(Path(args.inv_dir), args.style, args.to_desktop, report_file=args.report_file, export_all=args.export_all))
if __name__ == "__main__":
    main()
