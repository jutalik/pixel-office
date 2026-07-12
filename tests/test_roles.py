from pixel_office.company import roles, skills, workflows


def test_every_role_is_internally_consistent():
    assert len(roles.ROLES) >= 10
    for r in roles.ROLES.values():
        assert r.family in skills.FAMILIES, r.id
        assert r.tier in roles.TIERS, r.id
        assert r.persona, r.id
        for sid in r.skills:
            assert sid in skills.SKILLS, (r.id, sid)
        for wid in r.workflows:
            assert wid in workflows.WORKFLOWS, (r.id, wid)


def test_headline_roles_exist():
    for rid in ("project-owner", "architect", "backend", "frontend", "designer",
                "writer", "growth", "data", "qa", "devops", "pm"):
        assert roles.get(rid) is not None, rid
    arch = roles.get("architect")
    assert arch.tier == "deep" and "system-design" in arch.skills   # high-performance architect


def test_default_teams_resolve_and_are_bounded():
    assert roles.DEFAULT_TEAMS
    for stack, team in roles.DEFAULT_TEAMS.items():
        assert 0 < len(team) <= 12, stack
        for rid in team:
            assert roles.get(rid) is not None, (stack, rid)
    assert roles.default_team_for("api-service")
    assert roles.default_team_for("unknown-stack") == ()


def test_match_title_resolves_known_and_declines_unknown():
    assert roles.match_title("backend engineer").id == "backend"
    assert roles.match_title("architecture engineer").id == "architect"
    assert roles.match_title("content writer").id == "writer"
    # title/id words outweigh shared skill keywords ("testing" leaks "qa" widely)
    assert roles.match_title("QA Engineer").id == "qa"
    assert roles.match_title("DevOps").id == "devops"
    # a title with no clear library role → None (caller keeps the plain title)
    assert roles.match_title("Founder") is None
    assert roles.match_title("astrologer") is None
    assert roles.match_title("") is None
    # a lone shared skill keyword (no title/id match) is too weak → None, not a role
    assert roles.match_title("endpoint") is None
