"""Prometheus adapter. Expects per-rack series labelled rack="A-01", zone="A".
Override the PromQL via env if your exporters use different metric names (PROM_Q_*)."""
import os, asyncio, httpx
URL = os.getenv("PROM_URL", "http://localhost:9090")
Q = {
 "inletC":  os.getenv("PROM_Q_INLET",  'avg by (rack,zone) (dc_rack_inlet_celsius)'),
 "cpu":     os.getenv("PROM_Q_CPU",    'avg by (rack,zone) (100 - rate(node_cpu_seconds_total{mode="idle"}[1m])*100)'),
 "powerKw": os.getenv("PROM_Q_POWER",  'sum by (rack,zone) (pdu_outlet_power_watts) / 1000'),
 "servers": os.getenv("PROM_Q_UP",     'count by (rack,zone) (up == 1)'),
}
FACILITY = os.getenv("PROM_Q_FACILITY", "")

async def _q(c, expr):
    r = await c.get(f"{URL}/api/v1/query", params={"query": expr}); r.raise_for_status()
    return r.json()["data"]["result"]

async def snapshot():
    async with httpx.AsyncClient(timeout=5) as c:
        res = await asyncio.gather(*[_q(c, e) for e in Q.values()])
        fac = (await _q(c, FACILITY)) if FACILITY else []
    racks = {}
    for key, rows in zip(Q.keys(), res):
        for row in rows:
            rid = row["metric"].get("rack"); zone = row["metric"].get("zone", rid[:1] if rid else "?")
            racks.setdefault(rid, {"id": rid, "zone": zone, "online": True})
            racks[rid][key] = round(float(row["value"][1]), 1)
    out = []
    for r in racks.values():
        for k in ("servers", "cpu", "inletC", "powerKw"): r.setdefault(k, 0)
        r["servers"] = int(r["servers"]); r["online"] = r["servers"] > 0 and r["powerKw"] > 0.1
        out.append(r)
    it = sum(r["powerKw"] for r in out)
    pue = round(float(fac[0]["value"][1]) / it, 3) if fac and it else None
    return {"racks": sorted(out, key=lambda r: r["id"]), "itLoadKw": round(it, 1), "pue": pue}
