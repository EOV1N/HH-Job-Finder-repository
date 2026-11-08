from hhfinder.filters import FilterState, apply_filters
from hhfinder.models import Vacancy


def v(vid: str, city: str, **kwargs) -> Vacancy:
    data = dict(
        id=vid, title="Вакансия", company="Компания", city=city,
        salary_from=50000, currency="RUR", salary_display="от 50 000 ₽",
        no_salary=False, category="IT и техподдержка", score=60,
        experience="Без опыта", experience_id="noExperience",
        work_format="Офис", excluded=False,
    )
    data.update(kwargs)
    return Vacancy(**data)


def test_target_city_filter_and_no_salary_marker():
    items = [
        v("1", "Набережные Челны"),
        v("2", "ОЭЗ Алабуга"),
        v("3", "Удалённо", work_format="Удалённо"),
        v("4", "Казань"),
        v("5", "Елабуга", no_salary=True, salary_from=None, salary_display=""),
    ]
    state = FilterState(only_target_cities=True)
    ids = {x.id for x in apply_filters(items, state)}
    assert ids == {"1", "2", "3", "5"}
    state_all = FilterState(only_target_cities=False, include_no_salary=False)
    ids_all = {x.id for x in apply_filters(items, state_all)}
    assert "4" in ids_all and "5" not in ids_all


def test_min_salary_and_search():
    items = [
        v("1", "Елабуга", salary_monthly_rub=40000, title="Системный администратор Linux"),
        v("2", "Елабуга", salary_monthly_rub=90000, title="Менеджер по продажам"),
    ]
    state = FilterState(min_salary=50000, search="Linux", only_target_cities=True)
    assert apply_filters(items, state) == []
    state = FilterState(min_salary=0, search="Linux", only_target_cities=True)
    assert [x.id for x in apply_filters(items, state)] == ["1"]
