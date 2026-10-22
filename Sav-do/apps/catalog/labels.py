"""Etiketka PDF (reportlab). Ikki rejim: lenta (har bir etiketka alohida sahifa) va A4 jadval."""
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .barcode import is_valid_gs1

FONT_DIR = Path(__file__).resolve().parents[2] / "static" / "fonts"
MAX_LABELS = 2000


@dataclass
class LabelItem:
    name: str
    code: str
    price: Decimal | None = None
    unit: str = ""
    copies: int = 1


@dataclass(frozen=True)
class Layout:
    title: str
    label_w: float  # mm
    label_h: float  # mm
    cols: int = 1
    rows: int = 1
    sheet: bool = False  # True: A4 jadval, False: har bir etiketka alohida sahifa


LAYOUTS = {
    "roll_58x40": Layout("Lenta 58×40 mm", 58, 40),
    "roll_40x30": Layout("Lenta 40×30 mm", 40, 30),
    "a4_3x8": Layout("A4 varaq, 3×8 (70×37 mm)", 70, 37, cols=3, rows=8, sheet=True),
}
DEFAULT_LAYOUT = "roll_58x40"


def _fonts():
    regular, bold = FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "DejaVuSans-Bold.ttf"
    if regular.exists() and bold.exists():
        if "SavDo" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("SavDo", str(regular)))
            pdfmetrics.registerFont(TTFont("SavDo-Bold", str(bold)))
        return "SavDo", "SavDo-Bold"
    return "Helvetica", "Helvetica-Bold"  # kirill harflar chiqmaydi


def format_price(price: Decimal) -> str:
    return f"{int(price):,}".replace(",", " ")


def _fit_lines(text, font, size, max_w, max_lines):
    lines = simpleSplit(text, font, size, max_w)
    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    last = lines[-1]
    while last and pdfmetrics.stringWidth(last + "…", font, size) > max_w:
        last = last[:-1]
    lines[-1] = last.rstrip() + "…"
    return lines


def _barcode_drawing(code, target_w, max_h):
    """Kenglik bo'yicha moslab, balandlik max_h dan oshmasligi uchun qayta quradi."""
    kind = "EAN13" if len(code) == 13 and code.isdigit() and is_valid_gs1(code) else "Code128"
    bar_h = max_h
    for _ in range(3):
        d = createBarcodeDrawing(kind, value=code, barHeight=bar_h, humanReadable=True)
        sx = target_w / d.width
        overflow = d.height * sx - max_h
        if overflow <= 0.5:
            break
        bar_h = max(4 * mm / sx, bar_h - overflow / sx)
    d.scale(sx, sx)
    return d, d.height * sx  # Drawing.scale() width/height ni yangilamaydi


def _draw_label(c, x, y, w, h, item, regular, bold):
    pad = 2 * mm
    k = min(1.0, h / (40 * mm))  # kichik etiketkada shriftlar kichrayadi
    name_size = max(6.5, 9 * k)
    price_size = max(9, 14 * k)
    inner_w = w - 2 * pad

    cur_y = y + h - pad - name_size
    c.setFont(bold, name_size)
    for line in _fit_lines(item.name, bold, name_size, inner_w, 2):
        c.drawString(x + pad, cur_y, line)
        cur_y -= name_size * 1.15

    price_h = price_size * 1.2 if item.price is not None else 0
    avail_h = cur_y + name_size * 0.6 - (y + pad + price_h)
    d, d_h = _barcode_drawing(item.code, inner_w, max(8 * mm, avail_h - 1.5 * mm))
    renderPDF.draw(d, c, x + pad, y + pad + price_h + max(0, (avail_h - d_h) / 2))

    if item.price is not None:
        c.setFont(bold, price_size)
        c.drawString(x + pad, y + pad, f"{format_price(item.price)} so'm")
        if item.unit:
            c.setFont(regular, price_size * 0.6)
            c.drawRightString(x + w - pad, y + pad, f"/ {item.unit}")


def build_labels_pdf(items, layout_key=DEFAULT_LAYOUT) -> bytes:
    layout = LAYOUTS.get(layout_key, LAYOUTS[DEFAULT_LAYOUT])
    flat = [it for it in items for _ in range(max(0, it.copies))]
    if not flat:
        raise ValueError("Chop etish uchun etiketka yo'q")
    if len(flat) > MAX_LABELS:
        raise ValueError(f"Bir martada {MAX_LABELS} tadan ko'p etiketka chiqarib bo'lmaydi")

    regular, bold = _fonts()
    lw, lh = layout.label_w * mm, layout.label_h * mm
    buf = BytesIO()
    if layout.sheet:
        page_w, page_h = A4
        c = canvas.Canvas(buf, pagesize=A4)
        mx = (page_w - layout.cols * lw) / 2
        my = (page_h - layout.rows * lh) / 2
        per_page = layout.cols * layout.rows
        for i, item in enumerate(flat):
            pos = i % per_page
            if i and pos == 0:
                c.showPage()
            col, row = pos % layout.cols, pos // layout.cols
            _draw_label(c, mx + col * lw, page_h - my - (row + 1) * lh, lw, lh, item, regular, bold)
    else:
        c = canvas.Canvas(buf, pagesize=(lw, lh))
        for i, item in enumerate(flat):
            if i:
                c.showPage()
            _draw_label(c, 0, 0, lw, lh, item, regular, bold)
    c.save()
    return buf.getvalue()
