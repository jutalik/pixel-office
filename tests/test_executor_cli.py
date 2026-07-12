"""CLIExecutor — real employee work, verified at ZERO tokens via a mock invoke_fn."""
from pixel_office.company.employee import Employee, Team
from pixel_office.company.executor_cli import CLIExecutor
from pixel_office.company.learning import EmployeeMemory, Lesson
from pixel_office.company.runtime import OrgRuntime, Task


def test_tier_routes_to_cli():
    ex = CLIExecutor(invoke_fn=lambda c, p: "ok")
    assert ex.pick_cli(Employee("a", "eng", tier="deep")) == "claude"
    assert ex.pick_cli(Employee("b", "eng", tier="cheap")) == "grok"


def test_prompt_is_compact_persona_task_and_lessons():
    mems = {"e": EmployeeMemory("e")}
    mems["e"].add_lesson(Lesson("prefer small PRs", 1, "backend", confidence=0.9))
    ex = CLIExecutor(invoke_fn=lambda c, p: "done", memories=mems)
    prompt = ex.build_prompt(Employee("e", "backend engineer", persona="ship fast"),
                             Task("add endpoint", dri="e", task_class="backend"))
    assert "backend engineer" in prompt and "ship fast" in prompt
    assert "prefer small PRs" in prompt and "add endpoint" in prompt
    # compact: no whole-company dump — a handful of short lines
    assert len(prompt.splitlines()) <= 8


def test_no_invoke_fn_is_honest_blocked_not_fake_success():
    ex = CLIExecutor()                                   # not wired
    r = ex(Employee("e", "eng"), Task("x", dri="e"))
    assert r.ok is False and "not configured" in r.summary


def test_invoke_error_and_empty_fail_open():
    boom = CLIExecutor(invoke_fn=lambda c, p: 1 / 0)
    r = boom(Employee("e", "eng"), Task("x", dri="e"))
    assert r.ok is False and r.summary == "error: ZeroDivisionError"   # type only, no raw text
    empty = CLIExecutor(invoke_fn=lambda c, p: "   ")
    assert empty(Employee("e", "eng"), Task("x", dri="e")).ok is False


def test_prompt_is_bounded_even_with_huge_inputs():
    mems = {"e": EmployeeMemory("e")}
    mems["e"].add_lesson(Lesson("L" * 5000, 1, "backend", confidence=0.9))
    ex = CLIExecutor(invoke_fn=lambda c, p: "ok", memories=mems)
    emp = Employee("e", "engineer", persona="P" * 5000)
    prompt = ex.build_prompt(emp, Task("T" * 5000, dri="e", task_class="backend"))
    assert "\n\n" not in prompt                     # each field is a single clipped line
    assert len(prompt) < 1200                        # total stays small (token-efficient)
    for line in prompt.splitlines():
        assert len(line) <= 320


def test_error_summary_never_leaks_prompt():
    def boom(cli, prompt):
        raise RuntimeError("secret: " + prompt)      # exception embeds the prompt
    r = CLIExecutor(invoke_fn=boom)(Employee("e", "eng", persona="TOPSECRET"), Task("x", dri="e"))
    assert "TOPSECRET" not in r.summary and "secret" not in r.summary


def test_refusal_or_failure_text_is_not_counted_as_success():
    # honesty: a CLI that PRODUCES TEXT but refused/failed must NOT advance work.
    for reply in ["BLOCKED: no write permission", "I cannot modify that file",
                  "permission denied", "failed to run the tests", "실패했습니다",
                  "권한이 없어 수정할 수 없습니다", "Sorry, I'm unable to do this"]:
        r = CLIExecutor(invoke_fn=lambda c, p, _r=reply: _r)(Employee("e", "eng"), Task("x", dri="e"))
        assert r.ok is False, f"{reply!r} should be blocked, not success"


def test_refusal_markers_are_precise_not_overbroad():
    ex = lambda reply: CLIExecutor(invoke_fn=lambda c, p, _r=reply: _r)(Employee("e", "eng"), Task("x", dri="e"))
    # embedded Korean failure ("작업이 실패했습니다") is caught even when not at the start
    assert ex("작업이 실패했습니다").ok is False
    # but a genuine success that merely contains the words "read-only" is NOT blocked
    assert ex("implemented read-only mode and all tests pass").ok is True
    # "done" must be the WORD, not a prefix of another word — and generic prose with no
    # completion signal is NOT counted as done (honest: "reported", needs verification)
    assert ex("donefoo is now wired up").ok is False           # no completion signal → reported
    assert ex("DONE").ok is True                               # bare DONE verdict → success


def test_done_verdict_is_success_and_prefix_stripped():
    r = CLIExecutor(invoke_fn=lambda c, p: "DONE: shipped the endpoint")(Employee("e", "eng"), Task("x", dri="e"))
    assert r.ok is True and r.summary == "shipped the endpoint"   # verdict prefix removed


def test_plain_success_text_without_a_verdict_still_passes():
    # backward-compatible: a normal result line with no refusal markers is success
    r = CLIExecutor(invoke_fn=lambda c, p: "added the migration and tests pass")(Employee("e", "eng"), Task("x", dri="e"))
    assert r.ok is True


def test_completion_detection_handles_first_person_markdown_and_phrases():
    ok = lambda reply: CLIExecutor(invoke_fn=lambda c, p, _r=reply: _r)(Employee("e", "eng"), Task("x", dri="e")).ok
    assert ok("I added the endpoint and wired the tests") is True     # first-person completion
    assert ok("### DONE: shipped the feature") is True                # markdown-prefixed verdict
    assert ok("The fix is complete and deployed to staging") is True  # completion phrase
    assert ok("Here is a plan: first we should consider…") is False   # a PLAN → reported, not done
    assert ok("Could you clarify the requirements?") is False         # a question → reported


def test_done_verdict_that_describes_a_failure_is_not_credited():
    # honesty: "DONE:" must not override a result that itself reports failure
    r = CLIExecutor(invoke_fn=lambda c, p: "DONE: failed to deploy, permission denied")(Employee("e", "eng"), Task("x", dri="e"))
    assert r.ok is False and "blocked" in r.summary


def test_objective_grounds_the_prompt_when_set():
    ex = CLIExecutor(invoke_fn=lambda c, p: "ok", objective="reach 1000 paying users")
    p = ex.build_prompt(Employee("e", "engineer"), Task("ship", dri="e", task_class="backend"))
    assert "reach 1000 paying users" in p and "mission" in p.lower()


def test_e2e_runtime_with_cli_executor_mock():
    # the executor is a drop-in for OrgRuntime; a mock proves the full path with 0 tokens
    calls = []
    ex = CLIExecutor(invoke_fn=lambda cli, prompt: (calls.append(cli), "shipped it")[1])
    t = Team(); t.hire(Employee("eng", "backend engineer", tier="deep"))
    events = []
    rt = OrgRuntime(t, executor=ex, sink=events.append)
    ex.memories = rt.memories                            # share memory for context + learning
    r = rt.assign(Task("build API", dri="eng", task_class="backend"))
    assert r.ok and r.summary == "shipped it"
    assert calls == ["claude"]                           # deep tier → claude
    assert [e.kind for e in events] == ["Working", "Done"]
    assert rt.memory_of("eng").samples("backend") == 1   # outcome recorded
