"""Формирование набора поисковых запросов для HH API и резервного режима."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import (
    BROAD_QUERIES,
    KEYWORD_GROUPS,
    ROLE_CATEGORY_GROUPS,
    Settings,
)

# Минимальный набор ролей на случай, если справочник /professional_roles недоступен.
FALLBACK_ROLES: dict[str, list[str]] = {
    "11": ["96", "156", "160", "165", "104", "10"],
    "4": ["25", "40"],
    "5": ["12", "113"],
    "3": ["77", "113"],
    "1": ["23", "40", "113"],
    "2": ["97", "104"],
    "6": ["12", "24", "46"],
    "24": ["25", "40"],
    "7": ["82", "96", "113"],
    "17": ["40", "104"],
    "10": ["40", "104"],
    "25": ["40", "165"],
    "27": ["40", "165"],
}

ROLE_GROUP_TO_CATEGORY: dict[str, str] = {
    "IT и разработка": "Разработка и тестирование",
    "Администрирование и офис": "Управление и администрирование",
    "Продажи и обслуживание": "Продажи и клиенты",
    "Маркетинг, медиа, творчество": "Дизайн и медиа",
    "Производство и рабочие профессии": "Производство и инженерия",
    "Транспорт и логистика": "Другие направления",
    "Наука, образование, медицина": "Другие направления",
    "Другие сферы": "Другие направления",
}


@dataclass
class SearchQuery:
    label: str
    category: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    pages: int = 1
    alabuga_only: bool = False

    def storage_value(self) -> str:
        import json
        return json.dumps({"label": self.label, "params": self.params}, ensure_ascii=False)


def _or_phrase(parts: list[str]) -> str:
    cleaned: list[str] = []
    for part in parts:
        part = part.strip().strip('"')
        if part and part not in cleaned:
            cleaned.append(part)
    return " OR ".join(f'"{p}"' for p in cleaned)


def _chunks(items: list[str], size: int = 4) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _base_params(settings: Settings, areas: list[str], text: str) -> dict[str, Any]:
    return {
        "text": text,
        "area": list(areas),
        "experience": settings.selected_experience_ids,
        # API использует period, публичный поиск hh.ru — search_period.
        "period": settings.search_period_days,
        "search_period": settings.search_period_days,
        "order_by": "publication_time",
        # Публичная выдача отдаёт краткие обязанности/требования прямо в карточке.
        # Это уменьшает число детальных запросов и помогает проверять опыт.
        "enable_snippets": "true",
        "no_magic": True,
        "host": "hh.ru",
    }


def build_queries(
    settings: Settings,
    roles_by_category: dict[str, list[str]] | None = None,
) -> list[SearchQuery]:
    """Возвращает дедуплицированный план поиска.

    Ключевые слова объединяются в группы через OR, чтобы охватить все направления,
    но не делать сотни сетевых запросов. Широкие запросы и профессиональные роли
    находят предложения, в названии которых нет ни одного заданного слова.
    """
    roles_by_category = roles_by_category or FALLBACK_ROLES
    area_ids = settings.selected_area_ids
    queries: list[SearchQuery] = []

    for group, words in KEYWORD_GROUPS.items():
        if not settings.enabled_groups.get(group, True):
            continue
        for idx, chunk in enumerate(_chunks(words, 4), start=1):
            label = f"{group}: {', '.join(chunk)}"
            params = _base_params(settings, area_ids, _or_phrase(chunk))
            queries.append(SearchQuery(
                label=label, category=group, kind="keywords",
                params=params, pages=settings.pages_per_query,
            ))

    custom = [x.strip() for x in settings.custom_keywords.replace(",", "\n").splitlines() if x.strip()]
    for idx, chunk in enumerate(_chunks(custom, 4), start=1):
        queries.append(SearchQuery(
            label=f"Пользовательский запрос {idx}: {', '.join(chunk)}",
            category="Широкий поиск", kind="custom",
            params=_base_params(settings, area_ids, _or_phrase(chunk)),
            pages=settings.pages_per_query,
        ))

    if settings.broad_enabled:
        for label, text, bonus in BROAD_QUERIES:
            queries.append(SearchQuery(
                label=label,
                category=ROLE_GROUP_TO_CATEGORY.get(label, "Широкий поиск"),
                kind="broad",
                params=_base_params(settings, area_ids, text),
                pages=min(10, settings.pages_per_query + bonus),
            ))

    if settings.role_categories_enabled:
        for group, category_ids in ROLE_CATEGORY_GROUPS.items():
            role_ids: list[str] = []
            for cid in category_ids:
                for rid in roles_by_category.get(cid, FALLBACK_ROLES.get(cid, [])):
                    if rid not in role_ids:
                        role_ids.append(str(rid))
            if not role_ids:
                continue
            params = _base_params(settings, area_ids, "")
            params["professional_role"] = role_ids[:45]
            queries.append(SearchQuery(
                label=f"Профроли: {group}",
                category=ROLE_GROUP_TO_CATEGORY.get(group, "Широкий поиск"),
                kind="roles", params=params,
                pages=settings.pages_per_query,
            ))

    if settings.alabuga_enabled and settings.areas.get("alabuga", True):
        alabuga_areas = list(dict.fromkeys([*area_ids, "1624"]))
        for text in [
            '"Алабуга"',
            '"ОЭЗ Алабуга" OR "особая экономическая зона Алабуга"',
        ]:
            queries.append(SearchQuery(
                label=f"ОЭЗ Алабуга: {text}",
                category="Широкий поиск",
                kind="alabuga",
                params=_base_params(settings, alabuga_areas, text),
                pages=min(10, settings.pages_per_query + 1),
                alabuga_only=True,
            ))

    # Один и тот же text+набор фильтров не запрашивается дважды.
    seen: set[str] = set()
    unique: list[SearchQuery] = []
    for q in queries:
        key = repr(sorted((k, repr(v)) for k, v in q.params.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    return unique
