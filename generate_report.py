"""
JBM ERP AI Agent — Technical Report Generator
Generates: docs/rapport_technique_jbm.pdf
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white, black, lightgrey, Color
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer,
    HRFlowable, PageBreak, KeepTogether, Flowable
)
from reportlab.graphics.shapes import (
    Drawing, Rect, String, Line, Group, Polygon
)
from reportlab.graphics import renderPDF
from reportlab.pdfgen import canvas

# ─── Colour palette ──────────────────────────────────────────────────────────
BLUE        = HexColor("#2563eb")
TEAL        = HexColor("#0d9488")
DARK_HEADER = HexColor("#0f172a")
LIGHT_GRAY  = HexColor("#f1f5f9")
MID_GRAY    = HexColor("#e2e8f0")
DARK_GRAY   = HexColor("#475569")
TEXT_COLOR  = HexColor("#1e293b")
WHITE       = white
GREEN       = HexColor("#16a34a")
ORANGE      = HexColor("#ea580c")
AMBER       = HexColor("#d97706")

# ─── Page dimensions ─────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4          # 595.28 x 841.89 pts
MARGIN = 2 * cm

# ─── Styles ──────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

_custom_styles = {}

def make_style(name, **kwargs):
    base = kwargs.pop("parent", "Normal")
    if base in _custom_styles:
        parent = _custom_styles[base]
    else:
        parent = styles[base]
    s = ParagraphStyle(name, parent=parent, **kwargs)
    _custom_styles[name] = s
    return s

COVER_TITLE  = make_style("CoverTitle",  fontSize=26, textColor=WHITE,
                           alignment=TA_CENTER, fontName="Helvetica-Bold",
                           leading=34, spaceAfter=10)
COVER_SUB    = make_style("CoverSub",    fontSize=14, textColor=HexColor("#93c5fd"),
                           alignment=TA_CENTER, fontName="Helvetica",
                           leading=20, spaceAfter=6)
COVER_LABEL  = make_style("CoverLabel",  fontSize=11, textColor=HexColor("#cbd5e1"),
                           alignment=TA_CENTER, fontName="Helvetica", leading=16)
COVER_INFO   = make_style("CoverInfo",   fontSize=12, textColor=WHITE,
                           alignment=TA_CENTER, fontName="Helvetica-Bold", leading=18)

SEC_HEADER   = make_style("SecHeader",   fontSize=13, textColor=WHITE,
                           fontName="Helvetica-Bold", leading=18, spaceAfter=4)
SUBSEC       = make_style("SubSec",      fontSize=11, textColor=BLUE,
                           fontName="Helvetica-Bold", leading=16,
                           spaceBefore=14, spaceAfter=6)
BODY         = make_style("Body",        fontSize=10, textColor=TEXT_COLOR,
                           fontName="Helvetica", leading=14,
                           spaceBefore=4, spaceAfter=4)
BODY_JUSTIFY = make_style("BodyJ",       fontSize=10, textColor=TEXT_COLOR,
                           fontName="Helvetica", leading=14,
                           alignment=TA_JUSTIFY, spaceBefore=3, spaceAfter=3)
SMALL        = make_style("Small",       fontSize=8,  textColor=DARK_GRAY,
                           fontName="Helvetica", leading=11)
TABLE_HEADER = make_style("TH",          fontSize=9,  textColor=WHITE,
                           fontName="Helvetica-Bold", leading=12, alignment=TA_CENTER)
TABLE_CELL   = make_style("TC",          fontSize=9,  textColor=TEXT_COLOR,
                           fontName="Helvetica", leading=12)
TABLE_CELL_C = make_style("TCC",         fontSize=9,  textColor=TEXT_COLOR,
                           fontName="Helvetica", leading=12, alignment=TA_CENTER)
CAPTION      = make_style("Caption",     fontSize=9,  textColor=DARK_GRAY,
                           fontName="Helvetica", leading=12, alignment=TA_CENTER,
                           spaceBefore=4, spaceAfter=8)

# ─── Helper: section header block ────────────────────────────────────────────
def section_header(label):
    """Dark-background section banner."""
    return [
        Spacer(1, 10),
        _SectionBanner(label),
        Spacer(1, 6),
    ]

class _SectionBanner(Flowable):
    def __init__(self, text, height=24):
        Flowable.__init__(self)
        self.text   = text
        self.height = height
        self.width  = PAGE_W - 2 * MARGIN

    def draw(self):
        c = self.canv
        c.setFillColor(DARK_HEADER)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.setFillColor(BLUE)
        c.rect(0, 0, 4, self.height, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(10, 7, self.text)

# ─── Helper: subsection ──────────────────────────────────────────────────────
def sub(text):
    return Paragraph(text, SUBSEC)

def body(text):
    return Paragraph(text, BODY_JUSTIFY)

def sp(h=6):
    return Spacer(1, h)

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=MID_GRAY, spaceAfter=6)

# ─── Helper: styled table ────────────────────────────────────────────────────
def styled_table(data, col_widths=None, header_rows=1):
    t = Table(data, colWidths=col_widths, repeatRows=header_rows)
    n_rows = len(data)
    style_cmds = [
        ("BACKGROUND",  (0, 0), (-1, header_rows - 1), DARK_HEADER),
        ("TEXTCOLOR",   (0, 0), (-1, header_rows - 1), WHITE),
        ("FONTNAME",    (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, header_rows - 1), 9),
        ("ALIGN",       (0, 0), (-1, header_rows - 1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME",    (0, header_rows), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, header_rows), (-1, -1), 9),
        ("ROWBACKGROUND",(0, header_rows), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("GRID",        (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("LINEBELOW",   (0, header_rows - 1), (-1, header_rows - 1), 1.5, BLUE),
    ]
    # Alternate row shading
    for i in range(header_rows, n_rows):
        bg = LIGHT_GRAY if i % 2 == 0 else WHITE
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
    t.setStyle(TableStyle(style_cmds))
    return t


# ─── Diagram helpers ─────────────────────────────────────────────────────────
def draw_rect(d, x, y, w, h, fill_color, label, label_color=WHITE, font_size=8, stroke_color=None):
    sc = stroke_color or fill_color
    d.add(Rect(x, y, w, h, fillColor=fill_color, strokeColor=sc, strokeWidth=0.8))
    d.add(String(x + w/2, y + h/2 - font_size/2.5, label,
                 textAnchor="middle", fontSize=font_size,
                 fillColor=label_color, fontName="Helvetica-Bold"))

def draw_arrow_v(d, x, y_top, y_bot, color=DARK_GRAY):
    d.add(Line(x, y_top, x, y_bot + 6, strokeColor=color, strokeWidth=1.2))
    d.add(Polygon([x-4, y_bot+6, x+4, y_bot+6, x, y_bot],
                  fillColor=color, strokeColor=color, strokeWidth=0.5))

def draw_arrow_h(d, x_left, x_right, y, color=DARK_GRAY, label=""):
    d.add(Line(x_left, y, x_right - 6, y, strokeColor=color, strokeWidth=1.2))
    d.add(Polygon([x_right-6, y+4, x_right-6, y-4, x_right, y],
                  fillColor=color, strokeColor=color, strokeWidth=0.5))
    if label:
        mid = (x_left + x_right) / 2
        d.add(String(mid, y + 3, label, textAnchor="middle",
                     fontSize=7, fillColor=color, fontName="Helvetica"))

# ─── Architecture Diagram ────────────────────────────────────────────────────
def make_architecture_diagram():
    W, H = 460, 340
    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, fillColor=HexColor("#f8fafc"), strokeColor=MID_GRAY, strokeWidth=0.5))

    # Layer labels x
    LX, LW = 5, 60

    layers = [
        (290, 310, HexColor("#dbeafe"), "FRONTEND"),
        (220, 285, HexColor("#dcfce7"), "API LAYER"),
        (100, 215, HexColor("#ede9fe"), "AGENT LAYER"),
        (30,  95,  HexColor("#fef9c3"), "DATA LAYER"),
        (5,   25,  HexColor("#fee2e2"), "EXTERNAL"),
    ]
    for (y0, y1, col, lbl) in layers:
        d.add(Rect(0, y0, W, y1-y0, fillColor=col, strokeColor=MID_GRAY, strokeWidth=0.5))
        d.add(String(4, (y0+y1)/2 - 4, lbl, fontSize=6, fillColor=DARK_GRAY,
                     fontName="Helvetica-Bold", textAnchor="start"))

    # ── Frontend layer ──
    draw_rect(d, 80,  296, 120, 18, BLUE,            "Chat Interface (HTML/JS)", font_size=7)
    draw_rect(d, 270, 296, 130, 18, TEAL,            "BI Dashboards (Streamlit)", font_size=7)

    # ── API layer ──
    draw_rect(d, 80,  230, 120, 18, HexColor("#16a34a"), "FastAPI /chat", font_size=7)
    draw_rect(d, 270, 230, 130, 18, HexColor("#0369a1"),  "Session Management", font_size=7)

    # ── Agent layer ──
    draw_rect(d, 175, 170, 120, 22, DARK_HEADER, "Supervisor Agent", font_size=8)
    draw_rect(d, 70,  125, 110, 22, BLUE,        "CRM Specialist",   font_size=7)
    draw_rect(d, 300, 125, 120, 22, TEAL,        "Invoice Specialist", font_size=7)
    draw_rect(d, 175, 108, 120, 18, HexColor("#7c3aed"), "RAG Retriever", font_size=7)

    # ── Data layer ──
    draw_rect(d, 45,  46, 100, 22, HexColor("#b45309"), "PostgreSQL DB",    font_size=7)
    draw_rect(d, 185, 46, 100, 22, HexColor("#7c3aed"), "ChromaDB Vectors", font_size=7)
    draw_rect(d, 330, 46, 100, 22, HexColor("#0369a1"), "Data Warehouse",   font_size=7)

    # ── External layer ──
    draw_rect(d, 130, 8, 100, 16, HexColor("#dc2626"), "qwen2.5:7b (Ollama)", font_size=6)
    draw_rect(d, 280, 8, 110, 16, HexColor("#dc2626"), "nomic-embed-text",    font_size=6)

    # ── Arrows ──
    # Frontend -> API
    draw_arrow_v(d, 230, 293, 250)
    # API -> Agent
    draw_arrow_v(d, 230, 227, 194)
    # Supervisor -> CRM
    d.add(Line(175, 181, 125, 147, strokeColor=BLUE, strokeWidth=1.2))
    d.add(Polygon([121,150, 129,144, 125,147], fillColor=BLUE, strokeColor=BLUE))
    # Supervisor -> Invoice
    d.add(Line(295, 181, 350, 147, strokeColor=TEAL, strokeWidth=1.2))
    d.add(Polygon([346,150, 354,144, 350,147], fillColor=TEAL, strokeColor=TEAL))
    # Supervisor -> RAG
    draw_arrow_v(d, 235, 169, 127)
    # Agent layer -> Data
    draw_arrow_v(d, 125, 124, 68)
    draw_arrow_v(d, 235, 107, 68)
    draw_arrow_v(d, 360, 124, 68)
    # RAG -> ChromaDB
    draw_arrow_v(d, 245, 107, 68)
    # Data -> External
    draw_arrow_v(d, 180, 45, 25)
    draw_arrow_v(d, 335, 45, 25)

    return d


# ─── Request Flow Diagram ────────────────────────────────────────────────────
def make_request_flow():
    W, H = 460, 260
    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, fillColor=HexColor("#f8fafc"), strokeColor=MID_GRAY, strokeWidth=0.4))

    steps = [
        (1,  "User sends message in Chat UI",          HexColor("#dbeafe")),
        (2,  "POST /chat -> FastAPI",                  HexColor("#dcfce7")),
        (3,  "Input validated (error_handler.py)",     HexColor("#dcfce7")),
        (4,  "Session history loaded from PostgreSQL", HexColor("#ede9fe")),
        (5,  "run_agent() called in supervisor.py",    HexColor("#ede9fe")),
        (6,  "RAG: embed query, top-5 chunks from ChromaDB", HexColor("#fef9c3")),
        (7,  "Message enriched with RAG context",      HexColor("#fef9c3")),
        (8,  "LLM classifies intent, routes to specialist", HexColor("#ede9fe")),
        (9,  "Specialist calls appropriate tool",      HexColor("#dbeafe")),
        (10, "Tool queries PostgreSQL operational DB", HexColor("#fee2e2")),
        (11, "Result formatted and returned",          HexColor("#dcfce7")),
        (12, "Response saved to session history",      HexColor("#dcfce7")),
        (13, "Response returned to frontend",          HexColor("#dbeafe")),
    ]

    col_w = 210
    row_h = 18
    gap   = 2
    cols  = 2
    rows_per_col = 7

    for i, (num, label, col) in enumerate(steps):
        col_idx = 0 if i < rows_per_col else 1
        row_idx = i if i < rows_per_col else i - rows_per_col
        x = 10 + col_idx * (col_w + 30)
        y = H - 30 - row_idx * (row_h + gap)
        d.add(Rect(x, y, col_w, row_h, fillColor=col,
                   strokeColor=MID_GRAY, strokeWidth=0.5))
        d.add(Rect(x, y, 22, row_h, fillColor=BLUE,
                   strokeColor=BLUE, strokeWidth=0))
        d.add(String(x + 11, y + 5, str(num), textAnchor="middle",
                     fontSize=8, fillColor=WHITE, fontName="Helvetica-Bold"))
        d.add(String(x + 26, y + 5, label, textAnchor="start",
                     fontSize=7, fillColor=TEXT_COLOR, fontName="Helvetica"))
        if row_idx < rows_per_col - 1 and i < len(steps) - 1:
            draw_arrow_v(d, x + col_w/2, y, y - gap - 2)

    # Connect col 1 bottom to col 2 top
    x1 = 10 + col_w / 2
    x2 = 10 + col_w + 30 + col_w / 2
    y_bottom_col1 = H - 30 - (rows_per_col - 1) * (row_h + gap)
    y_top_col2    = H - 30
    # Horizontal connector
    d.add(Line(x1, y_bottom_col1, x1, y_bottom_col1 - 12,
               strokeColor=DARK_GRAY, strokeWidth=1))
    d.add(Line(x1, y_bottom_col1 - 12, x2, y_bottom_col1 - 12,
               strokeColor=DARK_GRAY, strokeWidth=1))
    draw_arrow_v(d, x2, y_top_col2 + (row_h + gap), y_top_col2 + row_h + 4)

    return d


# ─── Multi-Agent Routing Diagram ─────────────────────────────────────────────
def make_routing_diagram():
    W, H = 460, 200
    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, fillColor=HexColor("#f8fafc"),
               strokeColor=MID_GRAY, strokeWidth=0.4))

    # User
    draw_rect(d, 10, 165, 90, 24, BLUE, "User Message", font_size=8)
    # Supervisor
    draw_rect(d, 160, 165, 130, 24, DARK_HEADER, "Supervisor Agent", font_size=8)
    draw_arrow_h(d, 100, 160, 177, label="POST /chat")

    # CRM branch
    draw_rect(d, 70, 100, 110, 22, BLUE, "CRM Specialist", font_size=7)
    draw_rect(d, 70, 55, 110, 22, HexColor("#0369a1"), "CRM Tools", font_size=7)
    draw_rect(d, 70, 10, 110, 22, HexColor("#b45309"), "PostgreSQL", font_size=7)

    # CRM label
    d.add(Line(195, 165, 125, 122, strokeColor=BLUE, strokeWidth=1.2))
    d.add(Polygon([121,125, 129,119, 125,122], fillColor=BLUE, strokeColor=BLUE))
    d.add(String(130, 138, "[CRM]", fontSize=7, fillColor=BLUE,
                 fontName="Helvetica-Bold", textAnchor="middle"))
    draw_arrow_v(d, 125, 99, 78)
    draw_arrow_v(d, 125, 54, 33)

    # Invoice branch
    draw_rect(d, 280, 100, 130, 22, TEAL, "Invoice Specialist", font_size=7)
    draw_rect(d, 280, 55, 130, 22, HexColor("#0d9488"), "Invoice Tools", font_size=7)
    draw_rect(d, 280, 10, 130, 22, HexColor("#b45309"), "PostgreSQL", font_size=7)

    d.add(Line(290, 165, 345, 122, strokeColor=TEAL, strokeWidth=1.2))
    d.add(Polygon([341,125, 349,119, 345,122], fillColor=TEAL, strokeColor=TEAL))
    d.add(String(340, 138, "[INVOICING]", fontSize=7, fillColor=TEAL,
                 fontName="Helvetica-Bold", textAnchor="middle"))
    draw_arrow_v(d, 345, 99, 78)
    draw_arrow_v(d, 345, 54, 33)

    # General
    draw_rect(d, 180, 100, 80, 22, DARK_GRAY, "Direct LLM", font_size=7)
    d.add(Line(225, 165, 220, 122, strokeColor=DARK_GRAY, strokeWidth=1))
    d.add(Polygon([216,125, 224,119, 220,122], fillColor=DARK_GRAY, strokeColor=DARK_GRAY))
    d.add(String(208, 138, "[GENERAL]", fontSize=7, fillColor=DARK_GRAY,
                 fontName="Helvetica-Bold", textAnchor="middle"))

    return d


# ─── RAG Diagram ─────────────────────────────────────────────────────────────
def make_rag_diagram():
    W, H = 460, 200
    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, fillColor=HexColor("#f8fafc"),
               strokeColor=MID_GRAY, strokeWidth=0.4))

    # OFFLINE phase label
    d.add(Rect(5, 140, 220, 54, fillColor=HexColor("#ede9fe"),
               strokeColor=HexColor("#7c3aed"), strokeWidth=0.8))
    d.add(String(115, 183, "EMBEDDING PHASE (offline)", textAnchor="middle",
                 fontSize=7, fillColor=HexColor("#7c3aed"), fontName="Helvetica-Bold"))

    warehouse_cols = ["fact_activities", "fact_deals", "dim_client", "fact_revenue"]
    for i, lbl in enumerate(warehouse_cols):
        x = 8 + i * 54
        draw_rect(d, x, 145, 50, 16, HexColor("#0369a1"), lbl, font_size=5.5)

    draw_arrow_v(d, 115, 143, 124)
    draw_rect(d, 55, 108, 120, 18, HexColor("#7c3aed"), "nomic-embed-text (Ollama)", font_size=7)
    draw_arrow_v(d, 115, 107, 88)
    draw_rect(d, 55, 72, 120, 18, HexColor("#4f46e5"), "ChromaDB (./chroma_db/)", font_size=7)

    # Collections
    draw_rect(d, 30, 48, 78, 18, BLUE, "CRM: 160,123 vec", font_size=6.5)
    draw_rect(d, 120, 48, 78, 18, TEAL, "Invoice: 2,376 vec", font_size=6.5)
    d.add(Line(85, 71, 69, 67, strokeColor=BLUE, strokeWidth=1))
    d.add(Line(145, 71, 159, 67, strokeColor=TEAL, strokeWidth=1))

    # ONLINE phase
    d.add(Rect(235, 80, 220, 110, fillColor=HexColor("#dcfce7"),
               strokeColor=HexColor("#16a34a"), strokeWidth=0.8))
    d.add(String(345, 180, "RETRIEVAL PHASE (every query)", textAnchor="middle",
                 fontSize=7, fillColor=HexColor("#16a34a"), fontName="Helvetica-Bold"))

    draw_rect(d, 240, 145, 90, 18, BLUE, "User Query", font_size=7)
    draw_arrow_h(d, 330, 360, 154)
    draw_rect(d, 360, 145, 88, 18, HexColor("#7c3aed"), "Embed (nomic)", font_size=7)
    draw_arrow_v(d, 404, 144, 124)
    draw_rect(d, 360, 108, 88, 18, HexColor("#4f46e5"), "Cosine Search", font_size=7)
    draw_arrow_v(d, 404, 107, 88)
    draw_rect(d, 360, 72, 88, 18, HexColor("#16a34a"), "Top-5 Chunks", font_size=7)
    draw_arrow_v(d, 404, 71, 52)
    draw_rect(d, 360, 36, 88, 18, DARK_HEADER, "Inject in Prompt", font_size=7)

    # Agent
    draw_rect(d, 240, 36, 100, 18, DARK_HEADER, "Specialist Agent", font_size=7)
    draw_arrow_h(d, 340, 360, 45)

    return d


# ─── ETL Pipeline Diagram ────────────────────────────────────────────────────
def make_etl_diagram():
    W, H = 460, 160
    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, fillColor=HexColor("#f8fafc"),
               strokeColor=MID_GRAY, strokeWidth=0.4))

    sources = ["raw_clients.xlsx", "raw_deals.xlsx", "raw_activities.xlsx", "raw_invoices.xlsx"]
    targets = ["dim_client", "fact_deals", "fact_activities", "fact_revenue"]
    colors  = [BLUE, TEAL, HexColor("#7c3aed"), HexColor("#ea580c")]

    row_h = 22
    y_base = 120
    for i, (src, tgt, col) in enumerate(zip(sources, targets, colors)):
        y = y_base - i * (row_h + 4)
        draw_rect(d, 5,  y, 100, row_h, col, src, font_size=6.5)
        draw_arrow_h(d, 105, 155, y + row_h/2, label="extract")
        draw_rect(d, 155, y, 120, row_h, HexColor("#f1f5f9"), "Transform + Clean",
                  label_color=DARK_HEADER, font_size=6.5,
                  stroke_color=MID_GRAY)
        draw_arrow_h(d, 275, 325, y + row_h/2, label="load")
        draw_rect(d, 325, y, 100, row_h, col, f"warehouse.{tgt}", font_size=6.5)

    # dim_date
    draw_rect(d, 325, 4, 100, 18, HexColor("#0369a1"), "warehouse.dim_date", font_size=6)
    d.add(Line(375, 22, 375, 18+4, strokeColor=HexColor("#0369a1"), strokeWidth=0.8))

    return d


# ─── Star Schema Diagram ─────────────────────────────────────────────────────
def make_star_schema():
    W, H = 460, 300
    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, fillColor=HexColor("#f8fafc"),
               strokeColor=MID_GRAY, strokeWidth=0.4))

    # Center: FACT_DEALS
    cx, cy = 180, 145
    fw, fh = 140, 80
    d.add(Rect(cx - fw/2, cy - fh/2, fw, fh, fillColor=DARK_HEADER,
               strokeColor=BLUE, strokeWidth=1.5))
    d.add(String(cx, cy + fh/2 - 12, "FACT_DEALS", textAnchor="middle",
                 fontSize=9, fillColor=WHITE, fontName="Helvetica-Bold"))
    fact_fields = ["deal_key, deal_ref", "company_name, deal_title",
                   "value_tnd, status, stage", "days_to_close, year, quarter"]
    for i, f in enumerate(fact_fields):
        d.add(String(cx, cy + fh/2 - 24 - i*11, f, textAnchor="middle",
                     fontSize=6.5, fillColor=HexColor("#93c5fd"), fontName="Helvetica"))

    # DIM_DATE (top)
    draw_rect(d, 130, 240, 100, 55, HexColor("#0369a1"), "", font_size=7)
    d.add(String(180, 282, "DIM_DATE", textAnchor="middle",
                 fontSize=8, fillColor=WHITE, fontName="Helvetica-Bold"))
    for i, f in enumerate(["date_key, full_date", "day, week, month",
                            "quarter, year", "is_weekend, is_holiday"]):
        d.add(String(180, 272 - i*10, f, textAnchor="middle",
                     fontSize=6, fillColor=HexColor("#bae6fd"), fontName="Helvetica"))
    d.add(Line(180, 240, 180, 185, strokeColor=HexColor("#0369a1"), strokeWidth=1.2))

    # DIM_CLIENT (left)
    draw_rect(d, 5, 115, 100, 60, HexColor("#16a34a"), "", font_size=7)
    d.add(String(55, 163, "DIM_CLIENT", textAnchor="middle",
                 fontSize=8, fillColor=WHITE, fontName="Helvetica-Bold"))
    for i, f in enumerate(["client_key", "canonical_name", "industry, city",
                            "status, company_size"]):
        d.add(String(55, 153 - i*10, f, textAnchor="middle",
                     fontSize=6, fillColor=HexColor("#bbf7d0"), fontName="Helvetica"))
    d.add(Line(105, 145, 110, 145, strokeColor=HexColor("#16a34a"), strokeWidth=1.2))

    # FACT_REVENUE (right, below center)
    draw_rect(d, 310, 115, 140, 80, HexColor("#ea580c"), "", font_size=7)
    d.add(String(380, 183, "FACT_REVENUE", textAnchor="middle",
                 fontSize=8, fillColor=WHITE, fontName="Helvetica-Bold"))
    for i, f in enumerate(["revenue_id, invoice_number", "company_name, invoice_date",
                            "total_amount, status", "payment_delay_days, is_overdue"]):
        d.add(String(380, 173 - i*11, f, textAnchor="middle",
                     fontSize=6.5, fillColor=HexColor("#fed7aa"), fontName="Helvetica"))
    d.add(Line(250, 145, 310, 145, strokeColor=HexColor("#ea580c"), strokeWidth=1.2))

    # FACT_ACTIVITIES (bottom)
    draw_rect(d, 70, 10, 220, 65, HexColor("#7c3aed"), "", font_size=7)
    d.add(String(180, 62, "FACT_ACTIVITIES", textAnchor="middle",
                 fontSize=8, fillColor=WHITE, fontName="Helvetica-Bold"))
    for i, f in enumerate(["activity_id, company_name", "activity_type, activity_date",
                            "outcome, description", "churn_signal, positive_signal"]):
        d.add(String(180, 52 - i*11, f, textAnchor="middle",
                     fontSize=6.5, fillColor=HexColor("#ddd6fe"), fontName="Helvetica"))
    d.add(Line(180, 75, 180, 105, strokeColor=HexColor("#7c3aed"), strokeWidth=1.2))

    # DIM_DATE -> FACT_REVENUE
    d.add(Line(230, 268, 380, 195, strokeColor=HexColor("#0369a1"),
               strokeWidth=0.8, strokeDashArray=[3,2]))
    # DIM_CLIENT -> FACT_REVENUE
    d.add(Line(105, 145, 310, 155, strokeColor=HexColor("#16a34a"),
               strokeWidth=0.8, strokeDashArray=[3,2]))

    return d


# ─── Write Operation Flow ─────────────────────────────────────────────────────
def make_write_flow():
    W, H = 460, 170
    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, fillColor=HexColor("#f8fafc"),
               strokeColor=MID_GRAY, strokeWidth=0.4))

    items = [
        ('User: "Create deal for Tunisie Telecom — 50,000 TND"', BLUE),
        ('Agent: create_deal(confirmed=False) -> PREVIEW returned', DARK_GRAY),
        ('User sees confirmation prompt, replies "yes"', HexColor("#16a34a")),
        ('Supervisor detects confirmation + pending WARNING in history', HexColor("#d97706")),
        ('Agent: create_deal(confirmed=True) -> DB write + audit_log', TEAL),
        ('Response: "OK: Deal created (ID: 314)"', HexColor("#16a34a")),
    ]
    for i, (label, col) in enumerate(items):
        y = H - 22 - i * 24
        d.add(Rect(5, y, W-10, 20, fillColor=col,
                   strokeColor=col, strokeWidth=0, rx=3))
        d.add(String(14, y+6, label, textAnchor="start",
                     fontSize=7.5, fillColor=WHITE, fontName="Helvetica"))
        if i < len(items) - 1:
            draw_arrow_v(d, W/2, y, y - 5)

    return d


# ─── PDF page callbacks ───────────────────────────────────────────────────────
FOOTER_TEXT_FR = "JBM ERP AI Agent — Documentation Technique — Mars 2026"
FOOTER_TEXT_EN = "JBM ERP AI Agent System — Technical Documentation — March 2026"
FOOTER_TEXT    = FOOTER_TEXT_FR   # default; overridden per build

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DARK_HEADER)
    canvas.rect(MARGIN, 1.0*cm - 6, PAGE_W - 2*MARGIN, 18, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(MARGIN + 6, 1.0*cm, FOOTER_TEXT)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawRightString(PAGE_W - MARGIN - 6, 1.0*cm, f"Page {doc.page}")
    canvas.restoreState()


def on_cover_page(canvas, doc):
    # Full dark background
    canvas.setFillColor(DARK_HEADER)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # Blue accent stripe
    canvas.setFillColor(BLUE)
    canvas.rect(0, PAGE_H - 8, PAGE_W, 8, fill=1, stroke=0)
    canvas.rect(0, 0, PAGE_W, 6, fill=1, stroke=0)
    # Side stripe
    canvas.setFillColor(BLUE)
    canvas.rect(0, 0, 6, PAGE_H, fill=1, stroke=0)
    canvas.rect(PAGE_W-6, 0, 6, PAGE_H, fill=1, stroke=0)


# ─── Document class with first-page override ─────────────────────────────────
class TwoPageTemplateDoc(SimpleDocTemplate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def handle_pageBegin(self):
        super().handle_pageBegin()

    def afterFlowable(self, flowable):
        pass


# ─── Cover page content ───────────────────────────────────────────────────────
def build_cover(lang="fr"):
    is_fr = (lang == "fr")
    cover = []
    cover.append(sp(110))

    # Main title line
    cover.append(Paragraph(
        "Systeme Agentique ERP" if is_fr else "ERP Agentic System",
        COVER_TITLE
    ))
    # Sub-title (company name)
    cover.append(Paragraph("JBM Consulting", make_style(
        f"CT2_{lang}", parent="CoverTitle",
        fontSize=20, textColor=HexColor("#94a3b8"),
        fontName="Helvetica-Bold", alignment=TA_CENTER, leading=28)))
    cover.append(sp(28))

    # Thin divider — no colour, just a subtle light line
    cover.append(HRFlowable(width="40%", thickness=0.8, color=HexColor("#334155"),
                             hAlign="CENTER", spaceAfter=28))

    # Report type label
    label_text = "Rapport d'Avancement" if is_fr else "Progress Report"
    cover.append(Paragraph(label_text, make_style(
        f"CLbl_{lang}", parent="Normal",
        fontSize=13, textColor=HexColor("#64748b"),
        fontName="Helvetica", alignment=TA_CENTER, leading=18)))
    cover.append(sp(60))

    # Author name — prominent
    cover.append(Paragraph("Jihed Ben Messaoud", make_style(
        f"CAuth_{lang}", parent="Normal",
        fontSize=14, textColor=WHITE,
        fontName="Helvetica-Bold", alignment=TA_CENTER, leading=20)))
    cover.append(sp(8))

    # Date
    date_text = "Mars 2026" if is_fr else "March 2026"
    cover.append(Paragraph(date_text, make_style(
        f"CDate_{lang}", parent="Normal",
        fontSize=10, textColor=HexColor("#64748b"),
        fontName="Helvetica", alignment=TA_CENTER, leading=14)))

    cover.append(PageBreak())
    return cover


# ─── Section 1 ───────────────────────────────────────────────────────────────
def build_section1():
    s = []
    s += section_header("Section 1 — Project Overview")

    s.append(sub("1.1 Context and Objectives"))
    s.append(body(
        "The JBM ERP AI Agent is a natural language interface built on top of an enterprise "
        "resource planning (ERP) system for JBM Consulting, a fictional Tunisian IT firm. "
        "Instead of navigating complex forms and reports, business users type questions in "
        "plain language and receive structured, data-backed answers in real time."
    ))
    s.append(body(
        "The system covers two core ERP modules: Customer Relationship Management (CRM) and "
        "Invoicing. A multi-agent architecture, powered by LangChain and a local LLM "
        "(qwen2.5:7b via Ollama), routes each user query to the correct specialist agent. "
        "Retrieval-Augmented Generation (RAG) enriches every response with semantic context "
        "drawn from a 160k-vector ChromaDB store built on top of the data warehouse."
    ))
    s.append(body(
        "Key innovations include: (1) an LLM-based supervisor agent that routes queries to "
        "specialist agents; (2) a write-confirmation safety pattern for all mutating "
        "operations; (3) a fully local, privacy-preserving stack (no cloud LLM required); "
        "and (4) an Apache Airflow ETL pipeline that ingests, cleans, and loads ~403k raw "
        "rows into a star-schema data warehouse."
    ))
    s.append(sp(8))

    s.append(sub("1.2 Technology Stack"))
    stack_data = [
        [Paragraph("Layer", TABLE_HEADER), Paragraph("Technology", TABLE_HEADER),
         Paragraph("Version", TABLE_HEADER), Paragraph("Purpose", TABLE_HEADER)],
        ["LLM",                 "qwen2.5:7b via Ollama",    "local",    "Natural language understanding and routing"],
        ["Agent Framework",     "LangChain",                "0.2.16",   "Agent orchestration and tool calling"],
        ["Vector Store",        "ChromaDB",                 "0.4.x",    "RAG embeddings storage"],
        ["Embedding Model",     "nomic-embed-text",         "local",    "Text vectorization (768 dims)"],
        ["Backend API",         "FastAPI",                  "latest",   "REST endpoints and session handling"],
        ["Database",            "PostgreSQL",               "16",       "Operational + warehouse data"],
        ["ORM",                 "SQLAlchemy",               "2.0",      "Database access layer"],
        ["ETL Orchestration",   "Apache Airflow",           "2.8.1",    "Pipeline scheduling and monitoring"],
        ["Data Processing",     "pandas",                   "2.0.3",    "ETL transformations"],
        ["Fuzzy Matching",      "rapidfuzz",                "3.6.1",    "Company name deduplication"],
        ["Dashboard",           "Streamlit",                "latest",   "BI visualizations"],
        ["Charts",              "Plotly",                   "latest",   "Interactive charts"],
        ["Frontend",            "HTML / CSS / JavaScript",  "—",        "Single-page chat interface"],
        ["Containerization",    "Docker",                   "—",        "Airflow deployment"],
    ]
    cw = [90, 110, 55, 220]
    s.append(styled_table(stack_data, col_widths=cw))
    s.append(sp(6))
    return s


# ─── Section 2 ───────────────────────────────────────────────────────────────
def build_section2():
    s = []
    s += section_header("Section 2 — System Architecture")

    s.append(sub("2.1 Overall Architecture Diagram"))
    s.append(body(
        "The system is structured in five horizontal layers: the user-facing frontend (Chat UI "
        "and Streamlit dashboards), the FastAPI REST layer, the multi-agent orchestration layer, "
        "the data layer (PostgreSQL + ChromaDB + Data Warehouse), and the external Ollama "
        "runtime hosting both the LLM and embedding model."
    ))
    s.append(sp(4))
    d = make_architecture_diagram()
    s.append(d)
    s.append(Paragraph("Figure 1 — Five-layer system architecture", CAPTION))

    s.append(sub("2.2 Multi-Agent Routing Diagram"))
    s.append(body(
        "The Supervisor Agent uses LLM-based routing via the supervisor agent to classify "
        "each incoming query and dispatch it to the appropriate specialist. The result is "
        "routed to the CRM Specialist, the Invoicing Specialist, or handled directly as a "
        "general response."
    ))
    s.append(sp(4))
    s.append(make_routing_diagram())
    s.append(Paragraph("Figure 2 — Multi-agent routing flow", CAPTION))

    s.append(sub("2.3 Request Flow — Step by Step"))
    s.append(body(
        "Every user message triggers a 13-step processing pipeline from the chat interface "
        "through to the final response. RAG context is injected at step 6, ensuring that "
        "the specialist agent receives semantically relevant warehouse context before "
        "tool invocation."
    ))
    s.append(sp(4))
    s.append(make_request_flow())
    s.append(Paragraph("Figure 3 — End-to-end request processing flow", CAPTION))
    return s


# ─── Section 3 ───────────────────────────────────────────────────────────────
def build_section3():
    s = []
    s += section_header("Section 3 — Data Architecture")

    s.append(sub("3.1 Raw Data Sources"))
    raw_data = [
        [Paragraph("File", TABLE_HEADER), Paragraph("Rows", TABLE_HEADER),
         Paragraph("Description", TABLE_HEADER), Paragraph("Key Issues for ETL", TABLE_HEADER)],
        ["raw_clients.xlsx",    "98,133",   "Companies and contacts",   "Name variations, format noise, duplicates"],
        ["raw_deals.xlsx",      "75,944",   "Sales pipeline history",   "Value formats, stage variations"],
        ["raw_activities.xlsx", "200,000",  "CRM activity log",         "Date formats (12+ variants), outcome variations"],
        ["raw_invoices.xlsx",   "29,017",   "Billing records",          "Math errors, duplicate invoice numbers"],
        [Paragraph("<b>TOTAL</b>", TABLE_CELL), Paragraph("<b>403,094</b>", TABLE_CELL_C), "—", "—"],
    ]
    s.append(styled_table(raw_data, col_widths=[120, 60, 140, 165]))
    s.append(sp(6))

    s.append(sub("3.2 ETL Pipeline Diagram"))
    s.append(body(
        "The ETL pipeline reads from raw Excel files, applies data quality transformations, "
        "and loads clean records into the warehouse schema. Key transformations include company "
        "name standardization (rapidfuzz, threshold >= 85%), date normalization across 12+ "
        "formats, currency standardization (TND), deal value parsing for mixed formats "
        "(e.g., '50k', 'cinquante mille' -> 50000.0 TND), tax recalculation, "
        "and duplicate removal."
    ))
    s.append(sp(4))
    s.append(make_etl_diagram())
    s.append(Paragraph("Figure 4 — ETL pipeline from raw Excel files to warehouse schema", CAPTION))

    s.append(sub("3.3 Data Warehouse Star Schema"))
    s.append(body(
        "The warehouse follows a star schema with three fact tables (fact_deals, fact_revenue, "
        "fact_activities) connected to shared dimension tables (dim_client, dim_date). "
        "All monetary values are stored in TND."
    ))
    s.append(sp(4))
    s.append(make_star_schema())
    s.append(Paragraph("Figure 5 — Star schema: fact and dimension tables", CAPTION))

    s.append(sub("3.4 Warehouse Statistics"))
    wh_data = [
        [Paragraph("Table", TABLE_HEADER), Paragraph("Rows", TABLE_HEADER),
         Paragraph("Description", TABLE_HEADER)],
        ["warehouse.dim_client",      "16,547",  "Unique deduplicated client/contact records"],
        ["warehouse.fact_deals",      "8,000",   "Cleaned unique deal records"],
        ["warehouse.fact_activities", "200,000", "CRM interaction log with churn signals"],
        ["warehouse.fact_revenue",    "2,376",   "Invoice records with payment status"],
        ["warehouse.dim_date",        "1,461",   "Date dimension 2023-2026 incl. Tunisian holidays"],
        [Paragraph("<b>TOTAL</b>", TABLE_CELL),
         Paragraph("<b>227,984</b>", TABLE_CELL_C),
         "Clean warehouse rows loaded from 403,094 raw records"],
    ]
    s.append(styled_table(wh_data, col_widths=[160, 70, 245]))
    s.append(sp(6))
    return s


# ─── Section 4 ───────────────────────────────────────────────────────────────
def build_section4():
    s = []
    s += section_header("Section 4 — RAG System")

    s.append(sub("4.1 RAG Architecture"))
    s.append(body(
        "The Retrieval-Augmented Generation system operates in two phases. In the offline "
        "embedding phase, warehouse records are chunked (500 chars, 50 overlap), embedded "
        "via nomic-embed-text (Ollama, 274 MB, 768 dimensions), and stored in ChromaDB with "
        "cosine similarity. In the online retrieval phase, each user query is embedded and "
        "the top-5 most similar chunks are prepended to the specialist agent's prompt."
    ))
    s.append(sp(4))
    s.append(make_rag_diagram())
    s.append(Paragraph("Figure 6 — RAG embedding and retrieval pipeline", CAPTION))

    s.append(sub("4.2 Why RAG is Necessary"))
    rag_why = [
        [Paragraph("Challenge", TABLE_HEADER), Paragraph("Without RAG", TABLE_HEADER),
         Paragraph("With RAG", TABLE_HEADER)],
        ["Synonym handling",  '"workers" != "employees" — missed',   "Semantic similarity resolves aliases"],
        ["Client knowledge",  "Only structured DB fields",           "Meeting notes, call history retrieved"],
        ["Churn detection",   "Not possible from SQL alone",         "Activity patterns retrieved semantically"],
        ["Answer depth",      "Shallow, field-level answers",        "Evidence-based, context-rich responses"],
        ["Historical context","Point-in-time DB snapshot only",      "3-year interaction history surfaced"],
    ]
    s.append(styled_table(rag_why, col_widths=[130, 160, 185]))
    s.append(sp(6))

    s.append(sub("4.3 Embedding Statistics"))
    emb_data = [
        [Paragraph("Parameter", TABLE_HEADER), Paragraph("Value", TABLE_HEADER)],
        ["Total vectors in ChromaDB",   "162,499"],
        ["CRM collection (jbm_crm)",    "160,123 documents"],
        ["Invoicing collection (jbm_invoicing)", "2,376 documents"],
        ["Embedding model",             "nomic-embed-text (Ollama, local, 274 MB)"],
        ["Vector dimensions",           "768"],
        ["Similarity metric",           "Cosine"],
        ["Chunk size",                  "500 characters"],
        ["Chunk overlap",               "50 characters"],
        ["Source tables",               "fact_activities, fact_deals, dim_client, fact_revenue"],
    ]
    s.append(styled_table(emb_data, col_widths=[220, 255]))
    s.append(sp(6))
    return s


# ─── Section 5 ───────────────────────────────────────────────────────────────
def build_section5():
    s = []
    s += section_header("Section 5 — Agent System")

    s.append(sub("5.1 CRM Module Tools (12 tools)"))
    crm_tools = [
        [Paragraph("Tool Name", TABLE_HEADER), Paragraph("Operation", TABLE_HEADER),
         Paragraph("Description", TABLE_HEADER)],
        ["list_companies",    "READ",  "List companies with filters (name, city, status)"],
        ["get_company",       "READ",  "Get full company details by name or ID"],
        ["list_deals",        "READ",  "List deals filtered by status or company"],
        ["get_total_sales",   "READ",  "Aggregate sales with date and status filters"],
        ["get_pipeline_summary","READ","Pipeline statistics by stage"],
        ["list_contacts",     "READ",  "List contacts filtered by company"],
        ["list_activities",   "READ",  "List CRM activities with date/type filters"],
        ["create_company",    "WRITE", "Create new company (two-phase confirmation)"],
        ["create_contact",    "WRITE", "Create contact linked to company"],
        ["create_deal",       "WRITE", "Create new deal opportunity (with confirmation)"],
        ["update_deal_status","WRITE", "Update deal status or stage"],
        ["create_activity",   "WRITE", "Schedule CRM activity (call, meeting, email)"],
    ]
    s.append(styled_table(crm_tools, col_widths=[130, 65, 280]))
    s.append(sp(6))

    s.append(sub("5.2 Invoicing Module Tools (6 tools)"))
    inv_tools = [
        [Paragraph("Tool Name", TABLE_HEADER), Paragraph("Operation", TABLE_HEADER),
         Paragraph("Description", TABLE_HEADER)],
        ["list_invoices",     "READ",  "List invoices filtered by status or company"],
        ["get_invoice",       "READ",  "Get invoice details with all line items"],
        ["get_revenue_summary","READ", "Revenue aggregation by period in TND"],
        ["create_invoice",    "WRITE", "Create invoice with line items (confirmation)"],
        ["mark_invoice_paid", "WRITE", "Record payment against invoice"],
        ["send_invoice",      "WRITE", "Mark invoice as sent to client"],
    ]
    s.append(styled_table(inv_tools, col_widths=[130, 65, 280]))
    s.append(sp(6))

    s.append(sub("5.3 Write Operation Safety Flow"))
    s.append(body(
        "All mutating operations (create, update, mark paid) follow a mandatory two-phase "
        "confirmation pattern. The first tool call with confirmed=False returns a preview. "
        "The second call, after the user confirms, executes the write and appends an "
        "immutable audit_log entry."
    ))
    s.append(sp(4))
    s.append(make_write_flow())
    s.append(Paragraph("Figure 7 — Two-phase write confirmation flow", CAPTION))
    s.append(sp(6))

    s.append(sub("5.4 Error Handling"))
    err_data = [
        [Paragraph("Error Type", TABLE_HEADER), Paragraph("Where Caught", TABLE_HEADER),
         Paragraph("User-Facing Message", TABLE_HEADER)],
        ["DB Connection Failed",   "handle_db_error()",    "Database temporarily unavailable"],
        ["Tool Execution Failed",  "handle_tool_error()",  "Operation failed, please retry"],
        ["Agent Timeout",          "handle_agent_error()", "Could not complete request in time"],
        ["Empty Input",            "validate_user_input()","Please enter a message"],
        ["Rate Limit",             "handle_agent_error()", "AI service rate limit reached"],
    ]
    s.append(styled_table(err_data, col_widths=[150, 150, 175]))
    s.append(sp(6))
    return s


# ─── Section 6 ───────────────────────────────────────────────────────────────
def build_section6():
    s = []
    s += section_header("Section 6 — Business Context — JBM Consulting")

    s.append(sub("6.1 Company Profile"))
    profile = [
        [Paragraph("Attribute", TABLE_HEADER), Paragraph("Value", TABLE_HEADER)],
        ["Company Name",    "JBM Consulting (fictional Tunisian IT firm)"],
        ["Sector",          "IT Consulting and Solutions"],
        ["Location",        "Tunis, Tunisia"],
        ["Period Covered",  "January 2023 — March 2026"],
        ["Services",        "Data/BI, AI Integration, Cloud Infrastructure"],
        ["Team Size",       "8 employees (2023) to 31 employees (2025)"],
        ["Revenue Growth",  "~400,000 TND (2023) to ~1,800,000 TND (2025)"],
    ]
    s.append(styled_table(profile, col_widths=[160, 315]))
    s.append(sp(6))

    s.append(sub("6.2 Three-Year Growth Arc"))
    growth = [
        [Paragraph("Year", TABLE_HEADER), Paragraph("Phase", TABLE_HEADER),
         Paragraph("Team", TABLE_HEADER), Paragraph("Win Rate", TABLE_HEADER),
         Paragraph("Key Milestone", TABLE_HEADER)],
        ["2023",    "Startup",     "8 employees",  "28%",  "Initial client base, small contracts"],
        ["2024",    "Growth",      "18 employees", "38%",  "Landed Tunisie Telecom, enterprise entry"],
        ["2025",    "Established", "31 employees", "50%+", "Enterprise portfolio, recurring revenue"],
        ["2026 Q1", "Expansion",   "31+ employees","~61%", "Strong pipeline, forecast positive"],
    ]
    s.append(styled_table(growth, col_widths=[55, 75, 95, 70, 180]))
    s.append(sp(6))

    s.append(sub("6.3 Key Business Metrics from Warehouse"))
    kpi = [
        [Paragraph("Metric", TABLE_HEADER), Paragraph("Value", TABLE_HEADER)],
        ["Total Deals in Warehouse",   "8,000"],
        ["Overall Win Rate",           "49.9%"],
        ["Won Deals",                  "2,269"],
        ["Lost Deals",                 "1,411"],
        ["Active Pipeline — Prospecting", "1,613 deals"],
        ["Active Pipeline — Proposal",    "922 deals"],
        ["Active Pipeline — Negotiation", "554 deals"],
        ["Total Invoices",             "2,376"],
        ["Paid Invoices",              "1,845 (77.6%)"],
        ["Pending Invoices",           "386 (16.2%)"],
        ["Overdue Invoices",           "29 (1.2%)"],
        ["Cancelled Invoices",         "116 (4.9%)"],
        ["Total CRM Activities",       "200,000 interactions over 3 years"],
        ["Churn/Positive Signals",     "Encoded in 160,123 activity embedding vectors"],
    ]
    s.append(styled_table(kpi, col_widths=[260, 215]))
    s.append(sp(6))
    return s


# ─── Section 7 — Scrum ───────────────────────────────────────────────────────
def build_section7():
    s = []
    s += section_header("Section 7 — Project Management — Scrum")

    s.append(sub("7.1 Scrum Overview"))
    s.append(body(
        "The project follows an adapted Scrum methodology, with one-week sprints and a solo "
        "development team. The product backlog is maintained collaboratively with the company "
        "supervisor. Ceremonies are lightweight: sprint reviews conducted periodically "
        "with supervisors."
    ))
    roles = [
        [Paragraph("Role", TABLE_HEADER), Paragraph("Person / Entity", TABLE_HEADER)],
        ["Product Owner",   "Company supervisor — Eita Consulting"],
        ["Scrum Master",    "Jihed Ben Messaoud"],
        ["Development Team","Jihed Ben Messaoud (solo developer)"],
        ["Sprint Duration", "1 week"],
    ]
    s.append(styled_table(roles, col_widths=[160, 315]))
    s.append(sp(8))

    s.append(sub("7.2 Sprint Plan"))
    sprints = [
        [Paragraph("Sprint", TABLE_HEADER), Paragraph("Goal", TABLE_HEADER),
         Paragraph("Deliverables", TABLE_HEADER), Paragraph("Status", TABLE_HEADER)],
        ["Sprint 1", "Project setup + Architecture",
         "Environment, DB models, seed data", "Done"],
        ["Sprint 2", "Agent foundation",
         "Tools, MCP layer, basic agents", "Done"],
        ["Sprint 3", "Multi-agent system",
         "Supervisor, specialist agents, routing", "Done"],
        ["Sprint 4", "Data pipeline",
         "Raw data generation, ETL, warehouse", "Done"],
        ["Sprint 5", "RAG system",
         "ChromaDB, embeddings, retrieval layer", "Done"],
        ["Sprint 6", "BI Dashboards",
         "Streamlit dashboards, KPI charts", "In Progress"],
        ["Sprint 7", "Evaluation + Security",
         "Test framework, JWT authentication, RBAC", "Planned"],
        ["Sprint 8", "UI + Deployment",
         "New frontend, Docker containerization", "Planned"],
        ["Sprint 9", "Report + Defense",
         "Final documentation, diagrams, presentation", "Planned"],
    ]
    # Status color cells
    status_colors = {
        "Done": HexColor("#16a34a"),
        "In Progress": HexColor("#d97706"),
        "Planned": HexColor("#6b7280"),
    }
    t_sprints = Table(sprints, colWidths=[55, 130, 165, 70], repeatRows=1)
    style_cmds = [
        ("BACKGROUND",  (0, 0), (-1, 0), DARK_HEADER),
        ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ALIGN",       (0, 0), (-1, 0), "CENTER"),
        ("ALIGN",       (3, 1), (3, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",        (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0,0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("LINEBELOW",   (0, 0), (-1, 0), 1.5, BLUE),
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
    ]
    for i in range(1, len(sprints)):
        bg = LIGHT_GRAY if i % 2 == 0 else WHITE
        style_cmds.append(("BACKGROUND", (0, i), (2, i), bg))
        status = sprints[i][3]
        style_cmds.append(("BACKGROUND", (3, i), (3, i),
                            status_colors.get(status, DARK_GRAY)))
        style_cmds.append(("TEXTCOLOR", (3, i), (3, i), WHITE))
        style_cmds.append(("FONTNAME", (3, i), (3, i), "Helvetica-Bold"))
    t_sprints.setStyle(TableStyle(style_cmds))
    s.append(t_sprints)
    s.append(sp(8))

    s.append(sub("7.3 Product Backlog"))
    backlog = [
        [Paragraph("Priority", TABLE_HEADER), Paragraph("Item", TABLE_HEADER),
         Paragraph("Sprint", TABLE_HEADER), Paragraph("Status", TABLE_HEADER)],
        ["High",   "Evaluation framework (60+ test queries, accuracy metrics)", "7", "Planned"],
        ["High",   "Agent performance tuning based on evaluation results",      "7", "Planned"],
        ["Medium", "JWT authentication + role-based access control",            "7", "Planned"],
        ["Medium", "New production-quality SaaS frontend UI",                   "8", "Planned"],
        ["Medium", "Docker containerization and deployment",                    "8", "Planned"],
        ["Low",    "Churn prediction model (ML on activity signals)",           "9", "Planned"],
        ["Low",    "Revenue forecasting model",                                 "9", "Planned"],
        ["Low",    "Additional ERP module (HR or Projects if time permits)",    "9", "If time permits"],
    ]
    pri_colors = {"High": HexColor("#dc2626"), "Medium": HexColor("#d97706"),
                  "Low": HexColor("#6b7280")}
    t_back = Table(backlog, colWidths=[55, 265, 55, 100], repeatRows=1)
    bcmds = [
        ("BACKGROUND",  (0, 0), (-1, 0), DARK_HEADER),
        ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ALIGN",       (0, 0), (-1, 0), "CENTER"),
        ("ALIGN",       (0, 1), (0, -1), "CENTER"),
        ("ALIGN",       (2, 1), (2, -1), "CENTER"),
        ("ALIGN",       (3, 1), (3, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",        (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0,0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("LINEBELOW",   (0, 0), (-1, 0), 1.5, BLUE),
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
    ]
    for i in range(1, len(backlog)):
        bg = LIGHT_GRAY if i % 2 == 0 else WHITE
        bcmds.append(("BACKGROUND", (1, i), (-1, i), bg))
        pri = backlog[i][0]
        bcmds.append(("BACKGROUND", (0, i), (0, i), pri_colors.get(pri, DARK_GRAY)))
        bcmds.append(("TEXTCOLOR", (0, i), (0, i), WHITE))
        bcmds.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))
    t_back.setStyle(TableStyle(bcmds))
    s.append(t_back)
    s.append(sp(6))
    return s


# ─── Section 8 ───────────────────────────────────────────────────────────────
def build_section8():
    s = []
    s += section_header("Section 8 — Project Status")

    s.append(sub("8.1 Completed Components"))
    done_data = [
        [Paragraph("Component", TABLE_HEADER), Paragraph("Status", TABLE_HEADER),
         Paragraph("Details", TABLE_HEADER)],
        ["ERP Modules (CRM + Invoicing)", "Complete",
         "Full CRUD via natural language, 18 tools total"],
        ["Multi-Agent Architecture",      "Complete",
         "Supervisor + 2 specialist agents, two-tier routing"],
        ["RAG System",                    "Complete",
         "162,499 vectors in ChromaDB, cosine similarity"],
        ["Raw Data Generation",           "Complete",
         "403,094 rows across 4 Excel files"],
        ["ETL Pipeline",                  "Complete",
         "58-second runtime, all validation checks passed"],
        ["Data Warehouse",                "Complete",
         "5 tables, 227,984 clean rows, star schema"],
        ["Error Handling",                "Complete",
         "14 error types, centralized ERPErrorType enum"],
        ["Chat Frontend",                 "Complete",
         "Dark SaaS UI, single-page HTML/CSS/JS"],
        ["BI Dashboards",                 "In Progress",
         "Streamlit, 2 dashboards under active development"],
    ]
    status_col_map = {"Complete": GREEN, "In Progress": AMBER, "Planned": DARK_GRAY}
    t_done = Table(done_data, colWidths=[160, 80, 235], repeatRows=1)
    dcmds = [
        ("BACKGROUND",  (0, 0), (-1, 0), DARK_HEADER),
        ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ALIGN",       (0, 0), (-1, 0), "CENTER"),
        ("ALIGN",       (1, 1), (1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",        (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0,0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("LINEBELOW",   (0, 0), (-1, 0), 1.5, BLUE),
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
    ]
    for i in range(1, len(done_data)):
        bg = LIGHT_GRAY if i % 2 == 0 else WHITE
        dcmds.append(("BACKGROUND", (0, i), (0, i), bg))
        dcmds.append(("BACKGROUND", (2, i), (2, i), bg))
        status = done_data[i][1]
        col = status_col_map.get(status, DARK_GRAY)
        dcmds.append(("BACKGROUND", (1, i), (1, i), col))
        dcmds.append(("TEXTCOLOR",  (1, i), (1, i), WHITE))
        dcmds.append(("FONTNAME",   (1, i), (1, i), "Helvetica-Bold"))
    t_done.setStyle(TableStyle(dcmds))
    s.append(t_done)
    s.append(sp(8))

    s.append(sub("8.2 Planned Components"))
    plan_data = [
        [Paragraph("Component", TABLE_HEADER), Paragraph("Priority", TABLE_HEADER),
         Paragraph("Description", TABLE_HEADER)],
        ["Evaluation Framework",    "High",   "60+ test queries, accuracy and relevance metrics"],
        ["Agent Performance Tuning","High",   "Improvements based on evaluation results"],
        ["JWT Authentication + RBAC","Medium","Role-based access: CEO, Sales Manager, Accountant"],
        ["New SaaS UI",             "Medium", "Production-quality single-page frontend"],
        ["Docker Deployment",       "Medium", "Full containerization of API + dependencies"],
        ["Churn Prediction Model",  "Low",    "ML model on activity churn signals"],
        ["Revenue Forecasting",     "Low",    "Time-series forecasting on fact_revenue"],
        ["Additional ERP Module",   "Low",    "HR or Projects module if time permits"],
        ["Final Report",            "Final",  "Scrum methodology, full documentation"],
    ]
    pri_c = {"High": HexColor("#dc2626"), "Medium": AMBER, "Low": DARK_GRAY, "Final": BLUE}
    t_plan = Table(plan_data, colWidths=[155, 65, 255], repeatRows=1)
    pcmds = [
        ("BACKGROUND",  (0, 0), (-1, 0), DARK_HEADER),
        ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ALIGN",       (0, 0), (-1, 0), "CENTER"),
        ("ALIGN",       (1, 1), (1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",        (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0,0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("LINEBELOW",   (0, 0), (-1, 0), 1.5, BLUE),
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
    ]
    for i in range(1, len(plan_data)):
        bg = LIGHT_GRAY if i % 2 == 0 else WHITE
        dcmds.append(("BACKGROUND", (0, i), (0, i), bg))
        pcmds.append(("BACKGROUND", (2, i), (2, i), bg))
        pri = plan_data[i][1]
        col = pri_c.get(pri, DARK_GRAY)
        pcmds.append(("BACKGROUND", (1, i), (1, i), col))
        pcmds.append(("TEXTCOLOR",  (1, i), (1, i), WHITE))
        pcmds.append(("FONTNAME",   (1, i), (1, i), "Helvetica-Bold"))
        pcmds.append(("BACKGROUND", (0, i), (0, i), bg))
    t_plan.setStyle(TableStyle(pcmds))
    s.append(t_plan)
    s.append(sp(10))

    s.append(hr())
    s.append(body(
        "This document represents the technical state of the JBM ERP AI Agent project "
        "as of Mars 2026. All monetary values are expressed in TND (Tunisian Dinar). "
        "The system is built entirely on open-source components with no dependency on "
        "commercial cloud LLM APIs."
    ))
    return s


# ─── Language-aware section headers ──────────────────────────────────────────
SEC_TITLES = {
    "fr": {
        1: "Section 1 — Apercu du Projet",
        2: "Section 2 — Architecture du Systeme",
        3: "Section 3 — Architecture des Donnees",
        4: "Section 4 — Systeme RAG",
        5: "Section 5 — Systeme Agentique",
        6: "Section 6 — Contexte Metier — JBM Consulting",
        7: "Section 7 — Gestion de Projet — Scrum",
        8: "Section 8 — Etat du Projet",
    },
    "en": {
        1: "Section 1 — Project Overview",
        2: "Section 2 — System Architecture",
        3: "Section 3 — Data Architecture",
        4: "Section 4 — RAG System",
        5: "Section 5 — Agent System",
        6: "Section 6 — Business Context — JBM Consulting",
        7: "Section 7 — Project Management — Scrum",
        8: "Section 8 — Project Status",
    },
}


# ─── Main ─────────────────────────────────────────────────────────────────────
def build_story(lang="fr"):
    """Assemble the full Platypus story for a given language."""
    global FOOTER_TEXT
    FOOTER_TEXT = FOOTER_TEXT_FR if lang == "fr" else FOOTER_TEXT_EN
    titles = SEC_TITLES[lang]

    story = []
    story += build_cover(lang)

    # Section 1
    story += [Spacer(1, 10), _SectionBanner(titles[1]), Spacer(1, 6)]
    story += build_section1()[3:]   # skip the banner already prepended

    story.append(PageBreak())
    story += [Spacer(1, 10), _SectionBanner(titles[2]), Spacer(1, 6)]
    story += build_section2()[3:]

    story.append(PageBreak())
    story += [Spacer(1, 10), _SectionBanner(titles[3]), Spacer(1, 6)]
    story += build_section3()[3:]

    story.append(PageBreak())
    story += [Spacer(1, 10), _SectionBanner(titles[4]), Spacer(1, 6)]
    story += build_section4()[3:]

    story.append(PageBreak())
    story += [Spacer(1, 10), _SectionBanner(titles[5]), Spacer(1, 6)]
    story += build_section5()[3:]

    story.append(PageBreak())
    story += [Spacer(1, 10), _SectionBanner(titles[6]), Spacer(1, 6)]
    story += build_section6()[3:]

    story.append(PageBreak())
    story += [Spacer(1, 10), _SectionBanner(titles[7]), Spacer(1, 6)]
    story += build_section7()[3:]

    story.append(PageBreak())
    story += [Spacer(1, 10), _SectionBanner(titles[8]), Spacer(1, 6)]
    story += build_section8()[3:]

    return story


def build_pdf(lang="fr"):
    os.makedirs("docs", exist_ok=True)
    suffix = "fr" if lang == "fr" else "en"
    output = f"docs/rapport_technique_jbm_{suffix}.pdf"

    title_meta = ("Rapport Technique — JBM ERP AI Agent"
                  if lang == "fr" else
                  "Technical Report — JBM ERP AI Agent")
    subject_meta = ("Projet de Fin d'Etudes — Business Intelligence"
                    if lang == "fr" else
                    "Final Year Project — Business Intelligence")

    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 0.5*cm,
        bottomMargin=MARGIN + 0.5*cm,
        title=title_meta,
        author="Jihed Ben Messaoud",
        subject=subject_meta,
    )

    story = build_story(lang)

    def _on_first_page(canvas, doc):
        """Pure dark background for cover page — no coloured accents."""
        canvas.saveState()
        canvas.setFillColor(DARK_HEADER)
        canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        canvas.restoreState()

    def _on_later_page(canvas, doc):
        on_page(canvas, doc)

    doc.build(story, onFirstPage=_on_first_page, onLaterPages=_on_later_page)
    print(f"PDF generated: {output}")


def main():
    build_pdf("fr")
    build_pdf("en")


if __name__ == "__main__":
    main()
