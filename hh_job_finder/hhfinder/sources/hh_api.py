"""Официальный клиент api.hh.ru.

С 2026 года анонимный GET /vacancies возвращает 403: для поиска вакансий нужен
OAuth-токен приложения или пользователя. Справочники (/areas, /dictionaries,
/professional_roles) остаются доступны и используются приложением всегда.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..config import DEFAULT_RATES, Settings
from ..models import Vacancy
from ..queries import SearchQuery
from ..utils import (
    clean_text,
    content_hash,
    html_to_text,
    infer_required_years,
    monthly_rub_amount,
    normalize_city,
    normalize_experience,
    normalize_work_format,
    parse_salary,
    split_description_sections,
)
from .base import AsyncHTTP, AuthRequired, RateLimiter, SourceError

logger = logging.getLogger(__name__)
CURRENCY_ABBR = {"RUR": "₽", "RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸", "UAH": "₴"}


def _compact_params(source: dict[str, Any], allowed: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in allowed:
        value = source.get(key)
        if value in (None, "", [], False):
            continue
        out[key] = value
    return out


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _salary_display(salary_from: float | None, salary_to: float | None, currency: str | None, gross: bool | None) -> str:
    if salary_from is None and salary_to is None:
        return ""
    symbol = CURRENCY_ABBR.get((currency or "RUR").upper(), (currency or "").upper())
    fmt = lambda n: f"{int(n):,}".replace(",", "\u202f")
    if salary_from is not None and salary_to is not None and salary_from != salary_to:
        text = f"от {fmt(salary_from)} до {fmt(salary_to)} {symbol}"
    elif salary_from is not None:
        text = f"от {fmt(salary_from)} {symbol}"
    else:
        text = f"до {fmt(salary_to)} {symbol}"
    if gross is True:
        text += " до вычета налогов"
    elif gross is False:
        text += " на руки"
    return text


def _address(item: dict[str, Any]) -> tuple[str, str]:
    addr = item.get("address") or {}
    raw = clean_text(addr.get("raw"))
    if not raw and addr:
        raw = ", ".join(clean_text(addr.get(k)) for k in ("city", "street", "building", "description") if clean_text(addr.get(k)))
    city_hint = clean_text((item.get("area") or {}).get("name")) or clean_text(addr.get("city"))
    city = normalize_city(city_hint, raw, clean_text(item.get("name")), clean_text((item.get("employer") or {}).get("name")))
    return city, raw


class HHAPISource:
    name = "hh_api"

    def __init__(self, settings: Settings, limiter: RateLimiter):
        headers = {
            "HH-User-Agent": settings.api_user_agent,
            "User-Agent": "HHJobFinderDesktop/1.0",
            "Accept": "application/json",
        }
        if settings.api_access_token.strip():
            headers["Authorization"] = f"Bearer {settings.api_access_token.strip()}"
        self.settings = settings
        self.http = AsyncHTTP("https://api.hh.ru", headers, limiter, settings.timeout_seconds)

    def set_token(self, token: str) -> None:
        if token.strip():
            self.http.client.headers["Authorization"] = f"Bearer {token.strip()}"
        else:
            self.http.client.headers.pop("Authorization", None)

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self.http.request(path, params=params)
        if response.status_code in (401, 403) and path.startswith("/vacancies"):
            has_token = bool(self.settings.api_access_token.strip())
            msg = (
                "API HH вернул 403 для поиска вакансий. Токен есть, но у приложения нет права "
                "на GET /vacancies." if has_token else
                "API HH требует OAuth-токен для GET /vacancies: анонимный доступ закрыт. "
                "Добавьте токен в Настройках или используйте резервный режим hh.ru."
            )
            raise AuthRequired(msg)
        if response.status_code >= 400:
            raise SourceError(f"api.hh.ru {path}: HTTP {response.status_code}: {response.text[:180]}")
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(f"api.hh.ru {path}: некорректный JSON") from exc

    async def dictionaries(self) -> dict[str, Any]:
        return await self._get_json("/dictionaries")

    async def currency_rates(self) -> dict[str, float]:
        rates = dict(DEFAULT_RATES)
        try:
            data = await self.dictionaries()
            for item in data.get("currency", []):
                code = str(item.get("code", "")).upper()
                rate = _num(item.get("rate"))
                if code and rate and rate > 0:
                    rates[code] = rate
            rates["RUR"] = 1.0
            rates["RUB"] = 1.0
        except Exception as exc:
            logger.warning("Не удалось получить курсы валют HH: %s", exc)
        return rates

    async def professional_roles(self) -> dict[str, list[str]]:
        try:
            data = await self._get_json("/professional_roles")
            result: dict[str, list[str]] = {}
            for category in data.get("categories", []):
                result[str(category.get("id"))] = [
                    str(role.get("id")) for role in category.get("roles", []) if role.get("id")
                ]
            return result
        except Exception as exc:
            logger.warning("Не удалось получить справочник профролей: %s", exc)
            return {}

    async def get_app_token(self, client_id: str, client_secret: str) -> dict[str, Any]:
        response = await self.http.request(
            "/token", method="POST",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise SourceError(f"Не удалось получить токен приложения: HTTP {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError("Ответ /token не содержит JSON") from exc

    def _map_item(self, item: dict[str, Any], enriched: bool = False) -> Vacancy:
        vid = str(item.get("id") or "").strip()
        salary = item.get("salary") or {}
        salary_from = _num(salary.get("from"))
        salary_to = _num(salary.get("to"))
        currency = str(salary.get("currency") or "RUR").upper()
        gross = bool(salary["gross"]) if "gross" in salary and salary.get("gross") is not None else None
        salary_display = _salary_display(salary_from, salary_to, currency, gross)
        city, address = _address(item)
        exp = item.get("experience") or {}
        exp_name, exp_id = normalize_experience(clean_text(exp.get("name")), clean_text(exp.get("id")))
        work_format = normalize_work_format(
            clean_text(item.get("work_format_text")),
            [clean_text(l.get("name")) for l in item.get("labels", []) if isinstance(l, dict)],
            address, item.get("work_format") or [],
        )
        snippet = item.get("snippet") or {}
        resp_html = snippet.get("responsibility") or ""
        req_html = snippet.get("requirement") or ""
        description = html_to_text(item.get("description") or "")
        sections = split_description_sections(description)
        published = clean_text(item.get("published_at") or item.get("created_at"))
        updated = clean_text(item.get("updated_at") or item.get("published_at") or published)

        return Vacancy(
            id=vid, source=self.name,
            title=clean_text(item.get("name")),
            company=clean_text((item.get("employer") or {}).get("name")),
            employer_id=str((item.get("employer") or {}).get("id") or "") or None,
            salary_from=salary_from, salary_to=salary_to, currency=currency,
            salary_display=salary_display, gross=gross,
            salary_frequency="monthly",
            salary_monthly_rub=None,
            no_salary=salary_from is None and salary_to is None,
            city=city, address=address,
            experience=exp_name, experience_id=exp_id,
            required_years=infer_required_years(" ".join([description, html_to_text(req_html)]), exp_id) if description else None,
            work_format=work_format,
            employment=clean_text((item.get("employment") or {}).get("name")),
            schedule=clean_text((item.get("schedule") or {}).get("name")),
            description=description,
            responsibilities=sections["responsibilities"] or html_to_text(resp_html)[:1200],
            requirements=sections["requirements"] or html_to_text(req_html)[:1200],
            key_skills=[clean_text(s.get("name")) for s in item.get("key_skills", []) if isinstance(s, dict) and clean_text(s.get("name"))],
            labels=[clean_text(l.get("name")) for l in item.get("labels", []) if isinstance(l, dict) and clean_text(l.get("name"))],
            published_at=published, updated_at=updated,
            updated_at_source="api" if item.get("updated_at") else "published_fallback",
            url=clean_text(item.get("alternate_url")) or f"https://hh.ru/vacancy/{vid}",
            category="Широкий поиск", search_tags=[],
            enriched=enriched,
            content_hash=content_hash(item.get("name"), salary_display, exp_id),
        )

    async def search(self, query: SearchQuery, page: int) -> list[Vacancy]:
        params = _compact_params(query.params, [
            "text", "area", "experience", "professional_role", "period",
            "order_by", "no_magic", "host", "salary", "only_with_salary",
            "employment", "schedule", "work_format", "label", "enable_snippets",
        ])
        params.update({"page": page, "per_page": 100})
        data = await self._get_json("/vacancies", params)
        return [self._map_item(item, enriched=False) for item in data.get("items", []) if item.get("id")]

    async def fetch_detail(self, vacancy_id: str) -> Vacancy | None:
        data = await self._get_json(f"/vacancies/{vacancy_id}")
        if not isinstance(data, dict) or not data.get("id"):
            return None
        return self._map_item(data, enriched=True)

    async def test(self) -> dict[str, Any]:
        await self.dictionaries()
        try:
            data = await self._get_json("/vacancies", {"per_page": 1, "area": "1641"})
            return {"ok": True, "message": f"/vacancies доступен, найдено: {data.get('found', '?')}"}
        except AuthRequired as exc:
            return {"ok": False, "message": str(exc)}

    async def aclose(self) -> None:
        await self.http.aclose()
