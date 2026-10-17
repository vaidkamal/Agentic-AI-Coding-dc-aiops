"""Simulated hall: same shape the console expects. Use until real feeds are wired."""
import random
ZONES = "ABCD"
_racks = [{"id": f"{z}-0{i}", "zone": z, "servers": 18 + random.randint(0, 11),
           "inletC": 21.0 + random.random() * 2, "cpu": 40 + random.randint(0, 25)}
          for z in ZONES for i in range(1, 7)]

async def snapshot():
    out = []
    for r in _racks:
        r["inletC"] = round(r["inletC"] + (21.5 - r["inletC"]) * .2 + random.uniform(-.4, .4), 1)
        r["cpu"] = max(5, min(100, r["cpu"] + random.randint(-3, 3)))
        out.append({**r, "powerKw": round(r["servers"] * .42 + r["cpu"] * .03, 1), "online": True})
    it = sum(x["powerKw"] for x in out)
    return {"racks": out, "itLoadKw": round(it, 1), "pue": round(1.38 + random.uniform(-.01, .01), 3)}
