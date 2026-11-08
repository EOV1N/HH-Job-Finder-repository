"""Единая модель вакансии для всех источников, БД, оценки и UI."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any

_UNKNOWN = object()


def _load_json(value: Any, default: Any) -> Any:
    if value in (None, "", b""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass
class Vacancy:
    id: str = ""
    source: str = ""
    title: str = ""
    company: str = ""
    employer_id: str | None = None

    salary_from: float | None = None
    salary_to: float | None = None
    currency: str | None = None
    salary_display: str = ""
    gross: bool | None = None
    salary_frequency: str = ""
    salary_monthly_rub: float | None = None
    no_salary: bool = True

    city: str = ""
    address: str = ""
    experience: str = ""
    experience_id: str = ""
    required_years: int | None = None
    work_format: str = ""
    employment: str = ""
    schedule: str = ""

    description: str = ""
    responsibilities: str = ""
    requirements: str = ""
    key_skills: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    published_at: str = ""
    updated_at: str = ""
    # api / page / published_fallback / change_tracking
    updated_at_source: str = "published_fallback"
    url: str = ""

    category: str = "Другие направления"
    search_tags: list[str] = field(default_factory=list)
    score: float = 0.0
    score_explanation: str = ""
    score_factors: dict[str, float] = field(default_factory=dict)

    is_favorite: bool = False
    is_new: bool = False
    enriched: bool = False
    excluded: bool = False
    exclusion_reason: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    last_changed_at: str = ""
    content_hash: str = ""

    @classmethod
    def from_row(cls, row: Any) -> "Vacancy":
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        data: dict[str, Any] = {}
        for f in fields(cls):
            value = row[f.name] if f.name in keys else _UNKNOWN
            if value is _UNKNOWN:
                continue
            if f.name in {"key_skills", "labels", "search_tags"}:
                data[f.name] = _load_json(value, [])
            elif f.name == "score_factors":
                data[f.name] = _load_json(value, {})
            elif f.name in {
                "gross", "no_salary", "is_favorite", "is_new", "enriched", "excluded",
            }:
                data[f.name] = bool(value)
            elif f.name == "score":
                data[f.name] = float(value or 0.0)
            else:
                data[f.name] = value
        return cls(**data)

    def to_dict(self, human: bool = True) -> dict[str, Any]:
        d = asdict(self)
        if human:
            for key in ("key_skills", "labels", "search_tags"):
                d[key] = ", ".join(d[key] or [])
            d["score_factors"] = _dump_json(d.get("score_factors") or {})
        return d

    def db_values(self) -> dict[str, Any]:
        d = asdict(self)
        for key in ("key_skills", "labels", "search_tags", "score_factors"):
            d[key] = _dump_json(d.get(key) or ([] if key != "score_factors" else {}))
        for key in ("gross", "no_salary", "is_favorite", "is_new", "enriched", "excluded"):
            d[key] = int(bool(d[key]))
        return d

    def merge(self, other: "Vacancy", keep_search: bool = True) -> "Vacancy":
        """Дополняет текущую вакансию непустыми полями из подробной карточки."""
        tags = list(dict.fromkeys([*self.search_tags, *other.search_tags]))
        labels = list(dict.fromkeys([*self.labels, *other.labels]))
        bool_fields = {
            "gross", "no_salary", "is_favorite", "is_new", "enriched", "excluded",
        }
        for f in fields(self):
            if f.name in {"id", "search_tags", "labels", "is_favorite", "is_new",
                          "first_seen_at", "last_seen_at", "last_changed_at"}:
                continue
            new = getattr(other, f.name)
            if f.name in bool_fields:
                # False у no_salary/enriched — значимое значение, а не «пусто».
                if f.name in {"no_salary", "enriched", "excluded"} or new is not None:
                    setattr(self, f.name, bool(new))
                continue
            empty = new is None or new == "" or new == [] or new == {}
            if not empty:
                setattr(self, f.name, new)
        if keep_search:
            self.search_tags = tags
        self.labels = labels
        if not self.url and self.id:
            self.url = f"https://hh.ru/vacancy/{self.id}"
        return self


@dataclass
class RunSummary:
    run_id: int = 0
    source: str = ""
    api_status: str = ""
    queries_total: int = 0
    pages_done: int = 0
    found: int = 0
    unique: int = 0
    new_count: int = 0
    updated_count: int = 0
    changes_count: int = 0
    details_done: int = 0
    detail_errors: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    cancelled: bool = False
    captcha_stopped: bool = False

    def headline(self) -> str:
        extra = ""
        if self.captcha_stopped:
            extra = "; загрузка описаний остановлена из-за капчи HH"
        return (
            f"Найдено {self.unique} уникальных вакансий, новых: {self.new_count}, "
            f"описаний загружено: {self.details_done}, изменений: {self.changes_count}{extra}"
        )
