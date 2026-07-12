# The company operating layer (design)

The layer that runs an autonomous AI company on top of the pixel-office foundation
(telemetry/avatars + control plane + scaffold). Designed with a Codex + Grok
deliberation (both converged) and modeled on how today's fastest-growing companies
actually operate. **Status: BUILT (2026-07-10) — all 6 phases + full loop, deterministic + e2e-tested, ~60 tests. The real CLI executor is wired (opt-in; spends tokens). The autonomy loop (§3) drives the company on a background tick under `po run --demo/--live`.**

## 0. The one decision that changes everything

> **Employees are N durable *identities* on ONE event-driven org runtime — not N
> always-on agents.** Cost scales with the number of independently-*reasoned
> decisions*, never with headcount.

Both reviewers landed here independently. A distinct identity (private memory,
persona, permissions, competency record, ownership, audit trail) is cheap to
store. A distinct *opinion* costs at least one inference. One model call
role-playing five employees is simulation, not independence. So:

- **Always separate** (free/cheap): memory namespace, persona, permissions,
  competency, task ownership, audit identity, budget.
- **Usually shared**: the model endpoint, base runtime, retrieval, scheduler,
  tool adapters.
- **Buy a separate inference call ONLY when** a second role given the *same
  evidence* would reasonably choose a *different action* — i.e. genuine cognitive
  diversity: adversarial review, architecture/strategy disputes, security, or a
  consequential/irreversible decision. Otherwise: **one call + deterministic role
  constraints.**
- Budget the real multiplier: a company-wide **reasoning-call budget** (calls,
  fan-out, synthesis frequency), not just a token budget. Every extra employee
  call must state the unique information/conflict/risk it adds.

Default workflow: **one owner proposes → deterministic checks → at most one
relevant reviewer.** Never "everyone thinks."

## 0.5 The purpose: hyper-growth toward the CEO's goal

The company does not run a culture for its own sake — it runs **whatever operating
style most accelerates *this project* toward its goal.** Two consequences:

- **Mission-grounded employees.** Every employee is grounded in the project's
  meaning/purpose (the charter + Objective from `po new`). That shared context —
  *why we exist, who we serve, what winning looks like* — is the small, cached
  preamble on every activation, so employees make bold, aligned decisions without
  asking (Netflix "context, not control"). Purpose is the cheapest coordination.
- **Goal-optimized, self-adapting process (the growth engine).** The company
  measures its own **growth rate toward the Objective** (KR velocity, not activity)
  and periodically adapts *how it works* to grow faster: which practices, cadence,
  team shape, and where to place bold bets. It treats its own operating model as a
  variable to optimize — exactly what a hyper-growth startup's growth team does.
  The default practices in §1 are the *starting kit*; the growth engine keeps the
  ones that move the KR and drops the ones that don't (measured, not dogmatic).

So: pick the fastest path to the goal, ground everyone in why, act boldly on
reversible bets, and continuously tune the process against real growth.

## 0.6 Operating mode — the top-level dial (configurable, changeable anytime)

None of this is hardcoded. The company's **leadership + autonomy + culture** is a
single top-level setting the CEO picks (and can change or override any field).
One dial governs how wide default approval envelopes are, how much reaches the
CEO queue, and how the org plans — so a busy CEO picks `Autopilot` and steps back, or
`Manual` when they want the wheel.

The names use a **driving metaphor** — the CEO is the driver of the company, and
the mode is how much of the driving the AI team does:

```
operating_mode:
  drive:        Manual | Copilot | Autopilot   # ← the main dial (who drives)
  ceo_updates:  Everything | Key decisions | Weekly digest   # how much reaches the CEO
  culture:      Balanced | Hyper-growth | Steady | Research   # preset (§1), overridable
  self_tuning:  Off | Guardrailed | On          # may the growth engine tune the process?
```

The three **drive** presets (each just sets defaults for the fields above — every
field stays overridable):

| Mode | In one line | Who plans the weekly/monthly KRs | What reaches the CEO |
|---|---|---|---|
| **🚗 Manual** *(CEO-led)* | You drive; the team executes and checks with you. | CEO approves every replan | most planning + most actions |
| **🚙 Copilot** *(shared)* | You set the direction; the team runs the day-to-day and asks you for the big turns. | Team proposes, CEO approves | KR replans + medium-risk actions |
| **🚀 Autopilot** *(self-running)* | The team runs the whole company toward your goal; you set the destination and only sign off on one-way doors. | Growth engine replans on its own | one-way doors + a weekly digest |

