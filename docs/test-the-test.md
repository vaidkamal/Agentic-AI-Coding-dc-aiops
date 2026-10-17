# Test the test — deliberate faults (Weekend 2 p.22, Weekend 4 §6.3.1)

| Date | Fault introduced | Expected | Observed | Restored |
|---|---|---|---|---|
| 2026-10-17 | `Incident.kind` enum relaxed to `str` | `test_incident_enums_422` goes red | 1 failed (201 instead of 422) | yes, green again |
| 2026-10-17 | Reference to the incidents write path added inside `backend/ai/` | AI-6 guard and `verify.sh` go red | both red | yes |
| 2026-10-17 | Zone suppression removed in console `detect()` (manual, browser) | AC-2: per-rack incidents appear alongside the zone incident | 3 extra warnings observed | yes |
A surviving edit would have meant a missing check. None survived.
