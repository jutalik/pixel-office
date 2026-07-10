"""Real subprocess invoker — wiring verified with a fake runner (ZERO tokens)."""
import types

from pixel_office.company import cli_invoke


class _FakeProc:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode = stdout, returncode


def _fake_runner(record, stdout="result", rc=0):
    def run(argv, input=None, capture_output=True, text=True, timeout=None):
        record.append({"argv": argv, "stdin": input})
        return _FakeProc(stdout, rc)
    return run


def test_builds_correct_command_per_cli(monkeypatch):
    monkeypatch.setattr(cli_invoke, "_binary", lambda cli: f"/bin/{cli}")
    rec = []
    invoke = cli_invoke.make_subprocess_invoke(runner=_fake_runner(rec))
    assert invoke("claude", "hi") == "result"
    assert rec[-1]["argv"][:2] == ["/bin/claude", "--print"] and rec[-1]["stdin"] == "hi"
    invoke("codex", "yo")
    assert "exec" in rec[-1]["argv"] and rec[-1]["stdin"] == "yo"          # codex: stdin
    invoke("grok", "sup")
    assert "-p" in rec[-1]["argv"] and "sup" in rec[-1]["argv"] and rec[-1]["stdin"] is None  # grok: arg


def test_missing_binary_fails_open(monkeypatch):
    monkeypatch.setattr(cli_invoke, "_binary", lambda cli: None)
    invoke = cli_invoke.make_subprocess_invoke(runner=_fake_runner([]))
    assert invoke("claude", "hi") == ""    # not installed → "" → Blocked


def test_nonzero_exit_and_exceptions_fail_open(monkeypatch):
    monkeypatch.setattr(cli_invoke, "_binary", lambda cli: "/bin/x")
    rec = []
    fail = cli_invoke.make_subprocess_invoke(runner=_fake_runner(rec, stdout="oops", rc=1))
    assert fail("claude", "hi") == ""      # non-zero exit → ""

    def boom(*a, **k):
        raise TimeoutError()
    assert cli_invoke.make_subprocess_invoke(runner=boom)("claude", "hi") == ""


def test_plugs_into_cli_executor(monkeypatch):
    from pixel_office.company.employee import Employee
    from pixel_office.company.executor_cli import CLIExecutor
    from pixel_office.company.runtime import Task
    monkeypatch.setattr(cli_invoke, "_binary", lambda cli: f"/bin/{cli}")
    ex = CLIExecutor(invoke_fn=cli_invoke.make_subprocess_invoke(runner=_fake_runner([], "shipped")))
    r = ex(Employee("e", "engineer", tier="deep"), Task("build", dri="e"))
    assert r.ok and r.summary == "shipped"
