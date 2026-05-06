"""Tests for the 50-scenario seed corpus."""

import pytest

import storage
import seed_scenarios


@pytest.fixture(autouse=True)
def clean_storage():
    storage._reset_for_tests()
    yield
    storage._reset_for_tests()


def test_build_returns_50_scenarios():
    sc = seed_scenarios.build_seed_scenarios()
    assert len(sc) == 50


def test_seed_persists_50():
    result = seed_scenarios.seed()
    assert result["saved"] == 50
    assert result["skipped"] == 0
    assert len(storage.list_scenarios()) == 50


def test_seed_is_idempotent():
    seed_scenarios.seed()
    second = seed_scenarios.seed()
    assert second["saved"] == 0
    assert second["skipped"] == 50
    assert len(storage.list_scenarios()) == 50


def test_seed_force_overwrites():
    seed_scenarios.seed()
    second = seed_scenarios.seed(force=True)
    assert second["saved"] == 50  # All re-saved


def test_each_seed_has_3_to_6_questions():
    for s in seed_scenarios.build_seed_scenarios():
        n = len(s["questions"])
        assert 3 <= n <= 6, f"Scenario {s['id']} has {n} questions"


def test_each_seed_has_at_least_2_distinct_categories():
    for s in seed_scenarios.build_seed_scenarios():
        cats = {q["category"] for q in s["questions"]}
        assert len(cats) >= 2 or len(s["questions"]) == 1, (
            f"Scenario {s['id']} has only {cats}"
        )


def test_seed_covers_at_least_6_verticals():
    sc = seed_scenarios.build_seed_scenarios()
    verticals = {tag for s in sc for tag in s.get("tags", []) if tag != "seed"}
    assert len(verticals) >= 6, f"Found verticals: {verticals}"


def test_seed_covers_at_least_12_clients():
    sc = seed_scenarios.build_seed_scenarios()
    clients = {s["client"] for s in sc}
    assert len(clients) >= 12, f"Found {len(clients)} clients"


def test_seed_uses_seed_id_prefix():
    """All seed scenarios use the seed-NNN ID format so re-seed can detect them."""
    for s in seed_scenarios.build_seed_scenarios():
        assert s["id"].startswith("seed-")


def test_seed_scenarios_are_marked_seed():
    for s in seed_scenarios.build_seed_scenarios():
        assert s.get("_seed") is True


def test_seed_question_categories_only_use_known_values():
    valid = {"technical", "compliance", "pricing", "company-info"}
    for s in seed_scenarios.build_seed_scenarios():
        for q in s["questions"]:
            assert q["category"] in valid


def test_user_added_scenarios_not_overwritten_by_seed():
    """If a user creates a non-seed scenario, seeding shouldn't touch it."""
    storage.save_scenario({"name": "My Scenario", "questions": []})
    user_count_before = len([s for s in storage.list_scenarios() if not s["id"].startswith("seed-")])
    assert user_count_before == 1

    seed_scenarios.seed()
    user_count_after = len([s for s in storage.list_scenarios() if not s["id"].startswith("seed-")])
    assert user_count_after == 1
