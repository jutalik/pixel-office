from pixel_office.telemetry.claude_transcript import parse_line

TS = "2026-07-10T00:00:01.000Z"
S = "sess-1"


def _rec(rtype, content=None, stop_reason=None, **kw):
    d = {"type": rtype, "timestamp": TS, "sessionId": S, "isSidechain": False}
    if content is not None or rtype in ("user", "assistant"):
        d["message"] = {"role": rtype, "content": content}
        if stop_reason is not None:
            d["message"]["stop_reason"] = stop_reason
    d.update(kw)
    return d


def test_user_prompt_string_content():
    kind, ts, sess, meta = parse_line(_rec("user", "please fix the bug"))
    assert kind == "UserPromptSubmit" and sess == S and ts == TS and meta == {}


def test_user_tool_result_is_post_tool_use():
    kind, _, _, meta = parse_line(_rec("user", [{"type": "tool_result", "content": "..."}]))
    assert kind == "PostToolUse" and meta == {"result_count": 1}


def test_user_meta_record_ignored():
    assert parse_line(_rec("user", "harness-injected", isMeta=True)) is None


def test_assistant_end_turn_is_stop():
    kind, _, _, _ = parse_line(_rec("assistant", [{"type": "text", "text": "done!"}],
                                    stop_reason="end_turn"))
    assert kind == "Stop"


def test_assistant_tool_use_is_pre_tool_use_with_tool_name_only():
    content = [{"type": "tool_use", "name": "Bash", "input": {"command": "SECRET"}}]
    kind, _, _, meta = parse_line(_rec("assistant", content, stop_reason="tool_use"))
    assert kind == "PreToolUse"
    assert meta == {"tool": "Bash", "tool_count": 1}
    assert "SECRET" not in str(meta)  # inputs never leak into meta


def test_assistant_in_flight_message():
    kind, _, _, _ = parse_line(_rec("assistant", [{"type": "thinking"}], stop_reason=None))
    assert kind == "AssistantMessage"


def test_sidechain_skipped_in_phase_1a():
    assert parse_line(_rec("user", "sub work", isSidechain=True)) is None


def test_control_records_ignored():
    for rtype in ("mode", "permission-mode", "last-prompt", "ai-title",
                  "attachment", "file-history-snapshot", "queue-operation", "system"):
        assert parse_line({"type": rtype, "sessionId": S}) is None


def test_missing_ts_or_session_ignored():
    assert parse_line({"type": "user", "message": {"content": "x"}, "sessionId": S}) is None
    assert parse_line({"type": "user", "message": {"content": "x"}, "timestamp": TS}) is None


def test_garbage_input():
    assert parse_line(None) is None
    assert parse_line({}) is None
