# frontend-spec.md — DC-North AIOps Console

<!-- Weekend 3, Lecture 5: screens and flows. Technical choices recorded with the alternatives considered. -->

## 1. Tech decisions
| Decision | Chosen | Alternatives considered | Why |
|---|---|---|---|
| Framework | None: one self-contained HTML + vanilla JS | React + Vite, Vue 3 | No build step; the reviewer reads one file; deploys anywhere; the published demo needs no backend. Revisit if the console grows past ~8 tabs. |
| Charts | Chart.js 4.4.1 UMD from cdnjs | D3, uPlot, ECharts | Smallest learning surface; in-place updates at 0.5 Hz are enough. |
| Styling | Hand-written CSS with design tokens | Tailwind | Tokens must switch with system theme; a token table is simpler than a utility framework for one file. |
| State | In-memory JS objects; `localStorage` only for the remembered tab | Redux, React Query | No persisted client state; the backend and ticketing system are the records. |
| Live data | WebSocket `/ws/telemetry`, simulator fallback | Polling REST | Push keeps 2 s refresh cheap; fallback keeps the UI testable when the feed is down. |

## 2. Design tokens
| Token | Light | Dark |
|---|---|---|
| Background | #EEF2F7 | #0C1322 |
| Surface | #FFFFFF | #141E33 |
| Text | #13203A | #E4EBF6 |
| Accent (interactive only) | #1F6FEB | #4FB3FF |
| OK / Warning / Critical | #1B9E6A / #D98B00 / #D63C3C | #3DD598 / #F5B942 / #FF6B6B |
| Heat scale (5 steps) | #DCEBFF → #7FC4FF → #FFD36B → #FF7A59 → #D63C3C | darker equivalents |
Font: IBM Plex Sans (Google Fonts), system fallback. Severity colours are never used for interactive elements.

## 3. Screens
### 3.1 Header (all tabs)
Hall name and capacity line; "Inject fault" selector (CRAC failure Zone C, runaway process B-04, PSU loss D-02); live clock with pulse dot.

### 3.2 Overview
- KPI row: IT load (kW, % of design), PUE, average inlet, servers online, open incidents.
- Rack floor: 4 zones × 6 racks as a grid; each tile coloured by inlet temperature on the 5-step scale; offline racks greyed with strikethrough; tap selects a rack.
- Selected rack panel: inlet and CPU time series (20 samples), server count, power, CPU.
- AI insights panel: one row per open incident (title + probable cause), warmest rack when nothing is open, capacity warning when < 60 days to the planning line.
- Site chart: IT load and PUE over the last 60 samples.

### 3.3 Incidents
Open incidents (critical first, left stripe by severity) then Resolved (faded). Each card: id, title, severity pill, opened/closed time, evidence line, probable cause box with confidence bar, "Approve runbook: <name>" button, "Acknowledge" button, step list once running (✓ done, ▶ current, ○ pending), collapsible timeline.

### 3.4 Capacity
KPIs: power used %, rack space used %, days to 80 % power, growth per day. Chart: observed kW, dashed forecast 30 days, red 80 % line. Rack inventory table with status pill.

### 3.5 Runbooks
Catalogue: name, status (idle / proposed for INC-nnn), ordered steps.

### 3.6 Ops copilot
Question input, five suggestion chips, answer box.

### 3.7 Spec
Read-only summary of goal, plan, acceptance criteria.

## 4. Flows
```
Overview ──(badge)──► Incidents ──(Approve)──► steps run ──(5 normal samples)──► Resolved
   │                                                           ▲
   └──(Inject fault)──► detection → incident opens ────────────┘
```

## 5. Observable interface behaviour
| Situation | Expected behaviour |
|---|---|
| Page loads | 12 warm-up samples already in history; heatmap, charts and KPIs populated; no empty chart. |
| A fault is injected | Toast "Fault injected: …"; affected tiles change colour within 2 samples. |
| An incident opens | Toast with id; Incidents badge increments; insight row appears; critical sorts first. |
| Operator taps Approve | Button text becomes "Running…" and disables; steps advance every 1.4 s; timeline logs approval. |
| Runbook completes | Button reads "Runbook complete"; fault clears; incident resolves after 5 normal samples; toast "resolved". |
| Feed drops | Toast "Feed lost — using simulator"; UI keeps updating; reconnect attempted every 5 s; toast "Live telemetry connected" on success. |
| No incidents open | Incidents tab shows "No open incidents. Everything is within baseline." |
| Rack offline | Tile greyed, label "off", strikethrough; KPI "servers online" shows the gap. |
| Viewport 360 px | Floor grid collapses to 2 zones per row; no horizontal page scroll. |
| System theme changes | All tokens switch; charts recolour on next update. |

## 6. Accessibility
Rack tiles are buttons with aria-labels; tabs use role=tab/aria-selected; visible focus ring; pulse animation disabled under prefers-reduced-motion.

## 7. Open questions (resolved in review, Lecture 6)
- Should warnings create tickets or only critical? → All severities (default); configurable later.
- Keep "Spec" tab in production? → Yes, read-only, it is the audit entry point.
