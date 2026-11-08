from hhfinder.models import Vacancy
from hhfinder.scoring import score_vacancy

RATES = {"RUR": 1.0, "USD": 0.0125}


def make_vacancy(**kwargs) -> Vacancy:
    data = dict(
        id="1", source="hh_web", title="Junior системный администратор Linux",
        company="Тестовая компания", salary_from=60000, salary_to=None,
        currency="RUR", salary_display="от 60 000 ₽ за месяц", no_salary=False,
        salary_frequency="monthly", city="Набережные Челны",
        experience="Без опыта", experience_id="noExperience",
        work_format="Офис", employment="Полная занятость", schedule="5/2",
        description="Настройка рабочих мест, сетей и удалённое администрирование. "
                    "Знание Linux, Windows, Python, SQL, Docker, Git и API. Обучение и карьерный рост.",
        responsibilities="Настройка рабочих мест и сетей",
        requirements="Linux, Python, SQL, Git, API",
        key_skills=["Linux", "Python", "SQL"], enriched=True,
        category="IT и техподдержка", published_at="2026-11-01T10:00:00+03:00",
    )
    data.update(kwargs)
    return Vacancy(**data)


def test_good_match_is_high_but_not_inflated():
    v = score_vacancy(make_vacancy(), RATES, True)
    assert 55 <= v.score <= 95
    assert v.excluded is False
    assert "skills" in v.score_factors
    assert v.score_explanation
    assert v.salary_monthly_rub == 60000


def test_description_experience_overrides_metadata():
    v = score_vacancy(make_vacancy(
        description="Опыт работы от 5 лет обязателен. Знание Linux и Python.",
        requirements="Опыт работы от 5 лет",
    ), RATES, True)
    assert v.excluded is True
    assert "5 лет" in v.exclusion_reason
    assert v.score <= 15


def test_no_salary_is_marked_and_reduces_score():
    paid = score_vacancy(make_vacancy(), RATES, True)
    unpaid = score_vacancy(make_vacancy(
        salary_from=None, salary_to=None, salary_display="", no_salary=True,
        salary_monthly_rub=None,
    ), RATES, True)
    assert unpaid.score < paid.score
    assert "зарплата не указана" in unpaid.score_explanation.lower()


def test_manual_role_scores_lower_than_profile_role():
    it = score_vacancy(make_vacancy(), RATES, True)
    courier = score_vacancy(make_vacancy(
        title="Курьер (доставка продуктов)", category="Другие направления",
        description="Доставка заказов, работа на улице.",
        responsibilities="Доставка заказов", requirements="Без опыта",
        key_skills=[],
    ), RATES, True)
    assert courier.score < it.score
    assert courier.score_factors["alignment"] < 0


def test_high_salary_without_profile_skills_is_not_a_top_match():
    hr = score_vacancy(make_vacancy(
        title="Младший специалист Управления HR",
        category="Управление и администрирование",
        salary_from=150000, salary_display="от 150 000 ₽ за месяц",
        description="Массовый подбор персонала, оформление документов.",
        responsibilities="Подбор персонала", requirements="Коммуникабельность",
        key_skills=[],
    ), RATES, True)
    assert hr.score < 50
    assert "минусы" in hr.score_explanation.lower()


def test_strict_filter_can_be_disabled():
    v = score_vacancy(make_vacancy(description="Опыт работы от 6 лет"), RATES, False)
    assert v.excluded is False
    assert v.score < 60
