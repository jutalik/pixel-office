from pixel_office import doctor


def test_run_shape():
    r = doctor.run()
    assert "os" in r and "clis" in r
    assert r["os"]["system"] in ("Linux", "Darwin", "Windows")
    assert "gemini" not in r["clis"]  # replaced by agy (Antigravity)
    for name in ("claude", "codex", "grok", "agy", "hermes"):
        assert name in r["clis"]
        c = r["clis"][name]
        assert {"available", "hooks_capable", "hook_kind", "normalize_supported",
                "session_kind", "home", "session_glob", "transcripts", "telemetry"}.issubset(c)


def test_agy_is_sqlite_and_provisional():
    c = doctor.run()["clis"]["agy"]
    assert c["session_kind"] == "sqlite"
    assert c["hooks_capable"] is True
    # provisional: no verified sqlite mapper yet, so not a tailer source and not
    # normalize-supported — doctor must not over-promise agy telemetry
    assert c["normalize_supported"] is False
    assert c["sqlite_mapper_verified"] is False
    if c["available"]:
        assert "tailer" not in c["telemetry"]  # unverified sqlite != tailer


def test_telemetry_value_is_valid_for_every_cli():
    r = doctor.run()
    for c in r["clis"].values():
        assert c["telemetry"] in ("tailer+hooks", "tailer", "hooks", "unavailable")


def test_hermes_is_hook_capable_via_plugin():
    r = doctor.run()
    h = r["clis"]["hermes"]
    assert h["hooks_capable"] is True
    assert h["hook_kind"] == "plugin"
    assert h["session_glob"] is None  # no session-file store located — hooks only


def test_normalize_supported_only_for_implemented_tables():
    r = doctor.run()
    assert r["clis"]["claude"]["normalize_supported"] is True
    assert r["clis"]["codex"]["normalize_supported"] is True   # Phase 3 (2026-07-10)
    assert r["clis"]["grok"]["normalize_supported"] is True    # Phase 3 (2026-07-10)
    assert r["clis"]["agy"]["normalize_supported"] is False    # provisional (SQLite, unverified)
    assert r["clis"]["hermes"]["normalize_supported"] is False  # hooks-only


def test_env_home_override_and_transcript_glob(tmp_path, monkeypatch):
    sess = tmp_path / "sessions" / "2026" / "07" / "10"
    sess.mkdir(parents=True)
    (sess / "rollout-abc.jsonl").write_text("{}\n")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    r = doctor.detect_clis()
    c = r["codex"]
    assert c["home"] == str(tmp_path)
    if c["available"]:  # transcript glob only probed when the binary exists
        assert c["transcripts"] == 1


def test_format_report_runs():
    text = doctor.format_report(doctor.run())
    assert "OS" in text and "CLI" in text and "capabilities" in text
