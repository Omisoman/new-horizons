"""Print the demo documents from data/mock_meta.json["document_intake"].

    uv run python -m new_horizons.app.intake.samples

-> data/samples/invoice-held.pdf   (+ -preview.png)  supplier invoice, 23% over the order
                                                      price, from the wrong supplier
   data/samples/invoice-clean.pdf  (+ -preview.png)  supplier invoice matching its order
   data/samples/lab-report.pdf     (+ -preview.png)  water-lab report for the AQ-04 sample

Each page is laid out with PyMuPDF insert_htmlbox (HarfBuzz shapes the Arabic),
rasterised at 200 dpi, then aged into a scan — grey paper, uneven light,
≤0.6° skew, sensor noise, slight blur, JPEG — and written back as an IMAGE-ONLY
PDF, so intake always exercises the OCR path. Seeded: the same meta always
prints the same pixels. Supplier names come from the generated supplier master.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter

from new_horizons.app.analytics.dataio import frames, profile
from new_horizons.paths import DATA

META = DATA / "mock_meta.json"
OUT = DATA / "samples"
DPI = 200
W, H = 595, 842                      # A4 in points
SAMPLES = {"held": "invoice-held", "clean": "invoice-clean", "lab": "lab-report"}


def money(v: float) -> str:
    return f"{v:,.2f}"


def load_cases() -> dict:
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    cases = meta.get("document_intake")
    if not cases:
        raise SystemExit("data/mock_meta.json has no document_intake yet — run `make mock` first")
    data = frames(["suppliers", "items"])
    suppliers = data["suppliers"].set_index("supplier_ref")
    items = data["items"].set_index("item_code")
    return {"cases": cases, "suppliers": suppliers, "items": items}


# ---- layout ---------------------------------------------------------------------------

_CSS = """
* { font-family: sans-serif; }
p { margin: 0; }
.en { font-size: 9pt; color: #222; line-height: 1.35; }
.ar { font-size: 10pt; color: #222; text-align: right; direction: rtl; line-height: 1.35; }
.name { font-size: 15pt; font-weight: bold; color: #111; }
.lbl { font-size: 8pt; color: #555; }
.val { font-size: 10.5pt; font-weight: bold; color: #111; }
.th { font-size: 8.5pt; font-weight: bold; color: #111; }
.td { font-size: 11pt; color: #111; }
.num { text-align: right; }
.grand { font-size: 12.5pt; font-weight: bold; color: #000; }
"""


def _box(page, rect, html: str) -> None:
    page.insert_htmlbox(pymupdf.Rect(*rect), html, css=_CSS)


def _header(page, name: str, line2: str, line3: str, title_en: str, title_ar: str) -> None:
    ink = (0.1, 0.1, 0.1)
    _box(page, (40, 38, 380, 112), f"<p class='name'>{name}</p><p class='en'>{line2}</p>"
                                    f"<p class='en'>{line3}</p>")
    page.draw_line((40, 118), (555, 118), color=ink, width=1.6)
    page.draw_rect(pymupdf.Rect(40, 128, 555, 152), color=None, fill=(0.88, 0.88, 0.88))
    _box(page, (40, 132, 555, 152), "<p style='text-align:center;font-size:12.5pt;font-weight:bold'>"
                                    f"{title_en} &nbsp;&nbsp;·&nbsp;&nbsp; {title_ar}</p>")


def _facts(page, rows: list[tuple[str, str, str]], y: float = 164) -> float:
    for i, (en, ar, value) in enumerate(rows):
        col, row = i % 2, i // 2
        x = 40 if col == 0 else 312
        yy = y + row * 28
        _box(page, (x, yy, x + 80, yy + 22), f"<p class='lbl'>{en}</p><p class='lbl'>{ar}</p>")
        _box(page, (x + 80, yy + 2, x + 243, yy + 22), f"<p class='val'>{value}</p>")
    return y + ((len(rows) + 1) // 2) * 28


def render_invoice(spec: dict) -> pymupdf.Document:
    cur = profile()["market"]["currency"]
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    rule = (0.55, 0.55, 0.55)
    _header(page, spec["supplier_name"], "Aquaculture feed, nutrients and spare parts",
            f"Supplier ref. {spec['supplier_ref']} · Tel. {spec['phone']}", "INVOICE", "فاتورة")
    y = _facts(page, [("Invoice No.", "رقم الفاتورة", spec["invoice_no"]),
                      ("Bill to", "إلى", "the Farm"),
                      ("Invoice Date", "تاريخ الفاتورة", spec["invoice_date"]),
                      ("Your order", "أمر الشراء", spec["po_no"]),
                      ("Supplier ref.", "رمز المورد", spec["supplier_ref"]),
                      ("Delivered", "تاريخ التسليم", spec["received"])])
    page.draw_line((40, y + 2), (555, y + 2), color=rule, width=0.6)
    y += 14
    cols = [(40, 120), (120, 352), (352, 412), (412, 480), (480, 555)]
    heads = ["Item", "Description · البيان", "Qty", "Unit price", f"Amount ({cur})"]
    page.draw_rect(pymupdf.Rect(40, y, 555, y + 22), color=None, fill=(0.9, 0.9, 0.9))
    for (x0, x1), h in zip(cols, heads):
        cls = "th" if h.startswith(("Item", "Description")) else "th num"
        _box(page, (x0 + 4, y + 5, x1 - 4, y + 21), f"<p class='{cls}'>{h}</p>")
    y += 26
    cells = [spec["item_code"], spec["item_name"], f"{spec['qty']:g}", money(spec["unit_price"]),
             money(spec["total"])]
    for j, ((x0, x1), c) in enumerate(zip(cols, cells)):
        cls = "td num" if j >= 2 else "td"
        _box(page, (x0 + 4, y + 3, x1 - 4, y + 17), f"<p class='{cls}'>{c}</p>")
    _box(page, (124, y + 16, 348, y + 29), f"<p class='ar' style='text-align:left;font-size:8pt;"
                                           f"color:#555'>{spec['item_unit']}</p>")
    y += 34
    page.draw_line((40, y), (555, y), color=(0.8, 0.8, 0.8), width=0.4)
    y += 14
    page.draw_rect(pymupdf.Rect(296, y, 555, y + 34), color=(0.1, 0.1, 0.1), width=1.2)
    _box(page, (304, y + 5, 420, y + 30), "<p class='grand'>TOTAL DUE</p>"
                                          "<p class='ar' style='text-align:left;font-size:9pt'>المبلغ المستحق</p>")
    _box(page, (420, y + 9, 551, y + 30), f"<p class='grand num'>{money(spec['total'])} {cur}</p>")
    y += 60
    _box(page, (40, y, 555, y + 60),
         "<p class='en'>Agricultural inputs, zero-rated. Payment due within 30 days of a matched "
         "invoice.</p><p class='en'>Quote our supplier reference and your purchase order on "
         "every payment.</p><p class='ar'>يُرجى ذكر رمز المورد ورقم أمر الشراء عند الدفع.</p>")
    return doc


def render_lab(spec: dict) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    _header(page, spec["lab_name"], "Water quality testing for aquaculture",
            "Accredited methods · results relate only to the sample tested",
            "WATER ANALYSIS REPORT", "تقرير تحليل المياه")
    y = _facts(page, [("Report No.", "رقم التقرير", spec["report_no"]),
                      ("Client", "العميل", "the Farm"),
                      ("Grow unit", "الوحدة", spec["unit_id"]),
                      ("Sampled", "وقت أخذ العينة", spec["sampled"].replace("T", " ")),
                      ("Received", "تاريخ الاستلام", spec["sampled"][:10]),
                      ("Matrix", "نوع العينة", "Recirculating water")])
    y += 16
    cols = [(40, 250), (250, 340), (340, 440), (440, 555)]
    heads = ["Parameter · المعيار", "Result", "Unit", "Method"]
    page.draw_rect(pymupdf.Rect(40, y, 555, y + 22), color=None, fill=(0.9, 0.9, 0.9))
    for (x0, x1), h in zip(cols, heads):
        _box(page, (x0 + 4, y + 5, x1 - 4, y + 21), f"<p class='th'>{h}</p>")
    y += 26
    rows = [("pH", "الحموضة", f"{spec['ph']:.2f}", "—", "electrode, 25 °C"),
            ("Ammonia (TAN)", "الأمونيا", f"{spec['ammonia_mg_l']:g}", "mg/L", "salicylate"),
            ("Nitrite", "النتريت", f"{spec['nitrite_mg_l']:g}", "mg/L", "diazotisation"),
            ("Nitrate", "النترات", f"{spec['nitrate_mg_l']:g}", "mg/L", "cadmium reduction"),
            ("Iron", "الحديد", f"{spec['iron_mg_l']:g}", "mg/L", "phenanthroline")]
    for en, ar, val, unit, method in rows:
        _box(page, (44, y + 3, 246, y + 17), f"<p class='td'>{en}</p>")
        _box(page, (44, y + 15, 246, y + 28), f"<p class='ar' style='text-align:left;font-size:8pt;"
                                              f"color:#555'>{ar}</p>")
        for (x0, x1), c in zip(cols[1:], (val, unit, method)):
            _box(page, (x0 + 4, y + 3, x1 - 4, y + 17), f"<p class='td'>{c}</p>")
        y += 32
        page.draw_line((40, y - 2), (555, y - 2), color=(0.8, 0.8, 0.8), width=0.4)
    y += 16
    _box(page, (40, y, 555, y + 50),
         "<p class='en'>Sample taken by the client at the stated time and kept at 4 °C until "
         "analysis.</p><p class='ar'>أُخذت العينة من قبل العميل في الوقت المذكور وحُفظت مبرّدة حتى "
         "التحليل.</p>")
    return doc


# ---- scan ------------------------------------------------------------------------------

def scanify(png: bytes, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    img = Image.open(io.BytesIO(png)).convert("L")
    img = img.rotate(float(rng.uniform(-0.6, 0.6)), resample=Image.BICUBIC, expand=False, fillcolor=255)
    a = np.asarray(img).astype(np.float32)
    h, w = a.shape
    a = 26 + a * (236 - 26) / 255.0                       # grey paper, soft black
    yy, xx = np.mgrid[0:h, 0:w]
    a *= 1 - 0.07 * (((xx / w) - 0.45) ** 2 + ((yy / h) - 0.4) ** 2) * 4  # uneven light
    a += rng.normal(0, 5.5, a.shape)                      # sensor noise
    img = Image.fromarray(a.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.45))
    return Image.merge("RGB", (img.point(lambda v: min(255, v + 4)), img,
                               img.point(lambda v: max(0, v - 6))))


def write_scan(vec: pymupdf.Document, seed: int, title: str, day: str, out_pdf: Path) -> dict:
    png = vec[0].get_pixmap(dpi=DPI).tobytes("png")
    scan = scanify(png, seed)
    buf = io.BytesIO()
    scan.save(buf, "JPEG", quality=74, optimize=True)
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.insert_image(page.rect, stream=buf.getvalue())   # image only — no text layer
    stamp = "D:" + day.replace("-", "") + "090000"
    doc.set_metadata({"title": title, "producer": "scanner", "creationDate": stamp, "modDate": stamp})
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_pdf, garbage=4, deflate=True, no_new_id=True)  # byte-stable: same meta, same file
    preview = out_pdf.with_name(out_pdf.stem + "-preview.png")
    scan.resize((1000, round(1000 * scan.height / scan.width)), Image.LANCZOS).save(preview, optimize=True)
    return {"pdf": str(out_pdf), "preview": str(preview)}


def invoice_spec(kind: str, ctx: dict) -> dict:
    c = ctx["cases"][kind]
    supplier = c["invoice_supplier_ref"] if kind == "held" else c["supplier_ref"]
    price = float(c["invoice_unit_price"]) if kind == "held" else float(c["unit_price"])
    s, i = ctx["suppliers"].loc[supplier], ctx["items"].loc[c["item"]]
    rng = np.random.default_rng(7 if kind == "held" else 11)
    # the held invoice prints its own number, not the one on file
    phone = s["phone"] if kind == "clean" else f"+1-{rng.integers(200, 999)}-{rng.integers(200, 999)}-" \
                                               f"{rng.integers(1000, 9999)}"
    return {"invoice_no": c["invoice_no"], "invoice_date": str(c["invoice_date"]),
            "po_no": c["po_no"], "received": str(c["received"]), "supplier_ref": supplier,
            "supplier_name": s["name"], "phone": phone, "item_code": c["item"], "item_name": i["name"],
            "item_unit": f"per {i['unit']}", "qty": float(c["qty"]), "unit_price": price,
            "total": round(float(c["qty"]) * price, 2)}


def lab_spec(ctx: dict) -> dict:
    c = ctx["cases"]["lab"]
    return {"report_no": c["report_no"], "unit_id": c["unit"], "sampled": str(c["sampled"]),
            "lab_name": c["lab_name"], "ph": float(c["lab_ph"]), **c["results"]}


def main() -> int:
    ctx = load_cases()
    for kind in ("held", "clean"):
        spec = invoice_spec(kind, ctx)
        info = write_scan(render_invoice(spec), 7 if kind == "held" else 11, spec["invoice_no"],
                          spec["invoice_date"], OUT / f"{SAMPLES[kind]}.pdf")
        print(f"{kind:6s} {spec['invoice_no']}  {spec['supplier_ref']}  {spec['po_no']}  "
              f"{spec['qty']:g} × {money(spec['unit_price'])} = {money(spec['total'])}  -> {info['pdf']}")
    spec = lab_spec(ctx)
    info = write_scan(render_lab(spec), 13, spec["report_no"], spec["sampled"][:10], OUT / f"{SAMPLES['lab']}.pdf")
    print(f"lab    {spec['report_no']}  {spec['unit_id']}  pH {spec['ph']:.2f}  -> {info['pdf']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