- The mode only sets **how much reaches the CEO** (§6) and who plans (§3). It does
  **not** cap or throttle employees: they work unconstrained and bold. The ONLY
  hard gate is an irreversible **one-way door** (§4) — everything reversible just
  happens. (Budgets exist for cost accounting, not as autonomy levels.)
- Per-role and per-action overrides still apply (e.g. even in `Autopilot`, terminating
  an employee or a prod deploy is always a one-way door → CEO).
- If `self_tuning` ≠ Off, the growth engine (§3) may tune culture/cadence *within
  the mode's bounds* to raise growth rate — the CEO can pin any field to stop it.

Everything below describes the *behaviors*; the mode just picks how autonomous
and hands-off they run.

## 1. The operating culture — the starting kit (modern AND cheap)

The efficient practices of the biggest fast-growing companies happen to be the
*most token-efficient* structure, so we adopt them wholesale:

| Practice (origin) | What we do | Why it's cheap |
|---|---|---|
| **Working-backwards + 6-pagers, writing over slides** (Amazon) | Decisions are short written **memos**, not conversations | Writing = 1 call; a meeting = N calls × rounds |
| **Async-first, document everything** (GitLab/Stripe) | Default to async written decisions with a DRI | No synchronous multi-round token burn |
| **Two-way vs one-way doors** (Amazon Type-2/Type-1) | Reversible decisions = full autonomy, made instantly; irreversible = escalate | Gates only the rare irreversible action |
| **DRI / single-threaded owner** (Apple/Amazon) | Every task & decision has exactly one owner | No diffusion, no "everyone weighs in" |
| **Context, not control** (Netflix) | Give employees the goal + context + a wide envelope; trust their judgment | Fewer clarification round-trips; bold by default |
| **OKRs** (Intel/Google) | final goal = Objective; monthly/weekly = Key Results | Measurable, auto-updatable, no re-litigation |
| **Bias for action, disagree-and-commit** (Amazon) | Act on reversible calls; one bounded challenge round then commit | Kills endless debate |
| **Keeper test** (Netflix) | HR evidence-based, staged, reversible | No churn theater |

**Meetings are the exception, not the rhythm.** A "meeting" here = *parallel
position memos generated from one shared evidence packet → one synthesis call*,
only when the admission test passes (below). Never conversational role-play.

## 2. Employee model

```
employee/
  identity.json     title · role · persona digest · model tier · account/config-dir (if isolated)
  capability.json   sealed tools/mcp/net + approval class (what it may do un-gated)
  memory/           private, evidence-first (see §5)
  competency.json   evidence-based scores per task-class (+ sample size / "insufficient evidence")
  budget            per-employee reasoning-call + spend cap (BudgetGuard)
```

Dormant by default (0 tokens). Woken only by an assigned task or a memo it must
answer. A full isolated account/config-dir is provisioned **only** for roles that
own irreversible state or need a real security/tool boundary (PO, infra, finance);
everyone else is a role-scoped execution on the shared runtime.

## 3. Goals — OKRs

- **Objective** = the CEO's final goal (immutable without the CEO).
- **Key Results** = monthly then weekly, measurable. **Seeded by the user at init**
  (`po new --kr "publish 10 recipes weekly, reach 1,000 signups monthly"`, or the
  init Q&A) so the loop has real goals to advance from day one, then **auto-updated
  by the weekly review memo** from real product metrics (the KPI surface `po new`
  scaffolds: `/api/telemetry|funnel|quality|growth`). Never fabricated — a project
  with no KRs honestly sits at 0% until real progress lands. (`--demo` simulates
  metrics so the goal bar visibly climbs; `--live` only ever uses real metrics.)
- Closed loop: monitor metrics → weekly review replans KRs toward the Objective →
  tasks. A KR that stalls triggers a *decision memo*, not a standing meeting.
  This loop is `company/autonomy.py` — a **bounded, clock-driven tick** (plan
  toward stalled KRs → dispatch ≤N backlog tasks → cadence-gated review/radar/HR,
  each independently fail-open). `po run --demo/--live` runs it on a background
  daemon thread; cost scales with *decisions*, not wall-clock (dormant when idle).
