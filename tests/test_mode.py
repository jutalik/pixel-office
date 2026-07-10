import pytest

from pixel_office.company.mode import OperatingMode, default, preset


def test_presets():
    assert preset("Manual").drive == "Manual"
    assert preset("autopilot").drive == "Autopilot"          # case-insensitive
    assert default().drive == "Copilot"
    with pytest.raises(ValueError):
        preset("Turbo")


def test_from_dict_string_and_overrides():
    assert OperatingMode.from_dict("Autopilot").ceo_updates == "Weekly digest"
    m = OperatingMode.from_dict({"drive": "Autopilot", "culture": "Research"})
    assert m.drive == "Autopilot" and m.culture == "Research"   # override on preset
    assert OperatingMode.from_dict(None).drive == "Copilot"     # garbage → default


def test_validate_rejects_bad_fields():
    with pytest.raises(ValueError):
        OperatingMode(drive="Nope").validate()
    with pytest.raises(ValueError):
        OperatingMode.from_dict({"drive": "Copilot", "self_tuning": "Maybe"})


def test_one_way_door_always_reaches_ceo_in_every_mode():
    for name in ("Manual", "Copilot", "Autopilot"):
        assert preset(name).reaches_ceo(one_way_door=True, risk="low") is True


def test_reversible_escalation_by_mode():
    manual, copilot, auto = preset("Manual"), preset("Copilot"), preset("Autopilot")
    # Autopilot: reversible never reaches the CEO
    assert auto.reaches_ceo(one_way_door=False, risk="high") is False
    # Copilot: only high-risk reversible
    assert copilot.reaches_ceo(one_way_door=False, risk="high") is True
    assert copilot.reaches_ceo(one_way_door=False, risk="medium") is False
    # Manual: medium+ reversible
    assert manual.reaches_ceo(one_way_door=False, risk="medium") is True
    assert manual.reaches_ceo(one_way_door=False, risk="low") is False


def test_garbage_input_never_crashes():
    assert OperatingMode.from_dict({"drive": 123}).drive == "Copilot"   # non-str drive
    assert OperatingMode.from_dict({"drive": "Turbo"}).drive == "Copilot"  # unknown
    assert OperatingMode.from_dict({"drive": "Autopilot", "culture": 999}).drive == "Autopilot"


def test_unknown_risk_fails_safe_to_escalate():
    # a garbage risk must escalate (never silently hide a decision from the CEO)
    assert preset("Autopilot").reaches_ceo(one_way_door=False, risk="???") is True


def test_roundtrip():
    m = preset("Autopilot")
    assert OperatingMode.from_dict(m.to_dict()) == m
