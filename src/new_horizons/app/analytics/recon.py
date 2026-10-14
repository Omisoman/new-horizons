"""Cross-system reconciliation — commanded vs observed, harvested vs shipped,
consumed vs purchased.

  run()                    the nightly three-way match -> data/analytics/recon.json
  check_document(fields)   the reconciliation call for ONE uploaded document
                           (a supplier invoice or a water-lab report)
  unit_snapshot(unit_id)   every record the five systems hold for one grow unit

The systems share no surrogate keys: the controller and the sensors meet on
unit_id and time, harvests and shipments on harvest_no, consumption and
purchases on item_code. Every exception carries the kilograms and the money at
risk (data-dictionary §7) and is ranked by money. All reads go through the
read-only role; nothing here writes to the database.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from new_horizons.app.analytics.dataio import OUT, cite, currency, dsn_ro, frames, period, profile

RISE_CM, RISE_WITHIN = 1.5, pd.Timedelta(minutes=30)      # pump-maintenance-sop §4
SHIP_WITHIN = pd.Timedelta(hours=48)                      # harvest-shipping-procedure §3
TRIM_TOLERANCE = 0.05
PRICE_TOLERANCE = 0.05                                    # supplier-invoice-controls §2
PH_PROBE_TOLERANCE = 0.2                                  # sensor-calibration §3
LAB_BANDS = {  # water-quality-sop §8 / §2 — measure: (low, high, label)
    "ph": (6.6, 7.2, "pH"), "ammonia_mg_l": (None, 0.5, "Ammonia"),
    "nitrite_mg_l": (None, 0.5, "Nitrite"), "nitrate_mg_l": (5.0, 150.0, "Nitrate"),
    "iron_mg_l": (2.0, 3.0, "Iron"),
}

CLASSES = {  # class -> (label, severity, citation key)
    "commanded_not_observed": ("Pump commanded, level never rose", "high", "pump_command_check"),
    "harvest_not_shipped": ("Harvest with no shipment", "high", "harvest_shipment_match"),
    "consumed_not_purchased": ("Consumed, never purchased", "medium", "stock_unmetered"),
}

INVOICE_CHECKS = [  # id, label, schema, citation key when it fails
    ("order_exists", "Purchase order exists", "supplies", "invoice_tolerance"),
    ("supplier_matches_order", "Supplier matches the purchase order", "supplies", "supplier_master"),
    ("supplier_approved", "Supplier is on the approved supplier list", "supplies", "supplier_master"),
    ("item_matches_order", "Item matches the purchase order", "supplies", "invoice_tolerance"),
    ("quantity_matches_receipt", "Quantity equals goods received", "supplies", "invoice_tolerance"),
    ("price_within_tolerance", "Unit price within 5% of the order price", "supplies",
     "invoice_tolerance"),
    ("not_already_invoiced", "Order still awaiting its invoice", "supplies", "invoice_tolerance"),
]
LAB_CHECKS = [
    ("unit_exists", "Grow unit exists", "telemetry", None),
    ("probe_reading", "A probe reading at the sample time", "telemetry", "sensor_dropout"),
    ("ph_matches_probe", "Lab pH within 0.2 of the probe", "telemetry", "sensor_vs_chemistry"),
    ("ph_in_band", "pH within the operating band", "telemetry", "water_ph_band"),
    ("ammonia_mg_l", "Ammonia below 0.5 mg/L", None, "lab_bands"),
    ("nitrite_mg_l", "Nitrite below 0.5 mg/L", None, "lab_bands"),
    ("nitrate_mg_l", "Nitrate 5–150 mg/L", None, "lab_bands"),
    ("iron_mg_l", "Iron 2–3 mg/L", None, "lab_bands"),
]


# ---- helpers -------------------------------------------------------------------

def _js(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat(timespec="minutes")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and pd.isna(v):
        return None
    if v is pd.NaT:
        return None
    return v


def _rows(cur, sql: str, params=None) -> list[dict]:
    cur.execute(sql, params or {})
    cols = [d.name for d in cur.description]
    return [{c: _js(v) for c, v in zip(cols, r)} for r in cur.fetchall()]


def _connect():
    import psycopg
    return psycopg.connect(dsn_ro(), connect_timeout=5)


def prices() -> dict[str, float]:
    return {k: float(v) for k, v in profile()["prices"].items()}


def _money(x: float) -> str:
    return f"{x:,.2f} {currency()}"


# ---- the three matches -----------------------------------------------------------

def commanded_vs_observed(data: dict) -> tuple[list[dict], dict]:
    """Water-pump runs against the level sensor: each run must raise the level by
    RISE_CM within RISE_WITHIN. Consecutive failed runs on a unit are one incident,
    priced by the harvest that followed."""
    rd = data["readings"][["ts", "unit_id", "water_level_cm"]].sort_values("ts")
    cmd = data["commands"]
    runs = cmd[(cmd.actuator == "water_pump") & (cmd.action == "on")].sort_values("ts")
    incidents, total, failed = [], 0, 0
    for unit, rs in runs.groupby("unit_id"):
        lv = rd[rd.unit_id == unit].set_index("ts")["water_level_cm"]
        before = lv.shift(1)
        status = []
        for t in rs.ts:
            if t not in before.index or pd.isna(before.get(t)):
                status.append(None)                          # no reading to judge by
                continue
            window = lv[(lv.index >= t) & (lv.index <= t + RISE_WITHIN)]
            rise = (window.max() - before[t]) if len(window) else None
            status.append(None if rise is None else rise >= RISE_CM)
        rs = rs.assign(observed=status)
        judged = rs[rs.observed.notna()]
        total += len(judged)
        failed += int((judged.observed == False).sum())  # noqa: E712
        run: list = []
        for row in judged.itertuples():
            if row.observed is False:
                run.append(row)
                continue
            if len(run) >= 2:
                incidents.append((unit, run))
            run = []
        if len(run) >= 2:
            incidents.append((unit, run))
    out = []
    harvests, ships = data["harvests"], data["shipments"]
    shipped = set(ships.harvest_no)
    alerts, wos = data["alerts"], data["work_orders"]
    for unit, run in incidents:
        first, last = run[0].ts, run[-1].ts
        lv = rd[(rd.unit_id == unit) & (rd.ts >= first) & (rd.ts <= last + pd.Timedelta(minutes=15))]
        alert = alerts[(alerts.unit_id == unit) & (alerts.type == "low_water_level")
                       & (alerts.opened_ts >= first) & (alerts.opened_ts <= last)]
        alert = alert.iloc[0] if len(alert) else None
        wo = wos[wos.alert_no == alert.alert_no].iloc[0] if alert is not None and \
            (wos.alert_no == alert.alert_no).any() else None
        mine = harvests[(harvests.unit_id == unit) & harvests.harvest_no.isin(shipped)].sort_values("date")
        after = mine[mine.date > last]
        hit = after.iloc[0] if len(after) else None
        kg_lost = eur = 0.0
        expected = None
        if hit is not None:
            expected = round(float(mine[mine.harvest_no != hit.harvest_no].kg.mean()), 2)
            kg_lost = round(expected - float(hit.kg), 2)
            eur = round(kg_lost * prices()[hit.plant], 2)
        response = (round((wo.opened_ts - alert.opened_ts).total_seconds() / 3600, 1)
                    if wo is not None else None)
        out.append(_exception(
            "commanded_not_observed", unit_id=unit, ref=f"{unit}·{first:%Y-%m-%d}",
            kg=kg_lost, eur=eur, when=first,
            expected=f"level +{RISE_CM} cm within 30 min of each run",
            found=f"{len(run)} runs, no rise; level {lv.water_level_cm.max():.1f} → "
                  f"{lv.water_level_cm.min():.1f} cm",
            detail=f"{len(run)} water-pump runs commanded {first:%d %b %H:%M} – {last:%d %b %H:%M} "
                   f"with no level rise"
                   + (f"; alert {alert.alert_no} opened {alert.opened_ts:%d %b %H:%M}" if alert is not None else "")
                   + (f", work order {wo.work_order_no} {response:.1f} h later" if wo is not None else "")
                   + (f"; harvest {hit.harvest_no} on {hit.date:%d %b} {float(hit.kg):.2f} kg "
                      f"against {expected:.2f} kg usual" if hit is not None else ""),
            extra={"first_command": _js(first), "last_command": _js(last), "commands": len(run),
                   "alert_no": None if alert is None else alert.alert_no,
                   "alert_opened": None if alert is None else _js(alert.opened_ts),
                   "work_order_no": None if wo is None else wo.work_order_no,
                   "work_order_opened": None if wo is None else _js(wo.opened_ts),
                   "response_hours": response,
                   "harvest_no": None if hit is None else hit.harvest_no,
                   "harvest_date": None if hit is None else _js(hit.date),
                   "kg_actual": None if hit is None else round(float(hit.kg), 2),
                   "kg_expected": expected}))
    rate = {"commanded": total, "observed": total - failed,
            "rate": round((total - failed) / total, 4) if total else 0.0}
    return out, rate


def harvested_vs_shipped(data: dict) -> tuple[list[dict], dict]:
    """Every harvest batch shipped (within 5% trim) or written off within 48 hours."""
    hv, sh = data["harvests"], data["shipments"]
    _start, end = period()
    by_no = sh.groupby("harvest_no").kg.sum()
    out = []
    for h in hv.sort_values(["date", "unit_id"]).itertuples():
        signer = h.countersigned_by if isinstance(h.countersigned_by, str) else None
        if h.harvest_no in by_no.index:
            shipped = float(by_no[h.harvest_no])
            if shipped < float(h.kg) * (1 - TRIM_TOLERANCE):
                short = round(float(h.kg) - shipped, 2)
                out.append(_exception(
                    "harvest_not_shipped", unit_id=h.unit_id, ref=h.harvest_no, kg=short,
                    eur=round(short * prices()[h.plant], 2), when=h.date,
                    expected=f"{float(h.kg):.2f} kg shipped (−5% trim)", found=f"{shipped:.2f} kg",
                    detail=f"{h.harvest_no} shipped {short:.2f} kg short",
                    extra={"logged_by": h.logged_by, "countersigned_by": signer}))
            continue
        if h.date + SHIP_WITHIN > end:
            continue                                     # still inside its 48 hours
        out.append(_exception(
            "harvest_not_shipped", unit_id=h.unit_id, ref=h.harvest_no, kg=round(float(h.kg), 2),
            eur=round(float(h.kg) * prices()[h.plant], 2), when=h.date,
            expected="a shipment within 48 hours", found="no shipment, no write-off",
            detail=f"{h.harvest_no}: {float(h.kg):.2f} kg {h.plant} logged by {h.logged_by}, "
                   f"{'countersigned by ' + signer if signer else 'never countersigned'}, "
                   "never shipped",
            extra={"logged_by": h.logged_by, "countersigned_by": signer, "plant": h.plant}))
    total_kg = float(hv.kg.sum())
    rate = {"harvests": len(hv), "shipped": int(hv.harvest_no.isin(by_no.index).sum()),
            "kg_harvested": round(total_kg, 2), "kg_shipped": round(float(sh.kg.sum()), 2),
            "rate": round(float(sh.kg.sum()) / total_kg, 4) if total_kg else 0.0}
    return out, rate


def consumed_vs_purchased(data: dict) -> tuple[list[dict], dict]:
    """A stock ledger per item: what was received minus what was consumed, day by
    day. Consumption beyond the stock on hand is unmetered — grouped per unit,
    item and month."""
    pu, co, items = data["purchases"], data["consumption"], data["items"].set_index("item_code")
    received = pu[pu.received.notna()].groupby(["item_code", "received"]).qty.sum()
    out, metered, unmetered_total = [], 0.0, 0.0
    groups: dict[tuple, dict] = {}
    for item, rows in co.sort_values(["date", "unit_id"]).groupby("item_code"):
        rec = (received.loc[item].sort_index() if item in received.index.get_level_values(0)
               else pd.Series(dtype=float))
        arrivals, stock, i = list(rec.items()), 0.0, 0
        for day, day_rows in rows.groupby("date"):
            while i < len(arrivals) and arrivals[i][0] <= day:   # receipts up to and incl. today
                stock += float(arrivals[i][1])
                i += 1
            for r in day_rows.itertuples():
                q = float(r.qty)
                covered = min(max(stock, 0.0), q)
                stock -= q
                metered += covered
                short = q - covered
                if short > 1e-9:
                    unmetered_total += short
                    key = (r.unit_id, item, f"{day:%Y-%m}")
                    g = groups.setdefault(key, {"first": day, "last": day, "days": 0, "qty": 0.0})
                    g["last"], g["days"], g["qty"] = day, g["days"] + 1, g["qty"] + short
    for (unit, item, month), g in groups.items():
        price = float(items.loc[item, "list_price_eur"])
        qty = round(g["qty"], 3)
        unit_name = items.loc[item, "unit"]
        out.append(_exception(
            "consumed_not_purchased", unit_id=unit, ref=f"{unit}·{item}·{month}", kg=qty if unit_name == "kg" else 0.0,
            eur=round(qty * price, 2), when=g["first"],
            expected="consumption covered by recorded purchases",
            found=f"{qty:g} {unit_name} with no stock behind it",
            detail=f"{unit} consumed {qty:g} {unit_name} of {item} ({items.loc[item, 'name']}) "
                   f"from {g['first']:%d %b} to {g['last']:%d %b} with no purchase of it",
            extra={"item_code": item, "item": items.loc[item, "name"], "qty": qty,
                   "first": _js(g["first"].date()), "last": _js(g["last"].date()), "days": g["days"],
                   "list_price": price}))
    total = metered + unmetered_total
    rate = {"consumed": round(total, 3), "covered": round(metered, 3),
            "rate": round(metered / total, 4) if total else 0.0}
    return out, rate


def _exception(cls: str, *, unit_id, ref, kg, eur, when, expected, found, detail, extra=None) -> dict:
    label, sev, key = CLASSES[cls]
    return {"class": cls, "label": label, "severity": sev, "unit_id": unit_id, "ref": ref,
            "kg": round(float(kg), 3), "eur": round(float(eur), 2), "expected": expected,
            "found": found, "detail": detail, "date": _js(when), "cite": key,
            "citation": cite(key), **(extra or {})}


def run(write: bool = True) -> dict:
    data = frames(["readings", "commands", "alerts", "work_orders", "harvests", "shipments",
                   "purchases", "consumption", "items"])
    cmd_exc, cmd_rate = commanded_vs_observed(data)
    hv_exc, hv_rate = harvested_vs_shipped(data)
    su_exc, su_rate = consumed_vs_purchased(data)
    exceptions = sorted(cmd_exc + hv_exc + su_exc, key=lambda e: (-e["eur"], e["class"], e["date"] or ""))
    counts = {k: sum(e["class"] == k for e in exceptions) for k in CLASSES}
    _start, end = period()
    result = {
        "as_of": str((end - pd.Timedelta(days=1)).date()),
        "match": {"commands": cmd_rate, "harvest": hv_rate, "supplies": su_rate},
        "classes": {k: {"label": v[0], "severity": v[1], "cite": v[2]} for k, v in CLASSES.items()},
        "counts": counts,
        # money and kilograms per class and in total — the screens and the chat quote these
        "exposure": {k: round(sum(e["eur"] for e in exceptions if e["class"] == k), 2) for k in CLASSES},
        "exposure_kg": {k: round(sum(e["kg"] for e in exceptions if e["class"] == k), 3) for k in CLASSES},
        "exposure_total": round(sum(e["eur"] for e in exceptions), 2),
        "exposure_kg_total": round(sum(e["kg"] for e in exceptions), 3),
        "currency": currency(),
        "exceptions": exceptions,
    }
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "recon.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


# ---- one grow unit, every system ------------------------------------------------------

def unit_snapshot(unit_id: str, cur=None) -> dict | None:
    """What the five systems hold for one grow unit (JSON-safe), or None."""
    if cur is None:
        with _connect() as conn, conn.cursor() as c:
            return unit_snapshot(unit_id, c)
    uid = (unit_id or "").strip().upper()
    unit = _rows(cur, "SELECT * FROM telemetry.units WHERE unit_id = %(u)s", {"u": uid})
    if not unit:
        return None
    last = _rows(cur, """SELECT * FROM telemetry.readings WHERE unit_id = %(u)s
                         ORDER BY ts DESC LIMIT 1""", {"u": uid})
    span = _rows(cur, """SELECT count(*) AS readings, min(ts) AS first, max(ts) AS last,
                                round(avg(water_temp_c), 2) AS avg_water_temp_c,
                                round(avg(ph), 2) AS avg_ph,
                                round(avg(dissolved_o2_mg_l), 2) AS avg_do_mg_l,
                                min(water_level_cm) AS min_level_cm
                         FROM telemetry.readings WHERE unit_id = %(u)s""", {"u": uid})[0]
    alerts = _rows(cur, """SELECT alert_no, type, value, threshold, opened_ts, acknowledged_ts,
                                  acknowledged_by, resolved_ts, status
                           FROM controller.alerts WHERE unit_id = %(u)s ORDER BY opened_ts DESC""",
                   {"u": uid})
    commands = _rows(cur, """SELECT actuator, action, count(*) AS n FROM controller.commands
                             WHERE unit_id = %(u)s GROUP BY 1, 2 ORDER BY 1, 2""", {"u": uid})
    wos = _rows(cur, """SELECT w.work_order_no, w.opened_ts, w.type, w.alert_no, w.closed_ts,
                               w.outcome, w.part_item_code, w.notes, t.technician_code, t.name
                        FROM maintenance.work_orders w JOIN maintenance.technicians t USING (technician_id)
                        WHERE w.unit_id = %(u)s ORDER BY w.opened_ts DESC LIMIT 8""", {"u": uid})
    harvests = _rows(cur, """SELECT h.harvest_no, h.date, h.kg, h.logged_by, h.countersigned_by,
                                    s.shipment_ref, s.kg AS shipped_kg, s.eur
                             FROM harvest.harvests h
                             LEFT JOIN harvest.shipments s USING (harvest_no)
                             WHERE h.unit_id = %(u)s ORDER BY h.date DESC LIMIT 8""", {"u": uid})
    feed = _rows(cur, """SELECT item_code, to_char(date, 'YYYY-MM') AS month, round(sum(qty), 3) AS qty
                         FROM supplies.consumption WHERE unit_id = %(u)s
                         GROUP BY 1, 2 ORDER BY 2, 1""", {"u": uid})
    return {"unit": unit[0], "last_reading": last[0] if last else None, "readings": span,
            "alerts": alerts, "commands": commands, "work_orders": wos, "harvests": harvests,
            "consumption_by_month": feed}


# ---- the reconciliation call for one document ------------------------------------------

def check_document(fields: dict) -> dict:
    """Reconcile the fields extracted from one document against the farm systems.

    A supplier invoice carries invoice_no / po_no / supplier_ref / item_code / qty /
    unit_price / total; a water-lab report carries report_no / unit_id / sampled /
    ph / ammonia_mg_l / nitrite_mg_l / nitrate_mg_l / iron_mg_l.
    """
    f = {k: v for k, v in (fields or {}).items() if v not in (None, "")}
    if f.get("report_no") or f.get("sampled"):
        return _check_lab(f)
    return _check_invoice(f)


def _adder(checks: list, catalogue: list):
    labels = {cid: (label, db, key) for cid, label, db, key in catalogue}

    def add(cid: str, status: str, expected="", found="", detail: str = "") -> None:
        label, db, key = labels[cid]
        checks.append({"id": cid, "label": label, "status": status, "expected": expected,
                       "found": found, "db": db, "cite": key if status in ("fail", "warn") else None,
                       "detail": detail})
    return add


def _check_invoice(f: dict) -> dict:
    t0 = time.perf_counter()
    checks: list[dict] = []
    add = _adder(checks, INVOICE_CHECKS)
    po_no = str(f.get("po_no") or "").strip().upper()
    with _connect() as conn, conn.cursor() as cur:
        order = _rows(cur, """SELECT p.*, s.name AS supplier_name, s.approved, i.name AS item_name,
                                     i.unit AS item_unit
                              FROM supplies.purchases p
                              JOIN supplies.suppliers s USING (supplier_ref)
                              JOIN supplies.items i USING (item_code)
                              WHERE p.po_no = %(po)s""", {"po": po_no}) if po_no else []
        if not order and f.get("invoice_no"):
            order = _rows(cur, """SELECT p.*, s.name AS supplier_name, s.approved, i.name AS item_name,
                                         i.unit AS item_unit
                                  FROM supplies.purchases p JOIN supplies.suppliers s USING (supplier_ref)
                                  JOIN supplies.items i USING (item_code)
                                  WHERE p.invoice_no = %(inv)s""", {"inv": f["invoice_no"]})
        doc_supplier = str(f.get("supplier_ref") or "").strip().upper()
        supplier = _rows(cur, "SELECT * FROM supplies.suppliers WHERE supplier_ref = %(s)s",
                         {"s": doc_supplier}) if doc_supplier else []

    def result(verdict: str) -> dict:
        return {"kind": "invoice", "ref": f.get("invoice_no") or po_no or None, "po_no": po_no or None,
                "verdict": verdict, "checks": checks,
                "discrepancies": [c for c in checks if c["status"] == "fail"],
                "record": order[0] if order else {}, "currency": currency(), "fields": f,
                "tolerance": {"price_pct": PRICE_TOLERANCE},
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}

    if not order:
        add("order_exists", "fail", po_no or "a purchase order number on the invoice",
            "not found in supplies", "No purchase order matches this invoice.")
        for cid, *_ in INVOICE_CHECKS[1:]:
            add(cid, "skip")
        return result("not_found")
    o = order[0]
    add("order_exists", "pass", o["po_no"],
        f"{o['po_no']} · {o['item_code']} · ordered {o['ordered']} · received {o['received']}")
    if not doc_supplier:
        add("supplier_matches_order", "skip", "", "", "No supplier ref on the invoice.")
        add("supplier_approved", "skip")
    else:
        same = doc_supplier == o["supplier_ref"]
        add("supplier_matches_order", "pass" if same else "fail",
            f"{o['supplier_ref']} ({o['supplier_name']})",
            f"{doc_supplier}" + (f" ({supplier[0]['name']})" if supplier else " (unknown)"),
            "" if same else "The invoice comes from a supplier other than the one ordered from — "
                            "hold it and verify by the phone number on file.")
        approved = bool(supplier and supplier[0]["approved"])
        add("supplier_approved", "pass" if approved else "fail", "on the approved supplier list",
            f"{doc_supplier} " + ("approved" if approved else
                                  "not on the list" if supplier else "not in the supplier master"))
    item = str(f.get("item_code") or "").strip().upper()
    if item:
        add("item_matches_order", "pass" if item == o["item_code"] else "fail",
            f"{o['item_code']} {o['item_name']}", item)
    else:
        add("item_matches_order", "skip", "", "", "No item code on the invoice.")
    qty = f.get("qty")
    if qty is None:
        add("quantity_matches_receipt", "skip", "", "", "No quantity on the invoice.")
    else:
        ok = abs(float(qty) - float(o["qty"])) < 1e-6 and o["received"] is not None
        add("quantity_matches_receipt", "pass" if ok else "fail",
            f"{float(o['qty']):g} {o['item_unit']} received {o['received']}",
            f"{float(qty):g} {o['item_unit']}")
    price = f.get("unit_price")
    if price is None and f.get("total") is not None and qty:
        price = round(float(f["total"]) / float(qty), 2)
    if price is None:
        add("price_within_tolerance", "skip", "", "", "No unit price on the invoice.")
    else:
        agreed = float(o["unit_price_eur"])
        ceiling = round(agreed * (1 + PRICE_TOLERANCE), 2)
        over = float(price) / agreed - 1
        within = float(price) <= ceiling + 0.005
        q = float(qty) if qty is not None else float(o["qty"])
        add("price_within_tolerance", "pass" if within else "fail",
            f"≤ {_money(ceiling)} per {o['item_unit']} (order price {_money(agreed)} + 5%)",
            f"{_money(float(price))} per {o['item_unit']} ({over:+.1%})",
            "" if within else f"{over:+.1%} over the order price — "
                              f"{(float(price) - agreed) * q:,.2f} {currency()} above the order "
                              f"on {q:g} {o['item_unit']}.")
    if o["status"] == "awaiting_invoice":
        add("not_already_invoiced", "pass", "awaiting its invoice", o["status"])
    else:
        add("not_already_invoiced", "fail", "awaiting its invoice",
            f"already invoiced as {o['invoice_no']}",
            "This order was already invoiced — paying again would pay twice.")
    verdict = "discrepancy" if any(c["status"] == "fail" for c in checks) else "clean"
    return result(verdict)


def _check_lab(f: dict) -> dict:
    t0 = time.perf_counter()
    checks: list[dict] = []
    add = _adder(checks, LAB_CHECKS)
    unit = str(f.get("unit_id") or "").strip().upper()
    sampled = pd.Timestamp(str(f["sampled"])) if f.get("sampled") else None
    with _connect() as conn, conn.cursor() as cur:
        exists = _rows(cur, "SELECT * FROM telemetry.units WHERE unit_id = %(u)s", {"u": unit}) if unit else []
        reading = _rows(cur, """SELECT ts, ph FROM telemetry.readings
                                WHERE unit_id = %(u)s AND ts BETWEEN %(a)s AND %(b)s
                                ORDER BY abs(extract(epoch FROM ts - %(t)s)) LIMIT 1""",
                        {"u": unit, "a": sampled - pd.Timedelta(minutes=30),
                         "b": sampled + pd.Timedelta(minutes=30), "t": sampled}) \
            if exists and sampled is not None else []

    def result(verdict: str) -> dict:
        return {"kind": "lab", "ref": f.get("report_no"), "unit_id": unit or None, "verdict": verdict,
                "checks": checks, "discrepancies": [c for c in checks if c["status"] == "fail"],
                "record": {"unit": exists[0] if exists else None, "reading": reading[0] if reading else None},
                "currency": currency(), "fields": f,
                "tolerance": {"ph_probe": PH_PROBE_TOLERANCE},
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}

    if not exists:
        add("unit_exists", "fail", unit or "a grow unit on the report", "not found in telemetry")
        for cid, *_ in LAB_CHECKS[1:]:
            add(cid, "skip")
        return result("not_found")
    add("unit_exists", "pass", unit, f"{unit} · {exists[0]['plant']} · {exists[0]['location']}")
    lab_ph = f.get("ph")
    if not reading:
        add("probe_reading", "warn", f"a reading within 30 min of {f.get('sampled')}", "none (gap)",
            "The probe has no reading at the sample time — compare with the nearest one.")
        add("ph_matches_probe", "skip")
    else:
        add("probe_reading", "pass", f"within 30 min of {f.get('sampled')}",
            f"{reading[0]['ts']} · probe pH {float(reading[0]['ph']):.2f}")
        if lab_ph is None:
            add("ph_matches_probe", "skip", "", "", "No pH on the report.")
        else:
            diff = float(reading[0]["ph"]) - float(lab_ph)
            ok = abs(diff) <= PH_PROBE_TOLERANCE + 1e-9
            add("ph_matches_probe", "pass" if ok else "fail",
                f"probe {float(reading[0]['ph']):.2f} ± {PH_PROBE_TOLERANCE}",
                f"lab {float(lab_ph):.2f} ({diff:+.2f} probe − lab)",
                "" if ok else "The probe reads off the lab value by more than 0.2 — recalibrate it "
                              "before trusting its readings or the drift built on them.")
    for cid in ("ph", "ammonia_mg_l", "nitrite_mg_l", "nitrate_mg_l", "iron_mg_l"):
        lo, hi, label = LAB_BANDS[cid]
        check_id = "ph_in_band" if cid == "ph" else cid
        v = f.get(cid)
        if v is None:
            add(check_id, "skip", "", "", f"No {label} on the report.")
            continue
        band = (f"{lo:g}–{hi:g}" if lo is not None else f"< {hi:g}") + ("" if cid == "ph" else " mg/L")
        ok = float(v) < hi if lo is None else lo <= float(v) <= hi
        add(check_id, "pass" if ok else "fail", band, f"{float(v):g}")
    verdict = "discrepancy" if any(c["status"] == "fail" for c in checks) else "clean"
    return result(verdict)


if __name__ == "__main__":
    r = run()
    print("match:", r["match"])
    print("counts:", r["counts"], "exposure:", r["exposure"], "total", r["exposure_total"])
