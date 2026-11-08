from hhfinder.config import KEYWORD_GROUPS, Settings
from hhfinder.queries import build_queries


def test_query_plan_covers_keywords_broad_roles_and_alabuga():
    settings = Settings()
    queries = build_queries(settings)
    labels = " ".join(q.label.lower() for q in queries)
    assert len(queries) >= 25
    for group in KEYWORD_GROUPS:
        assert any(q.category == group for q in queries)
    assert any(q.kind == "broad" for q in queries)
    assert any(q.kind == "roles" and "professional_role" in q.params for q in queries)
    alabuga = [q for q in queries if q.alabuga_only]
    assert alabuga
    assert all("1624" in q.params["area"] for q in alabuga)
    assert all(q.params["area"][:2] == ["1641", "1633"] or "1641" in q.params["area"] for q in queries)
    assert all("noExperience" in q.params["experience"] for q in queries)
    assert all("between1And3" in q.params["experience"] for q in queries)
    assert len({repr(sorted((k, repr(v)) for k, v in q.params.items())) for q in queries}) == len(queries)


def test_disabling_group_and_custom_keywords():
    settings = Settings()
    settings.enabled_groups["IT и техподдержка"] = False
    settings.custom_keywords = "pytest, playwright"
    queries = build_queries(settings)
    assert not any(q.category == "IT и техподдержка" for q in queries)
    assert any("pytest" in q.params.get("text", "") for q in queries if q.kind == "custom")