- **Growth engine (meta-loop):** the weekly review also scores *KR velocity* and
  adapts the operating model itself — cadence, which practices earn their keep,
  where to make a bold bet, which role to add/drop — always to raise growth rate
  toward the Objective. Process is a tunable, measured against real progress.

## 4. Autonomy & gates — approval envelopes

"Unconstrained/bold" = unconstrained **ideation + reversible experimentation**,
never unconstrained side-effects.

- **Never gate**: research, local drafts/sims, disposable-env tests, reversible
  code in an approved scope, task decomposition, spend already inside an envelope.
- **Always gate (→ CEO)**: prod deploy/data mutation, external comms as the
  company, new recurring spend / cap increase / purchases, credential/access
  grants, destructive/irreversible ops, legal/privacy/personnel commitments,
  **final-goal change**, **employee termination**.
- **Approval envelope**: the CEO approves *purpose + max cost + environment +
  expiry + action class* **once**; agents then operate freely inside it (this is
  what keeps autonomy high while the CEO stays hands-off). Standing policies too:
  "auto-approve staging deploys under $X." **The operating mode (§0.6) sets the
  default envelope width** — `Autopilot` = wide (few, broad envelopes), `Manual` =
  narrow (more, tighter approvals).
- **Circuit breakers** (fail-closed): anomalous fan-out, repeated failures,
  unexpected external targets, rapid budget burn → pause + escalate. Guards
  against *permission laundering* (many allowed steps → one unapproved outcome).

## 5. Self-learning (evidence-first, mostly deterministic)

- **Evidence before lessons**: store the immutable event (task/commit/test/metric/
  approval/failure/rollback/reviewer verdict) first; a *lesson* is derived with
  confidence + scope + expiry, always carrying its evidence id.
- **Mostly deterministic extraction** from outcomes; spend an LLM reflection call
  only on novelty/failure/correction/surprising-success/repeated-pattern — never
  after every trivial task.
- **Memory tiers**: hot (current + validated) · warm (role playbooks) · cold (raw
  evidence, out of context) · quarantined (contradictions/hypotheses). Distill by
  *merging overlapping lessons that share evidence* — never summarize away dissent
  or provenance. **Evict from retrieval, not storage.**
- **Competency** = task-class outcomes (quality/verification/rollback/cost-latency/
  calibration), normalized for difficulty + sample size; shows "insufficient
  evidence" rather than an invented score.

## 6. CEO ← PO flow (minimal, because the CEO is one busy person)

How much the CEO is touched is set by the operating mode (§0.6): `Autopilot` = only
one-way doors + a weekly digest; `Manual` = most planning + actions. Domain
owners prepare machine-validated briefs; the **PO is the presentation boundary**
(dedupe, prioritize, fill gaps, explain), **not** a processing bottleneck (an
emergency delegate exists; one canonical queue + audit identity).

Each pending item is a **decision card**:
- one-line decision + **recommended choice**; deadline + *what happens if you
  don't respond*; risk class · reversibility · blast radius · max cost.
- **5W1H collapsed by default**, expandable (who/what/when/where/why-tied-to-the-
  goal/how+cost+risk) — the PO explains verbally only high-impact/ambiguous/
  irreversible items.
- the exact **envelope** that will be minted; buttons: approve / approve-modified
  / reject / defer. Shows the **delta from the last approved state**.
- sorted by deadline × impact × irreversibility; related actions batched into one
  bounded envelope; 48h auto-expiry (auto-reject or auto-defer per policy).

On confirm → single-use approval token (existing control plane) → proceed. A
reject stores a reason code (no extra LLM call to "invent a lesson").

## 7. HR — staged, reversible, evidence-based

- Hiring = **activating role capacity**, not spawning an always-on agent. Path:
  temp role → probation workload → evidence review → durable employee. Hire only
  when a recurring work-class has measurable backlog/quality failure that existing
  roles + tooling can't absorb, and expected value > model+coordination cost.
  (First try: better tooling, expand an existing role, a time-boxed specialist.)
- Firing is **staged**: freeze assignments → revoke risky capabilities → archive
  private memory → reassign owned work → **permanent deletion only with CEO
  confirm**. Reversible steps (dormancy, capability/tier downgrade, reassignment,
  archival) need no gate.
- HR is **one policy engine + an episodic reviewer role**, not a standing team.

## 8. Trend radar (bold, current, budgeted)

