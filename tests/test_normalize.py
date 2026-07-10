from pixel_office.telemetry.contract import ACTIVITY_STATES
from pixel_office.telemetry.normalize import TAILER_DERIVABLE, _TABLES, normalize


def test_claude_working():
    for k in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
              "PostToolUseFailure", "SubagentStart", "PermissionDenied", "PreCompact",
              "AssistantMessage"):
        assert normalize("claude", k) == "working"


def test_claude_waiting():
    for k in ("PermissionRequest", "AskUserQuestion", "Notification",
              "Notification:permission_prompt", "Notification:agent_needs_input",
              "Notification:elicitation_dialog"):
        assert normalize("claude", k) == "waiting"


def test_claude_done():
    for k in ("Stop", "SubagentStop", "SessionEnd",
              "Notification:idle_prompt", "Notification:agent_completed"):
        assert normalize("claude", k) == "done"


def test_claude_blocked_reachable():
    assert normalize("claude", "StopFailure") == "blocked"


def test_every_mapped_state_is_in_the_contract_enum():
    for table in _TABLES.values():
        assert set(table.values()) <= set(ACTIVITY_STATES)


def test_tailer_derivable_subset_of_table_states():
    for cli, states in TAILER_DERIVABLE.items():
        assert set(states) <= set(_TABLES[cli].values())


def test_unknown_kind_is_none():
    assert normalize("claude", "Nonsense") is None


def test_unknown_cli_is_none():
    assert normalize("nope", "Stop") is None
