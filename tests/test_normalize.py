from pixel_office.telemetry.normalize import normalize


def test_claude_working():
    for k in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"):
        assert normalize("claude", k) == "working"


def test_claude_waiting():
    assert normalize("claude", "PermissionRequest") == "waiting"
    assert normalize("claude", "AskUserQuestion") == "waiting"


def test_claude_done():
    assert normalize("claude", "Stop") == "done"
    assert normalize("claude", "SubagentStop") == "done"


def test_unknown_kind_is_none():
    assert normalize("claude", "Nonsense") is None


def test_unknown_cli_is_none():
    assert normalize("nope", "Stop") is None
