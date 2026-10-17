"""Jira Cloud REST v3. Env: JIRA_URL JIRA_EMAIL JIRA_TOKEN JIRA_PROJECT JIRA_DONE_TRANSITION"""
import os, httpx
BASE = os.getenv("JIRA_URL", ""); AUTH = (os.getenv("JIRA_EMAIL", ""), os.getenv("JIRA_TOKEN", ""))
PRIO = {"crit": "Highest", "warn": "High"}
def _doc(t): return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": t}]}]}

async def create(inc):
    body = {"fields": {"project": {"key": os.getenv("JIRA_PROJECT", "DCOPS")}, "issuetype": {"name": "Incident"},
            "summary": f"[{inc['id']}] {inc['title']}", "priority": {"name": PRIO.get(inc["sev"], "Medium")},
            "description": _doc(f"{inc['summary']}\nProbable cause ({int(inc['conf']*100)}%): {inc['rca']}\nRunbook: {inc['runbook']}")}}
    async with httpx.AsyncClient(auth=AUTH, timeout=10) as c:
        r = await c.post(f"{BASE}/rest/api/3/issue", json=body); r.raise_for_status()
        return r.json()["key"]

async def comment(key, text):
    async with httpx.AsyncClient(auth=AUTH, timeout=10) as c:
        await c.post(f"{BASE}/rest/api/3/issue/{key}/comment", json={"body": _doc(text)})

async def resolve(key):
    async with httpx.AsyncClient(auth=AUTH, timeout=10) as c:
        await c.post(f"{BASE}/rest/api/3/issue/{key}/transitions",
                     json={"transition": {"id": os.getenv("JIRA_DONE_TRANSITION", "31")}})
