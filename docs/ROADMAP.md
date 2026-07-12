
---

## Company operating layer (built 2026-07-10) — see docs/COMPANY-LAYER.md

The autonomous-AI-company layer on top of the foundation, all deterministic +
e2e-tested + Codex-reviewed (employee reasoning is a pluggable executor; the
deterministic stub is zero-token, the real CLI executor is opt-in):

- ✅ **operating_mode** (`company/mode.py`) — Manual / Copilot / Autopilot dial,
  wired into `po new`; governs only how much reaches the CEO (no employee limits).
- ✅ **OKRs + decision memos + employees + org runtime** (`company/{okr,memo,
  employee,runtime}.py`) — employees are durable identities on one runtime and
  appear as AVATARS via the same telemetry pipeline (`adapters/company.py`).
- ✅ **approval envelopes + PO 5W1H cards + `/api/company`** (`control/envelope.py`,
  `company/{po,company}.py`) — the CEO panel lights up with real approvals + OKRs.
- ✅ **self-learning** (`company/learning.py`) — evidence-first competency.
- ✅ **meetings** (`company/meeting.py`) — parallel memos → one synthesis (not a chat).
- ✅ **HR** (`company/hr.py`) — staged, reversible, evidence-based hire/fire.
- ✅ **trend radar** (`company/radar.py`) — budgeted recurring research.
- ✅ **full loop** — `po new` → `po run` boots a live AI company on the dashboard.
- ✅ **CLIExecutor** (`company/executor_cli.py`) — real employee work with a
  compact token-efficient prompt; opt-in (a real run spends tokens).

Since shipped (the Company Layer + game): the real subprocess invoke_fn (`cli_invoke`),
live meeting-gather animation, HR/radar/idea/trend UI surfacing, the honest
idea→outcome→reputation loop with baseline adjustment, trend-grounded creativity, and
the `--live` control gate (bounded activations + approval-required risky steps). See
`docs/COMPANY-LAYER.md`.
