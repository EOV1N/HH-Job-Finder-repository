"""Щадящий резервный источник: публичные страницы hh.ru.

Используется только когда официальный /vacancies недоступен без токена.
Режим однопользовательский: общий лимит запросов, повторные попытки с паузой,
никаких параллельных обходов всего сайта, никаких скрытых запросов к резюме.
Страницы поиска содержат `?`-параметры, поэтому в robots.txt для `User-agent: *`
они помечены как нежелательные для массовых краулеров; приложение явно
предупреждает об этом и позволяет отключить резервный режим в настройках.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import Settings
from ..models import Vacancy
from ..queries import SearchQuery
from ..utils import (
    clean_text,
    content_hash,
    html_to_text,
    infer_required_years,
    normalize_city,
    normalize_experience,
    normalize_work_format,
    parse_salary,
    split_description_sections,
)
from .base import AsyncHTTP, RateLimiter, SourceError

logger = logging.getLogger(__name__)
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
CURRENCY_SELECTOR = ", ".join(
    f'data[value="{code}"]' for code in ("RUB", "RUR", "USD", "EUR", "KZT", "UAH")
)


def _compact_params(source: dict[str, Any], allowed: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in allowed:
        value = source.get(key)
        if value in (None, "", [], False):
            continue
        out[key] = value
    return out


def _text(node: Any, selector: str = "") -> str:
    if node is None:
        return ""
    found = node.select_one(selector) if selector else node
    return clean_text(found.get_text(" ", strip=True)) if found else ""


def _labels(node: Any) -> list[str]:
    values: list[str] = []
    if node is None:
        return values
    for el in node.select('[data-qa*="label"], [class*="brand-sticker"], [class*="tag__label"]'):
        text = clean_text(el.get_text(" ", strip=True))
        if text and len(text) < 90 and text not in values:
            values.append(text)
    return values[:20]


def _ld_jobposting(soup: BeautifulSoup) -> dict[str, Any]:
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        candidates = data.get("@graph", []) if isinstance(data, dict) and "@graph" in data else [data]
        for item in candidates:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() == "jobposting":
                return item
    return {}


def _detail_address(ld: dict[str, Any], soup: BeautifulSoup) -> tuple[str, str, str]:
    raw = _text(soup, '[data-qa="vacancy-view-raw-address"]')
    addr = ((ld.get("jobLocation") or {}).get("address") or {})
    locality = clean_text(addr.get("addressLocality"))
    region = clean_text(addr.get("addressRegion"))
    street = clean_text(addr.get("streetAddress"))
    if not raw:
        raw = ", ".join(x for x in (locality, region, street) if x)
    city_hint = locality or region
    return city_hint, raw, street


class HHWebSource:
    name = "hh_web"

    def __init__(self, settings: Settings, limiter: RateLimiter):
        headers = {
            "User-Agent": BROWSER_UA,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.6",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.settings = settings
        self.http = AsyncHTTP("https://hh.ru", headers, limiter, settings.timeout_seconds)

    async def _get_html(self, path: str, params: dict[str, Any] | None = None) -> str:
        response = await self.http.request(path, params=params)
        if response.status_code >= 400:
            raise SourceError(f"hh.ru {path}: HTTP {response.status_code}")
        final_url = str(response.url).lower()
        if "/account/captcha" in final_url or "captcha" in final_url and "backurl=" in final_url:
            raise SourceError("hh.ru запросил капчу; уменьшите частоту запросов или повторите позже")
        # Запасная проверка для страницы-заглушки без редиректа.
        head = response.text[:20000].lower()
        if "введите код с картинки" in head or "проверка безопасности" in head and len(response.text) < 100_000:
            raise SourceError("hh.ru запросил капчу; уменьшите частоту запросов или повторите позже")
        return response.text

    def _parse_card(self, card: Any) -> Vacancy | None:
        link = card.select_one('[data-qa="serp-item__title"]')
        title = _text(card, '[data-qa="serp-item__title-text"]') or _text(link)
        href = link.get("href", "") if link else ""
        match = re.search(r"/vacancy/(\d+)", href)
        vid = clean_text(card.get("id")) or (match.group(1) if match else "")
        if not vid or not vid.isdigit() or not title:
            return None
        url = urljoin("https://hh.ru", href.split("?")[0]) if href else f"https://hh.ru/vacancy/{vid}"

        company = _text(card, '[data-qa="vacancy-serp__vacancy-employer-text"]') or _text(card, '[data-qa="vacancy-serp__vacancy_employer"]')
        address = _text(card, '[data-qa="vacancy-serp__vacancy-address"]')
        exp_tag = card.select_one('[data-qa*="vacancy-work-experience-"]')
        exp_id = ""
        if exp_tag:
            qa = exp_tag.get("data-qa", "")
            m = re.search(r"vacancy-work-experience-([A-Za-z0-9]+)", qa)
            exp_id = m.group(1) if m else ""
        exp_name, exp_id = normalize_experience(_text(exp_tag), exp_id)
        labels = _labels(card)
        card_text = card.get_text(" ", strip=True)
        snippet_responsibility = _text(card, '[data-qa="vacancy-serp__vacancy_snippet_responsibility"]')
        snippet_requirement = _text(card, '[data-qa="vacancy-serp__vacancy_snippet_requirement"]')
        snippet_text = " ".join([snippet_responsibility, snippet_requirement])
        snippet_years = infer_required_years(snippet_text, exp_id) if snippet_text else None

        salary_text = ""
        salary_values: list[str] = []
        currency_hint = None
        currency_node = card.select_one(CURRENCY_SELECTOR)
        if currency_node is not None:
            currency_hint = clean_text(currency_node.get("value"))
            salary_node = currency_node.parent
            salary_text = clean_text(salary_node.get_text(" ", strip=True)) if salary_node else ""
            salary_values = [clean_text(d.get("value")) for d in salary_node.select("data")] if salary_node else []
        salary = parse_salary(salary_text, salary_values, currency_hint)

        time_node = card.select_one("time[datetime]")
        published = clean_text(time_node.get("datetime")) if time_node else ""
        if not published:
            date_node = card.select_one('[data-qa*="publication-date"], [data-qa*="vacancy-date"]')
            published = clean_text(date_node.get("datetime") or date_node.get_text(" ", strip=True)) if date_node else ""

        work_format = normalize_work_format(card_text[:600], labels, address)
        schedule = ""
        employment = ""
        for label in labels:
            low = label.lower()
            if not schedule and any(x in low for x in ("5/2", "сменн", "гибк", "график")):
                schedule = label
            if not employment and any(x in low for x in ("занятость", "стажировка", "трудовой договор")):
                employment = label

        city = normalize_city("", address, title, company, work_format)
        return Vacancy(
            id=vid, source=self.name, title=title, company=company,
            salary_from=salary["salary_from"], salary_to=salary["salary_to"],
            currency=salary["currency"], salary_display=salary["salary_display"],
            gross=salary["gross"], salary_frequency=salary["salary_frequency"],
            no_salary=salary["no_salary"],
            city=city, address=address,
            experience=exp_name, experience_id=exp_id,
            work_format=work_format, employment=employment, schedule=schedule,
            responsibilities=snippet_responsibility,
            requirements=snippet_requirement,
            required_years=snippet_years,
            published_at=published, updated_at=published,
            updated_at_source="published_fallback",
            url=url, labels=labels,
            category="Широкий поиск", search_tags=[],
            enriched=False,
            content_hash=content_hash(title, salary["salary_display"], exp_id, snippet_text),
        )

    async def search(self, query: SearchQuery, page: int) -> list[Vacancy]:
        params = _compact_params(query.params, [
            "text", "area", "experience", "professional_role", "search_period",
            "order_by", "enable_snippets",
        ])
        params["page"] = page
        html = await self._get_html("/search/vacancy", params)
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select('div[id][class*="vacancy-card--"]')
        result: list[Vacancy] = []
        for card in cards:
            parsed = self._parse_card(card)
            if parsed:
                result.append(parsed)
        if not cards and "Ничего не найдено" not in html:
            logger.warning("Разметка поиска hh.ru изменилась: карточки не найдены")
        return result

    def _parse_detail(self, vacancy_id: str, html: str) -> Vacancy:
        soup = BeautifulSoup(html, "lxml")
        ld = _ld_jobposting(soup)
        title = _text(soup, '[data-qa="vacancy-title"]') or clean_text(ld.get("title"))
        company = _text(soup, '[data-qa="vacancy-company-name"]') or clean_text((ld.get("hiringOrganization") or {}).get("name"))
        city_hint, address, _street = _detail_address(ld, soup)

        salary_text = _text(soup, '[data-qa="vacancy-salary"]')
        salary_node = soup.select_one('[data-qa="vacancy-salary"]')
        salary_values = [clean_text(d.get("value")) for d in salary_node.select("data")] if salary_node else []
        salary = parse_salary(salary_text, salary_values)
        if not salary["salary_display"] and ld.get("baseSalary"):
            base = ld["baseSalary"]
            value = ((base.get("value") or {}).get("value")) if isinstance(base, dict) else None
            if value:
                salary = parse_salary(f"{value} {clean_text(base.get('currency'))}", [value])

        exp_raw = _text(soup, '[data-qa="vacancy-experience"]') or _text(soup, '[data-qa="work-experience-text"]')
        exp_raw = re.sub(r"^Опыт\s+работы\s*:", "", exp_raw, flags=re.I).strip()
        exp_name, exp_id = normalize_experience(exp_raw)

        employment_raw = _text(soup, '[data-qa="common-employment-text"]')
        employment = re.sub(r"^Тип\s+занятости\s*", "", employment_raw, flags=re.I).strip()
        schedule_raw = _text(soup, '[data-qa="work-schedule-by-days-text"]')
        schedule = re.sub(r"^График\s*:\s*", "", schedule_raw, flags=re.I).strip()
        format_raw = _text(soup, '[data-qa="work-formats-text"]')
        format_raw = re.sub(r"^Формат\s+работы\s*:\s*", "", format_raw, flags=re.I).strip()
        labels = _labels(soup)

        description_node = soup.select_one('[data-qa="vacancy-description"]')
        from_html = html_to_text(str(description_node)) if description_node else ""
        from_ld = html_to_text(ld.get("description") or "")
        description = from_html if len(from_html) >= len(from_ld) else from_ld
        sections = split_description_sections(description)
        skills = [clean_text(x.get_text(" ", strip=True)) for x in soup.select('[data-qa="skills-element"]')]
        skills = list(dict.fromkeys(x for x in skills if x))

        published = clean_text(ld.get("datePosted"))
        if not published:
            time_node = soup.select_one("time[datetime]")
            published = clean_text(time_node.get("datetime")) if time_node else ""
        modified = clean_text(ld.get("dateModified"))
        updated = modified or published
        updated_source = "page" if modified else "published_fallback"

        work_format = normalize_work_format(
            " ".join([format_raw, schedule_raw, shorten_text(description, 500)]),
            labels, address,
        )
        city = normalize_city(city_hint, address, title, company, work_format)
        required_years = infer_required_years(" ".join([sections["requirements"], description]), exp_id)

        return Vacancy(
            id=vacancy_id, source=self.name, title=title, company=company,
            salary_from=salary["salary_from"], salary_to=salary["salary_to"],
            currency=salary["currency"], salary_display=salary["salary_display"],
            gross=salary["gross"], salary_frequency=salary["salary_frequency"],
            no_salary=salary["no_salary"],
            city=city, address=address,
            experience=exp_name, experience_id=exp_id,
            required_years=required_years,
            work_format=work_format, employment=employment, schedule=schedule,
            description=description,
            responsibilities=sections["responsibilities"] or sections["summary"],
            requirements=sections["requirements"],
            key_skills=skills, labels=labels,
            published_at=published, updated_at=updated,
            updated_at_source=updated_source,
            url=f"https://hh.ru/vacancy/{vacancy_id}",
            category="Широкий поиск", search_tags=[],
            enriched=True,
            content_hash=content_hash(title, salary["salary_display"], description, exp_id, work_format),
        )

    async def fetch_detail(self, vacancy_id: str) -> Vacancy | None:
        html = await self._get_html(f"/vacancy/{vacancy_id}")
        if "вакансия не найдена" in html.lower() and len(html) < 50_000:
            return None
        v = self._parse_detail(vacancy_id, html)
        if not v.title:
            raise SourceError(f"Не удалось разобрать страницу вакансии {vacancy_id}: разметка изменилась")
        return v

    async def test(self) -> dict[str, Any]:
        params = {
            "area": self.settings.selected_area_ids,
            "experience": self.settings.selected_experience_ids,
            "search_period": self.settings.search_period_days,
            "page": 0,
        }
        html = await self._get_html("/search/vacancy", params)
        count = len(BeautifulSoup(html, "lxml").select('div[id][class*="vacancy-card--"]'))
        return {
            "ok": count > 0,
            "message": f"Публичная выдача hh.ru доступна, карточек на странице: {count}",
            "robots_warning": "robots.txt не рекомендует массовый обход URL с параметрами; режим ограничен одним пользователем и низкой частотой запросов.",
        }

    async def aclose(self) -> None:
        await self.http.aclose()


def shorten_text(text: str, limit: int = 500) -> str:
    text = clean_text(text)
    return text if len(text) <= limit else text[:limit] + "…"
