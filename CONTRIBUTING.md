# Contributing to Pixel Office

Thanks for your interest! Pixel Office is a small, honest, local-first project. A few
things make contributions land smoothly.

## Setup

```bash
git clone https://github.com/jutalik/pixel-office.git
cd pixel-office
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,web]"
pytest -q          # the full suite should be green
po doctor          # sanity-check your machine
```

Requires Python 3.10+. The runtime has **zero dependencies**; `[web]` adds the
dashboard (fastapi/uvicorn) and `[dev]` adds the test tools.

## The one rule that matters: honesty

Pixel Office's whole premise is that nothing on screen is faked. Any change must keep
these invariants — a PR that breaks one won't be merged:

- **Avatars/labels reflect only real telemetry.** No cosmetic "activity".
- **Work counts only when it really succeeded** (`TaskResult.ok`). A CLI that refuses
  or errors must not advance a workflow or earn competency.
- **No invented numbers or personality.** Competency, traits, and idea outcomes are
  evidence-based; below the sample floor they read `None`/"learning", never a made-up
  value. Correlation is labelled as such, never as causation.
- **`--demo` is simulated and labelled `simulated` everywhere;** it must never be
  confused with real work.

If you're unsure whether a change is "honest enough," open an issue and ask.

## Pull requests

- Keep the diff focused; match the surrounding code's style and comment density.
- Add or update tests — the suite is the contract. `pytest -q` must stay green.
- Update the relevant docs in the same PR (`docs/COMPANY-LAYER.md`, `README.md`).
- Describe *what* changed and *why*; note any invariant you had to reason about.

## Reporting bugs / ideas

Open an issue with steps to reproduce (for bugs) or the problem you're trying to solve
(for features). This is a spare-time project — responses may take a while, and not
every idea will fit the honest/local-first scope. That's OK; discussion is welcome.
