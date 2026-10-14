"""Patterns — who touches which unit, with what outcome, and the records that
do not add up when you look at the person behind them.

  graph        technician ↔ grow unit, weighted by work orders and harvest logs
  ghost loop   harvests a technician logged that nobody countersigned and
               nothing shipped (harvest-shipping-procedure §2–3)
  dropouts     sensor gaps per unit and the work order that followed
               (sensor-calibration §4)
  response     time from an alert to its work order against the SOP's 2 hours
               (pump-maintenance-sop §3, alert-escalation §3)

Artifact: data/analytics/patterns.json — consumed by the Patterns page and the
pattern_scan tool.
"""

from __future__ import annotations

import json

import networkx as nx
import pandas as pd

from new_horizons.app.analytics.dataio import OUT, cite, frames, period
from new_horizons.app.analytics.drift import gaps

LIVESTOCK = {"low_water_level", "low_dissolved_o2", "high_water_temp"}
SOP_HOURS = 2.0


def _iso(t) -> str | None:
    return None if t is None or pd.isna(t) else pd.Timestamp(t).isoformat(timespec="minutes")


def run(write: bool = True) -> dict:
    data = frames(["technicians", "work_orders", "harvests", "shipments", "alerts", "readings", "units"])
    tech, wo, hv, sh = data["technicians"], data["work_orders"], data["harvests"], data["shipments"]
    alerts, rd = data["alerts"], data["readings"]
    code_of = dict(zip(tech.technician_id, tech.technician_code))
    name_of = dict(zip(tech.technician_code, tech.name))
    wo = wo.assign(technician_code=wo.technician_id.map(code_of))
    shipped = set(sh.harvest_no)
    _start, end = period()
    hv = hv.assign(shipped=hv.harvest_no.isin(shipped),
                   countersigned=hv.countersigned_by.notna() & (hv.countersigned_by != ""))

    # ---- per technician ---------------------------------------------------------------
    stats = []
    for code in tech.technician_code:
        mine_wo, mine_hv = wo[wo.technician_code == code], hv[hv.logged_by == code]
        unshipped = mine_hv[~mine_hv.shipped & (mine_hv.date + pd.Timedelta(hours=48) <= end)]
        stats.append({
            "technician_code": code, "name": name_of[code],
            "role": tech.set_index("technician_code").loc[code, "role"],
            "work_orders": int(len(mine_wo)), "closed": int(mine_wo.closed_ts.notna().sum()),
            "no_fault_found": int((mine_wo.outcome == "no_fault_found").sum()),
            "units": sorted(set(mine_wo.unit_id) | set(mine_hv.unit_id)),
            "harvests_logged": int(len(mine_hv)), "harvests_unshipped": int(len(unshipped)),
            "harvests_uncountersigned": int((~mine_hv.countersigned).sum()),
            "unshipped_share": round(len(unshipped) / len(mine_hv), 3) if len(mine_hv) else 0.0,
        })

    # ---- the ghost loop: a person whose harvests never leave ---------------------------
    loops = []
    for s in stats:
        if s["harvests_unshipped"] >= 2:
            rows = hv[(hv.logged_by == s["technician_code"]) & ~hv.shipped
                      & (hv.date + pd.Timedelta(hours=48) <= end)].sort_values("date")
            others = [x["unshipped_share"] for x in stats if x is not s and x["harvests_logged"]]
            loops.append({
                "technician_code": s["technician_code"], "name": s["name"],
                "harvests": [{"harvest_no": r.harvest_no, "date": str(r.date.date()), "unit_id": r.unit_id,
                              "plant": r.plant, "kg": round(float(r.kg), 2),
                              "weekday": r.date.day_name(),
                              "countersigned_by": r.countersigned_by if isinstance(r.countersigned_by, str) else None}
                             for r in rows.itertuples()],
                "count": int(len(rows)), "kg": round(float(rows.kg.sum()), 2),
                "units": sorted(set(rows.unit_id)),
                "uncountersigned": int((~rows.countersigned).sum()),
                "logged": s["harvests_logged"], "share": s["unshipped_share"],
                "others_max_share": max(others) if others else 0.0,
                "citation": cite("harvest_countersign"),
            })

    # ---- alert response against the SOP -----------------------------------------------
    response = []
    for a in alerts.sort_values("opened_ts").itertuples():
        w = wo[wo.alert_no == a.alert_no].sort_values("opened_ts")
        first = w.iloc[0] if len(w) else None
        hours = round((first.opened_ts - a.opened_ts).total_seconds() / 3600, 2) if first is not None else None
        ack = round((a.acknowledged_ts - a.opened_ts).total_seconds() / 60, 1) \
            if not pd.isna(a.acknowledged_ts) else None
        response.append({"alert_no": a.alert_no, "unit_id": a.unit_id, "type": a.type,
                         "opened": _iso(a.opened_ts), "ack_minutes": ack,
                         "work_order_no": None if first is None else first.work_order_no,
                         "technician_code": None if first is None else first.technician_code,
                         "response_hours": hours,
                         "late": a.type in LIVESTOCK and (hours is None or hours > SOP_HOURS)})

    # ---- sensor dropouts and their follow-up -------------------------------------------
    dropouts = []
    for g in gaps(rd, *period()):
        t_end = pd.Timestamp(g["end"])
        follow = wo[(wo.unit_id == g["unit_id"]) & (wo.type == "sensor_check")
                    & (wo.opened_ts >= t_end) & (wo.opened_ts <= t_end + pd.Timedelta(hours=4))]
        dropouts.append({**g, "work_order_no": follow.iloc[0].work_order_no if len(follow) else None,
                         "needs_work_order": g["hours"] > 4})

    # ---- the graph: technician ↔ unit -----------------------------------------------------
    G = nx.Graph()
    units = sorted(data["units"].unit_id)
    for u in units:
        G.add_node(u, kind="unit", label=u)
    for s in stats:
        G.add_node(s["technician_code"], kind="technician", label=f"{s['technician_code']} · {s['name']}")
    edge_rows = _edges(wo, hv, end)
    loop_codes = {lp["technician_code"] for lp in loops}
    for (code, unit), e in edge_rows.items():
        G.add_edge(code, unit, work_orders=e["work_orders"], harvests=e["harvests"],
                   unshipped=e["unshipped"], loop=code in loop_codes and e["unshipped"] > 0)
    pos = nx.spring_layout(G, seed=2019, k=0.9)
    graph = {"nodes": [{"id": n, **G.nodes[n], "x": float(pos[n][0]), "y": float(pos[n][1])} for n in G.nodes],
             "edges": [{"a": u, "b": v, **G.edges[u, v]} for u, v in G.edges]}

    result = {
        "technicians": stats, "ghost_loops": loops, "response": response,
        "late_responses": [r for r in response if r["late"]],
        "dropouts": dropouts, "graph": graph, "sop_hours": SOP_HOURS,
        "citations": {"countersign": cite("harvest_countersign"), "shipment": cite("harvest_shipment_match"),
                      "response": cite("pump_response"), "dropout": cite("sensor_dropout")},
    }
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "patterns.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    return result


def _edges(wo: pd.DataFrame, hv: pd.DataFrame, end: pd.Timestamp) -> dict:
    edges: dict[tuple, dict] = {}
    for r in wo.itertuples():
        e = edges.setdefault((r.technician_code, r.unit_id), {"work_orders": 0, "harvests": 0, "unshipped": 0})
        e["work_orders"] += 1
    for r in hv.itertuples():
        e = edges.setdefault((r.logged_by, r.unit_id), {"work_orders": 0, "harvests": 0, "unshipped": 0})
        e["harvests"] += 1
        e["unshipped"] += int(not r.shipped and r.date + pd.Timedelta(hours=48) <= end)
    return edges


if __name__ == "__main__":
    r = run()
    print("loops:", [(lp["technician_code"], lp["count"], lp["kg"], lp["share"], lp["others_max_share"])
                     for lp in r["ghost_loops"]])
    print("late:", [(x["alert_no"], x["unit_id"], x["response_hours"]) for x in r["late_responses"]])
    print("dropouts:", r["dropouts"])