A recurring, **budgeted** research function scans the latest trends
(web search, competitor/market/tech) on a cadence, distills to a short memo, and
feeds the weekly review + backlog. Cheap-model + deterministic-dedup first; one
synthesis call. Cadence + token cap are policy; it never runs unbounded.

## 9. How this maps onto what's already built

- **Avatars/telemetry**: each employee activation is already an agent session →
  shows as an avatar (rooms by team). Dormant employees = idle/offline avatars.
- **Control plane**: approval gate + BudgetGuard already exist → become envelopes
  + the reasoning-call budget + circuit breakers.
- **Scaffold KPI surface**: already emits the metrics the OKR loop reads.
- **Adapters/registry modularity**: employees/roles/memos/OKRs/HR each become a
  small module with one descriptor, same philosophy as `adapters/`.

## 10. Phased build (cheapest value first)

0. **Operating mode + charter** — the top-level `operating_mode` config (§0.6)
   with presets (Manual / Copilot / Autopilot), wired into `po new` so a company is
   born with a chosen autonomy level; changeable anytime. Cheap, and it governs
   every later phase.
1. **Org runtime + OKR tree + decision memos** — the shared event-driven runtime,
   employee identities (memory/persona/competency), the OKR store, and async
   decision memos with a DRI. (No fan-out yet.)
2. **Approval envelopes + PO decision cards** — extend the control plane to
   envelopes + the CEO queue/cards + circuit breakers.
3. **Self-learning** — evidence store, deterministic extraction, tiered memory,
   competency.
4. **Meetings-as-memos** — the admission test + parallel-position + one synthesis,
   with a reasoning-call budget.
5. **HR lifecycle** — staged hire/fire, gap analysis.
6. **Trend radar** — budgeted recurring research.

Every phase: build → test → live-verify → Codex cross-review, one adapter/module
at a time, token-efficiency measured (reasoning-calls per decision) as the gate.

## 11. Roles, Skills & Workflows (built-in library)

A scaffolded company arrives knowing the jobs software companies actually hire for,
what each one is good at, and how to ship work — not just a list of title strings.

- **Roles** (`company/roles.py`): a catalog of canonical roles — `project-owner`,
  `architect` (a high-performance architecture engineer, `deep` tier), `backend`,
  `frontend`, `qa`, `devops`, `pm`, `designer`, `writer`, `growth`, `data`. Each
  carries a persona, a default model tier, its skills, and the workflows it can
  drive. `DEFAULT_TEAMS[stack]` seeds a real team when the user names no roles
  (`api-service` → PO + architect + backend + qa + devops, etc.) — seeded in the
  scaffold layer so `build_company` behavior is unchanged for existing inputs.
  `match_title` resolves a user's free-text title to a role (title/id words outweigh
  shared skill keywords); an unclear title stays a plain employee — never a
  confident-wrong mapping.
- **Skills** (`company/skills.py`): named competencies with routing keywords and a
  tier. A person's **proficiency** at a skill is NEVER declared — it is derived from
  evidence (`learning.EmployeeMemory.competency`) and reports "insufficient
  evidence" (None) below the sample floor. Workflow steps accrue evidence under a
  compound `task_class = "{kr}:{skill}"`, so per-skill competency emerges without
  ever colliding with the default planner's bare `kr.id`.
- **Workflows** (`company/workflows.py`): ordered playbooks (ship-feature,
  content-pipeline, architecture-review, growth-experiment, incident-response). The
  `workflow_planner` — chosen **automatically** when the team carries workflows (a
  library-role company does), not a user opt-in — drives a KR through its steps
  **one per tick**, routing each step to the best-skilled employee
  (`routing.best_owner_for_step`) and advancing only on a real, *matching*
  `TaskResult.ok` (`company.advance_workflow`) — a failed step **halts** the run
  (retry via `company.clear_workflow`) rather than skipping ahead. No fabricated
  progress. The `default_planner` function is unchanged; a team with no workflows
  uses it. Note this does change `po run` behavior for existing manifests whose
  titles resolve to library roles (task shape `kr:skill`, sharper routing) — a
  deliberate feature, kept green against all existing tests.

  Routing also unions each role's skill keywords into `_emp_keywords`, so owner
  selection sharpens for library roles; title-only (hand-built) employees are
  unaffected.

Surfaced honestly in `/api/company` (`roster[].role/skills/workflows/tier`,
`workflows[]` with the live step) and painted in the office CEO panel + avatar role
badges (KO/EN).
