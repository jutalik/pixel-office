"""CLIExecutor — activate a real CLI agent to do an employee's work.

The production Executor for OrgRuntime: it wakes a dormant employee, builds a
COMPACT prompt (persona digest + the one task + top-K relevant lessons — never
the whole company state), routes to a model tier, and invokes the CLI. This is
the only token-spending path, so the prompt is deliberately small and the
employee is dormant until assigned.

The actual invocation is a pluggable `invoke_fn(cli, prompt) -> str` (a real
subprocess to the CLI in production; a mock in tests, so the wiring is verified
at ZERO tokens). Fail-open: any error returns a Blocked result, never raises.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from .employee import Employee
from .learning import EmployeeMemory
from .runtime import Task, TaskResult

# invoke_fn(cli_name, prompt) -> the agent's text output
InvokeFn = Callable[[str, str], str]

# model tier → which installed CLI to use (cheap→fast/local, deep→strongest)
DEFAULT_TIER_CLI = {"cheap": "grok", "standard": "codex", "deep": "claude"}
MAX_LESSONS = 3
MAX_OUTPUT_CHARS = 400
MAX_PERSONA = 300
MAX_TASK = 200
MAX_LESSON = 120


def _clip(s, n: int) -> str:
    """One line, bounded — keeps the prompt small and predictable."""
    return " ".join(str(s or "").split())[:n]


# Refusal / failure signatures. A CLI agent that says "I can't", "permission
# denied", or "실패했습니다" produced text, but NOT a completed task — counting
# that as success would silently advance a workflow on a non-result (honesty
# gap). Matched at the START of the reply (or as an unambiguous embedded phrase)
# so a genuine success that merely mentions "error handling" isn't misread.
_BLOCKED_PREFIXES = (
    "blocked", "failed", "error", "cannot", "can't", "unable", "i cannot",
    "i can't", "i'm unable", "denied", "permission", "sorry", "no invoke",
    "not able", "couldn't", "could not", "못", "실패", "불가", "거부", "죄송",
)
_BLOCKED_PHRASES = (
    "permission denied", "access denied", "sandbox", "권한이 없", "실패했",
    "하지 못", "할 수 없", "불가능",
)


def _is_done_verdict(low: str) -> bool:
    # the WORD "done" (or Korean 완료), not a prefix of another word ("donefoo")
    return (low[:4] == "done" and (len(low) <= 4 or not low[4].isalnum())) or low.startswith("완료")


def _looks_blocked(text: str) -> bool:
    low = text.lstrip().lower()
    if _is_done_verdict(low):
        return False   # explicit success verdict wins
    if low.startswith(_BLOCKED_PREFIXES):
        return True
    head = low[:160]
    return any(p in head for p in _BLOCKED_PHRASES)


class CLIExecutor:
    def __init__(self, *, invoke_fn: Optional[InvokeFn] = None,
                 memories: Optional[Dict[str, EmployeeMemory]] = None,
                 tier_cli: Optional[Dict[str, str]] = None,
                 objective: str = ""):
        self.invoke_fn = invoke_fn
        self.memories = memories if memories is not None else {}
        self.tier_cli = tier_cli or dict(DEFAULT_TIER_CLI)
        self.objective = objective   # company mission — grounds every activation

    def pick_cli(self, employee: Employee) -> str:
        return self.tier_cli.get(employee.tier, self.tier_cli.get("cheap", "grok"))

    def build_prompt(self, employee: Employee, task: Task) -> str:
        """A COMPACT, token-efficient prompt that makes the agent act as THIS employee:
        persona + skills + their evidence-based focus + top-K lessons + (for creative
        roles) divergent lenses — never the whole company state. Individuality comes
        from the work (the focus is observed, not declared), staying honest."""
        from . import creativity as _creativity, roles as _roles
        lines = [f"You are the {_clip(employee.title, 80)}."]
        if self.objective:                          # mission grounding — every activation
            lines.append("Company mission: " + _clip(self.objective, 140))
        if employee.persona:
            lines.append(_clip(employee.persona, MAX_PERSONA))
        if employee.skills:
            lines.append("Skills: " + _clip(", ".join(employee.skills[:5]), 120))
        mem = self.memories.get(employee.id)
        if mem is not None:
            focus = mem.top_trait("focus")          # evidence-based, None until it emerges
            if focus:
                lines.append(f"You've built a focus on {_clip(focus, 40)} — lean on it.")
            for ls in mem.recall(task.task_class, k=MAX_LESSONS):
                lines.append("- lesson: " + _clip(ls.text, MAX_LESSON))
        if _roles.is_creative(employee):            # creative roles think in divergent lenses
            lenses = _creativity.lenses_for(_roles.family_of(employee.role))
            if lenses:
                lines.append("Explore one option per lens (" + _clip(", ".join(lenses), 100)
                             + "); mark unproven claims as assumptions.")
        lines.append("Task: " + _clip(task.title, MAX_TASK))
        lines.append("Do it. Reply `DONE: <result>` if completed, else `BLOCKED: <reason>`.")
        return "\n".join(lines)

    def __call__(self, employee: Employee, task: Task) -> TaskResult:
        if self.invoke_fn is None:
            # honest: real CLI execution isn't wired → Blocked, not a fake success
            return TaskResult(task.id, employee.id, ok=False,
                              summary="no invoke_fn — real CLI execution not configured")
        try:
            prompt = self.build_prompt(employee, task)
            out = self.invoke_fn(self.pick_cli(employee), prompt)
            text = (str(out) if out is not None else "").strip()
        except Exception as e:
            # only the exception TYPE — raw text can embed the prompt/args/secrets
            return TaskResult(task.id, employee.id, ok=False, summary=f"error: {type(e).__name__}")
        if not text:
            return TaskResult(task.id, employee.id, ok=False, summary="empty response")
        if _looks_blocked(text):
            # produced text, but it's a refusal/failure — NOT a completed task.
            # Honest: this must not advance a workflow or credit competency.
            return TaskResult(task.id, employee.id, ok=False, summary="blocked: " + text[:MAX_OUTPUT_CHARS])
        # strip a leading DONE verdict so the summary is just the result
        summary = text[4:].lstrip(": ").strip() if _is_done_verdict(text.lstrip().lower()) else text
        return TaskResult(task.id, employee.id, ok=True, summary=(summary or text)[:MAX_OUTPUT_CHARS])
