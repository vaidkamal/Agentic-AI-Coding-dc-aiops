"""ServiceNow Table API. Env: SNOW_INSTANCE SNOW_USER SNOW_PASS SNOW_ASSIGNMENT_GROUP"""
import os, httpx
BASE = os.getenv("SNOW_INSTANCE", ""); AUTH = (os.getenv("SNOW_USER", ""), os.getenv("SNOW_PASS", ""))
URG = {"crit": "1", "warn": "2"}

async def create(inc):
    body = {"short_description": f"[{inc['id']}] {inc['title']}", "urgency": URG.get(inc["sev"], "3"),
            "impact": URG.get(inc["sev"], "3"), "category": "hardware",
            "assignment_group": os.getenv("SNOW_ASSIGNMENT_GROUP", "DC Operations"),
            "description": f"{inc['summary']}\n\nProbable cause ({int(inc['conf']*100)}%): {inc['rca']}\nRunbook: {inc['runbook']}"}
    async with httpx.AsyncClient(auth=AUTH, timeout=10) as c:
        r = await c.post(f"{BASE}/api/now/table/incident", json=body); r.raise_for_status()
        return r.json()["result"]["sys_id"]

async def comment(sys_id, text):
    async with httpx.AsyncClient(auth=AUTH, timeout=10) as c:
        await c.patch(f"{BASE}/api/now/table/incident/{sys_id}", json={"work_notes": text})

async def resolve(sys_id):
    async with httpx.AsyncClient(auth=AUTH, timeout=10) as c:
        await c.patch(f"{BASE}/api/now/table/incident/{sys_id}",
                      json={"state": "6", "close_code": "Solved (Permanently)", "close_notes": "Auto-resolved by AIOps after metrics normalised"})
