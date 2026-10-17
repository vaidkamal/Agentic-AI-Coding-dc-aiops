#!/usr/bin/env python3
"""Run the golden cases (T1-T8) through the triage service and apply deterministic checks.

    python evals/run_cases.py --mock                 # canned outputs, no paid calls
    python evals/run_cases.py --live                 # real model; prints the cost estimate
                                                     # and waits for `y` on stdin before any call

Verdict vocabulary (observability-runbook section F): pass / fail / unable_to_assess /
not_applicable / budget_blocked. Failures are reported as failures / assessed cases; unassessed
cases are listed separately. Results are written to evals/results/<timestamp>.json.

Checks are keyed by the case's `expect` entries:
  kind, key, sev, runbook                 exact value (null allowed)
  missing_fields, clarification_fields    exact list (order-insensitive)
  <field>_contains                        every substring present (lists: every item present)
  <field>_contains_any                    at least one substring present (case-insensitive)
  <field>_not                             value differs
  <field>_not_contains                    none of the substrings present (case-insensitive)
  reply_asks_question                     reply ends with '?'
  reply_language: "en"                    ASCII-letters heuristic (no diacritics / non-Latin script)
The judge rubric (evals/judge_rubric.md) is a separate, on-request step; it is not run here.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))

from ai import tracing  # noqa: E402
from ai.budget import Budget, BudgetExhausted  # noqa: E402
from ai.schemas import TriageRequest  # noqa: E402
from ai.triage import (  # noqa: E402
    MAX_TOKENS,
    PROMPT_VERSION,
    RULES_VERSION,
    ModelUnavailable,
    TriageService,
    UnusableOutput,
    estimate_input_tokens,
    triage_with_budget,
)
from mock_client import FakeAnthropic, load_cases, load_mock_outputs  # noqa: E402

GRADER_VERSION = "v1"
VERDICTS = ("pass", "fail", "unable_to_assess", "not_applicable", "budget_blocked")


# ---- deterministic checks -------------------------------------------------------


def _field(response: dict[str, Any], name: str) -> Any:
    if name in response["draft"]:
        return response["draft"][name]
    return response.get(name)


def _is_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isascii() for c in letters)


def evaluate(expect: dict[str, Any], response: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, verdict: str, detail: str) -> None:
        checks.append({"check": name, "verdict": verdict, "detail": detail})

    for key, want in expect.items():
        if key == "reply_asks_question":
            reply = (response.get("reply") or "").rstrip()
            ok = reply.endswith("?") == bool(want)
            add(key, "pass" if ok else "fail", f"reply ends with '?': {reply.endswith('?')}")
        elif key == "reply_language":
            reply = response.get("reply") or ""
            if want != "en":
                add(key, "not_applicable", f"no heuristic for language {want!r}")
                continue
            ok = _is_english(reply)
            add(key, "pass" if ok else "fail", "ascii-letter heuristic" + ("" if ok else f": {reply[:60]!r}"))
        elif key.endswith("_contains_any"):
            field = key[: -len("_contains_any")]
            got = _field(response, field)
            text = (got if isinstance(got, str) else json.dumps(got)).lower()
            hit = [w for w in want if w.lower() in text]
            add(key, "pass" if hit else "fail", f"{field} contains any of {want}: {hit or 'none'}")
        elif key.endswith("_not_contains"):
            field = key[: -len("_not_contains")]
            got = _field(response, field)
            text = (got if isinstance(got, str) else json.dumps(got)).lower()
            hit = [w for w in want if w.lower() in text]
            add(key, "fail" if hit else "pass", f"{field} must not contain {want}: found {hit or 'none'}")
        elif key.endswith("_contains"):
            field = key[: -len("_contains")]
            got = _field(response, field)
            if isinstance(got, list):
                missing = [w for w in want if w not in got]
            else:
                text = got if isinstance(got, str) else ""
                missing = [w for w in want if w not in text]
            add(key, "fail" if missing else "pass", f"{field} contains {want}: missing {missing or 'none'}")
        elif key.endswith("_not"):
            field = key[: -len("_not")]
            got = _field(response, field)
            add(key, "fail" if got == want else "pass", f"{field} != {want!r}: got {got!r}")
        elif key in ("kind", "key", "sev", "runbook", "summary", "probable_cause"):
            got = _field(response, key)
            add(key, "pass" if got == want else "fail", f"{key} == {want!r}: got {got!r}")
        elif key in ("missing_fields", "clarification_fields"):
            got = response.get(key) or []
            ok = sorted(got) == sorted(want)
            add(key, "pass" if ok else "fail", f"{key} == {sorted(want)}: got {sorted(got)}")
        else:
            add(key, "not_applicable", "no deterministic check for this expectation")
    return checks


def case_verdict(checks: list[dict[str, Any]]) -> str:
    verdicts = [c["verdict"] for c in checks]
    if any(v == "fail" for v in verdicts):
        return "fail"
    if any(v == "pass" for v in verdicts):
        return "pass"
    return "not_applicable"


# ---- running --------------------------------------------------------------------


def build_request(case: dict[str, Any], now: str) -> TriageRequest:
    req = case["request"]
    return TriageRequest.model_validate(
        {
            "text": req["text"],
            "draft": req.get("draft"),
            "history": req.get("history", []),
            "context": {"hall": req.get("hall", "H2"), "now": now},
        }
    )


async def run_case(
    case: dict[str, Any], service: TriageService, budget: Budget, now: str
) -> dict[str, Any]:
    request_id = f"eval_{case['id']}_{secrets.token_hex(4)}"
    record: dict[str, Any] = {
        "id": case["id"],
        "family": case["family"],
        "dimensions": case.get("dimensions", []),
        "request_id": request_id,
        "evidence": case.get("evidence"),
        "response": None,
        "usage": None,
        "checks": [],
        "verdict": None,
        "reason": None,
    }
    try:
        result = await triage_with_budget(service, budget, build_request(case, now), request_id)
    except BudgetExhausted as e:
        record.update(verdict="budget_blocked", reason=str(e))
        return record
    except (ModelUnavailable, UnusableOutput) as e:
        kind = "model unavailable" if isinstance(e, ModelUnavailable) else "unusable model output"
        record.update(verdict="unable_to_assess", reason=f"{kind}: {e.reason}")
        if e.usage is not None:
            record["usage"] = {"input_tokens": e.usage.input_tokens, "output_tokens": e.usage.output_tokens}
        return record
    response = result.response.model_dump()
    record["response"] = response
    record["usage"] = {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens}
    record["checks"] = evaluate(case["expect"], response)
    record["verdict"] = case_verdict(record["checks"])
    return record


def summarise(records: list[dict[str, Any]]) -> OrderedDict[str, dict[str, int]]:
    families: OrderedDict[str, dict[str, int]] = OrderedDict()
    for r in records:
        fam = families.setdefault(r["family"], {v: 0 for v in VERDICTS} | {"cases": 0})
        fam["cases"] += 1
        fam[r["verdict"]] += 1
    return families


def print_report(records: list[dict[str, Any]], families: OrderedDict, cost_usd: float, mode: str) -> None:
    print()
    print(f"{'family':<18}{'cases':>6}{'pass':>6}{'fail':>6}{'unable':>8}{'n/a':>6}{'budget':>8}")
    print("-" * 58)
    for name, f in families.items():
        print(
            f"{name:<18}{f['cases']:>6}{f['pass']:>6}{f['fail']:>6}"
            f"{f['unable_to_assess']:>8}{f['not_applicable']:>6}{f['budget_blocked']:>8}"
        )
    totals = {v: sum(f[v] for f in families.values()) for v in VERDICTS}
    assessed = totals["pass"] + totals["fail"]
    print("-" * 58)
    print(f"{'total':<18}{len(records):>6}{totals['pass']:>6}{totals['fail']:>6}"
          f"{totals['unable_to_assess']:>8}{totals['not_applicable']:>6}{totals['budget_blocked']:>8}")
    rate = f"{totals['fail']}/{assessed}" if assessed else "n/a"
    print(f"\nfailures / assessed cases: {rate}   unassessed: "
          f"{totals['unable_to_assess'] + totals['not_applicable'] + totals['budget_blocked']}")
    print(f"mode: {mode}   cost: ${cost_usd:.4f}")
    print()
    for r in records:
        line = f"  {r['id']:<4} {r['family']:<16} {r['verdict']:<17} {r['request_id']}"
        if r["verdict"] == "fail":
            bad = [f"{c['check']} ({c['detail']})" for c in r["checks"] if c["verdict"] == "fail"]
            line += "\n       failed: " + "; ".join(bad)
        elif r["reason"]:
            line += f"\n       {r['reason']}"
        print(line)


def confirm_live(cases: list[dict[str, Any]], budget: Budget, now: str, model: str) -> bool:
    est = sum(budget.estimate_usd(estimate_input_tokens(build_request(c, now)), MAX_TOKENS) for c in cases)
    print(f"Live run: {len(cases)} calls to {model}")
    print(f"  estimated upper-bound cost: ${est:.4f}  (reserve per call = input estimate + {MAX_TOKENS} output tokens)")
    print(f"  month-to-date: ${budget.mtd_usd():.4f} of ${budget.monthly_usd:.2f} (AI_MONTHLY_BUDGET_USD)")
    sys.stdout.write("Proceed? [y/N] ")
    sys.stdout.flush()
    answer = sys.stdin.readline().strip().lower()
    return answer == "y"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=str(HERE / "golden" / "cases.json"))
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="canned outputs from evals/mock_outputs.json")
    mode.add_argument("--live", action="store_true", help="real model calls after budget approval")
    ap.add_argument("--results-dir", default=str(HERE / "results"))
    args = ap.parse_args(argv)

    cases = load_cases(args.cases)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tracing.setup_tracing()
    tracing.set_common_attributes(**{"grader.version": GRADER_VERSION})

    if args.mock:
        run_mode = "mock"
        service = TriageService(client=FakeAnthropic(load_mock_outputs(), cases, model="mock"), model="mock")
        budget = Budget(db_path=None)
    else:
        run_mode = "live"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set; aborting.", file=sys.stderr)
            return 2
        service = TriageService()
        budget = Budget()
        if not confirm_live(cases, budget, now, service.model):
            print("Aborted: no approval for paid calls.")
            return 2

    before = budget.mtd_usd()
    records = [asyncio.run(run_case(c, service, budget, now)) for c in cases]
    cost = budget.mtd_usd() - before
    families = summarise(records)
    print_report(records, families, cost, run_mode)

    out_dir = Path(args.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"{stamp}.json"
    payload = {
        "run": {
            "mode": run_mode,
            "timestamp": now,
            "model": service.model,
            "prompt_version": PROMPT_VERSION,
            "rules_version": RULES_VERSION,
            "grader.version": GRADER_VERSION,
            "cases_file": str(Path(args.cases)),
            "tracing": tracing.tracing_status(),
            "cost_usd": round(cost, 6),
        },
        "by_family": families,
        "cases": records,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nresults written to {out}")

    failed = any(r["verdict"] == "fail" for r in records)
    unassessed_in_mock = run_mode == "mock" and any(r["verdict"] != "pass" for r in records)
    return 1 if failed or unassessed_in_mock else 0


if __name__ == "__main__":
    sys.exit(main())
