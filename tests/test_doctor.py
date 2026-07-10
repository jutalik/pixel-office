from pixel_office import doctor


def test_run_shape():
    r = doctor.run()
    assert "os" in r and "clis" in r
    assert r["os"]["system"] in ("Linux", "Darwin", "Windows")
    for name in ("claude", "codex", "grok", "gemini", "hermes"):
        assert name in r["clis"]
        c = r["clis"][name]
        assert {"available", "hooks", "session_dir", "telemetry"}.issubset(c)


def test_format_report_runs():
    text = doctor.format_report(doctor.run())
    assert "OS" in text and "CLI" in text


def test_telemetry_value_is_valid_for_every_cli():
    r = doctor.run()
    for c in r["clis"].values():
        assert c["telemetry"] in ("hooks+tailer", "tailer", "unavailable")
