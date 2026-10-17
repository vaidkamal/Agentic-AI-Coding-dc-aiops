#!/usr/bin/env bash
# Definition of done (CLAUDE.md). Exit non-zero on any failing check; one summary line per check.
#   1. ruff (when installed)         lint backend/ and evals/
#   2. pytest -q                     backend contract, AI triage (AI-1..AI-8), tracing (OBS-1..3)
#   3. run_cases.py --mock           golden cases T1-T8 with canned outputs, no paid calls
#   4. AI-6                          no code path from backend/ai/ to the write path
#   5. frontend external scripts     <script src> only from cdnjs; stylesheets only from Google Fonts
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
fail=0
results=()

report() {  # name, status(0/1/2), detail
  local tag
  case "$2" in 0) tag="PASS";; 2) tag="SKIP";; *) tag="FAIL"; fail=1;; esac
  results+=("$(printf '%-5s %-22s %s' "$tag" "$1" "$3")")
}

# 1. ruff
if command -v ruff >/dev/null 2>&1; then
  if out=$(ruff check backend evals 2>&1); then report ruff 0 "backend/ evals/ clean"
  else echo "$out" | tail -20; report ruff 1 "$(echo "$out" | tail -1)"; fi
else
  report ruff 2 "ruff not installed (pip install ruff)"
fi

# 2. pytest
if out=$(cd backend && "$PY" -m pytest -q 2>&1); then
  report pytest 0 "$(echo "$out" | grep -E '^[0-9]+ passed' | tail -1 || echo "$out" | tail -1)"
else
  echo "$out" | tail -40; report pytest 1 "$(echo "$out" | tail -1)"
fi

# 3. golden cases, mocked
if out=$("$PY" evals/run_cases.py --mock 2>&1); then
  report evals-mock 0 "$(echo "$out" | grep -E 'failures / assessed' | head -1)"
else
  echo "$out" | tail -30; report evals-mock 1 "$(echo "$out" | grep -E 'failures / assessed' | head -1 || echo 'runner failed')"
fi

# 4. AI-6: no code path from the AI module to POST /incidents
if grep -r "incidents" backend/ai/ >/dev/null 2>&1; then
  grep -rn "incidents" backend/ai/ | head -5
  report ai-6-no-write-path 1 "backend/ai/ mentions the write path"
else
  report ai-6-no-write-path 0 "grep -r incidents backend/ai/ is empty"
fi

# 5. frontend: external scripts only from cdnjs, stylesheets only from Google Fonts
if [ -f frontend/index.html ]; then
  bad=$(grep -oE '<script[^>]*src="https?://[^"/]+' frontend/index.html | grep -oE 'https?://[^"/]+' | grep -vE '^https://cdnjs\.cloudflare\.com$' || true)
  badcss=$(grep -oE '<link[^>]*href="https?://[^"/]+' frontend/index.html | grep -oE 'https?://[^"/]+' | grep -vE '^https://fonts\.(googleapis|gstatic)\.com$' || true)
  if [ -z "$bad" ] && [ -z "$badcss" ]; then
    report frontend-hosts 0 "scripts: cdnjs only; stylesheets: Google Fonts only"
  else
    report frontend-hosts 1 "disallowed hosts: $(echo "$bad $badcss" | xargs)"
  fi
else
  report frontend-hosts 1 "frontend/index.html missing"
fi

echo
echo "verify.sh summary"
for line in "${results[@]}"; do echo "  $line"; done
if [ "$fail" -ne 0 ]; then echo "RESULT: FAIL"; exit 1; fi
echo "RESULT: GREEN"
