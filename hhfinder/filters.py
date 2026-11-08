"""Фильтрация и сортировка вакансий, общая для всех разделов интерфейса."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Vacancy
from .utils import clean_text, parse_iso_date

SORT_OPTIONS = [
    ("score_desc", "Сначала лучшие"),
    ("date_desc", "Сначала новые"),
    ("salary_desc", "Сначала высокая зарплата"),
    ("title_asc", "По названию"),
]

TARGET_CITIES = {
    "Набережные Челны", "Елабуга", "ОЭЗ Алабуга", "Удалённо", "Не указан",
}


@dataclass
class FilterState:
    search: str = ""
    category: str = "Все категории"
    city: str = "Все города"
    work_format: str = "Все форматы"
    min_salary: int = 0
    include_no_salary: bool = True
    only_new: bool = False
    only_favorites: bool = False
    show_excluded: bool = False
    only_target_cities: bool = True
    sort_by: str = "score_desc"

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _salary_for_filter(v: Vacancy) -> float:
    return float(v.salary_monthly_rub or 0.0)


def apply_filters(items: list[Vacancy], state: FilterState, limit: int | None = None) -> list[Vacancy]:
    search = clean_text(state.search).lower()
    result: list[Vacancy] = []
    for v in items:
        if not state.show_excluded and v.excluded:
            continue
        if state.only_favorites and not v.is_favorite:
            continue
        if state.only_new and not v.is_new:
            continue
        if state.category not in ("", "Все категории") and v.category != state.category:
            continue
        if state.city not in ("", "Все города") and v.city != state.city:
            continue
        if state.work_format not in ("", "Все форматы") and v.work_format != state.work_format:
            continue
        if state.only_target_cities and v.city not in TARGET_CITIES:
            continue
        if v.no_salary:
            if not state.include_no_salary:
                continue
        elif state.min_salary > 0 and _salary_for_filter(v) < state.min_salary:
            continue
        if search:
            blob = " ".join([
                v.title, v.company, v.description, v.responsibilities, v.requirements,
                v.address, v.city, " ".join(v.key_skills),
            ]).lower()
            if search not in blob:
                continue
        result.append(v)

    if state.sort_by == "date_desc":
        result.sort(key=lambda v: parse_iso_date(v.published_at) is not None, reverse=True)
        result.sort(key=lambda v: parse_iso_date(v.published_at) or parse_iso_date("1970-01-01"), reverse=True)
    elif state.sort_by == "salary_desc":
        result.sort(key=_salary_for_filter, reverse=True)
    elif state.sort_by == "title_asc":
        result.sort(key=lambda v: v.title.lower())
    else:
        result.sort(key=lambda v: (v.score, parse_iso_date(v.published_at) or parse_iso_date("1970-01-01")), reverse=True)
    if limit is not None:
        return result[:limit]
    return result


def unique_options(items: list[Vacancy]) -> dict[str, list[str]]:
    categories = sorted({v.category for v in items if v.category})
    cities = sorted({v.city for v in items if v.city})
    formats = sorted({v.work_format for v in items if v.work_format})
    return {
        "categories": ["Все категории", *categories],
        "cities": ["Все города", *cities],
        "formats": ["Все форматы", *formats],
    }
