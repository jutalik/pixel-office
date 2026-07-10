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


class CLIExecutor:
    def __init__(self, *, invoke_fn: Optional[InvokeFn] = None,
                 memories: Optional[Dict[str, EmployeeMemory]] = None,
                 tier_cli: Optional[Dict[str, str]] = None):
        self.invoke_fn = invoke_fn
        self.memories = memories if memories is not None else {}
        self.tier_cli = tier_cli or dict(DEFAULT_TIER_CLI)

    def pick_cli(self, employee: Employee) -> str:
        return self.tier_cli.get(employee.tier, self.tier_cli.get("cheap", "grok"))

    def build_prompt(self, employee: Employee, task: Task) -> str:
        """A COMPACT, token-efficient prompt: persona + this task + top-K lessons.
        Never the whole company state (cost = decisions, not context size)."""
        lines = [f"You are the {_clip(employee.title, 80)}."]
        if employee.persona:
            lines.append(_clip(employee.persona, MAX_PERSONA))
        mem = self.memories.get(employee.id)
        if mem is not None:
            for ls in mem.recall(task.task_class, k=MAX_LESSONS):
                lines.append("- lesson: " + _clip(ls.text, MAX_LESSON))
        lines.append("Task: " + _clip(task.title, MAX_TASK))
        lines.append("Do it. Reply with a one-line result.")
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
        return TaskResult(task.id, employee.id, ok=True, summary=text[:MAX_OUTPUT_CHARS])
