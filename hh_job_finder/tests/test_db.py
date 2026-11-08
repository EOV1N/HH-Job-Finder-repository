import sqlite3

from hhfinder.db import Database
from hhfinder.models import Vacancy


def base_vacancy(**kwargs) -> Vacancy:
    data = dict(
        id="100500", source="hh_web", title="IT-специалист",
        company="Компания", salary_from=50000, salary_to=None,
        currency="RUR", salary_display="от 50 000 ₽", no_salary=False,
        city="Набережные Челны", experience="Без опыта", experience_id="noExperience",
        category="IT и техподдержка", score=70, score_explanation="подходит",
        is_new=True, enriched=False, first_seen_at="", last_seen_at="",
    )
    data.update(kwargs)
    return Vacancy(**data)


def test_duplicate_protection_and_favorite(tmp_path):
    db = Database(tmp_path / "jobs.db")
    assert db.upsert_partial(base_vacancy()) is True
    assert db.upsert_partial(base_vacancy(title="IT-специалист (обновлено)")) is False
    with sqlite3.connect(tmp_path / "jobs.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0] == 1
    db.set_favorite("100500", True)
    assert db.get_vacancy("100500").is_favorite is True
    assert db.stats()["new_count"] == 1
    db.mark_seen()
    assert db.stats()["new_count"] == 0


def test_partial_snippets_update_score_without_overwriting_full_cards(tmp_path):
    db = Database(tmp_path / "jobs.db")
    db.upsert_partial(base_vacancy())
    v = base_vacancy(
        responsibilities="Настройка Linux и сетей",
        requirements="Python, SQL, опыт до 3 лет",
        required_years=3, score=81,
        score_explanation="Совпали навыки: Linux, Python",
        score_factors={"skills": 12},
    )
    assert db.upsert_partial(v) is False
    stored = db.get_vacancy("100500")
    assert "Linux" in stored.responsibilities
    assert "Python" in stored.requirements
    assert stored.required_years == 3
    assert stored.score == 81
    assert stored.score_factors == {"skills": 12}


def test_salary_and_description_changes_are_logged(tmp_path):
    db = Database(tmp_path / "jobs.db")
    db.upsert_partial(base_vacancy(description="", enriched=False))
    detail = base_vacancy(
        title="IT-специалист",
        salary_display="от 60 000 ₽", salary_from=60000,
        description="Настройка рабочих мест, Linux, Python.",
        responsibilities="Настройка рабочих мест", requirements="Linux",
        enriched=True, is_new=True,
    )
    # Первая загрузка полной карточки — обогащение, а не изменение работодателем.
    changed, count = db.upsert_detail(detail)
    assert changed is False and count == 0
    assert db.get_changes("100500") == []
    assert db.get_vacancy("100500").is_new is True

    updated = base_vacancy(
        title="IT-специалист",
        salary_display="от 70 000 ₽", salary_from=70000,
        description="Настройка рабочих мест, Linux, Python, Docker.",
        responsibilities="Настройка рабочих мест", requirements="Linux, Docker",
        enriched=True, is_new=True,
    )
    changed, count = db.upsert_detail(updated)
    assert changed is True and count >= 2
    fields = [row["field"] for row in db.get_changes("100500")]
    assert "Зарплата" in fields and "Описание" in fields
    unchanged, count2 = db.upsert_detail(updated)
    assert unchanged is False and count2 == 0
