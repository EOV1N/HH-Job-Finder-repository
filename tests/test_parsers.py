"""Парсеры проверяются на компактных фикстурах в формате реальной разметки HH."""
import json

from bs4 import BeautifulSoup

from hhfinder.sources.hh_api import HHAPISource
from hhfinder.sources.hh_web import HHWebSource

CARD_HTML = """
<div id="138664103" class="vacancy-card--test">
  <span class="vacancy-name-wrapper">
    <a data-qa="serp-item__title" href="https://hh.ru/vacancy/138664103?query=python">
      <span data-qa="serp-item__title-text">Backend Python Developer</span>
    </a>
  </span>
  <span class="salary">от <data value="127500">127 500</data> <data value="RUB">₽</data> за месяц, до вычета налогов</span>
  <data data-qa="vacancy-serp__vacancy-work-experience-noExperience" value="0">Без опыта</data>
  <span data-qa="vacancy-serp__vacancy-employer-text">Алабуга. Строительство</span>
  <span data-qa="vacancy-serp__vacancy-address">Елабужский район, особая экономическая зона Алабуга, улица Ш-2, 4/1</span>
  <span data-qa="vacancy-serp__vacancy_snippet_responsibility">Разработка backend-сервисов на Python и настройка Linux.</span>
  <span data-qa="vacancy-serp__vacancy_snippet_requirement">Опыт работы от 1 года до 3 лет. Python, SQL.</span>
</div>
"""


def _web_source() -> HHWebSource:
    source = object.__new__(HHWebSource)
    source.name = "hh_web"
    return source


def test_parse_search_card():
    card = BeautifulSoup(CARD_HTML, "lxml").select_one("div.vacancy-card--test")
    v = _web_source()._parse_card(card)
    assert v is not None
    assert v.id == "138664103"
    assert v.title == "Backend Python Developer"
    assert v.company == "Алабуга. Строительство"
    assert v.city == "ОЭЗ Алабуга"
    assert v.salary_from == 127500
    assert v.currency == "RUR"
    assert v.gross is True
    assert v.no_salary is False
    assert v.experience_id == "noExperience"
    assert v.url == "https://hh.ru/vacancy/138664103"
    assert "backend-сервисов" in v.responsibilities
    assert "Python, SQL" in v.requirements
    assert v.required_years == 3
    assert v.enriched is False


def test_parse_detail_page():
    ld = {
        "@context": "https://schema.org/", "@type": "JobPosting",
        "description": "<strong>Обязанности:</strong><ul><li>настраивать Linux и сети</li></ul>"
                       "<strong>Требования:</strong><ul><li>Python, SQL, без опыта</li></ul>",
        "datePosted": "2026-10-20T14:51:31.227+03:00",
        "title": "Младший системный администратор Linux",
        "hiringOrganization": {"@type": "Organization", "name": "Алабуга. Эксплуатация объектов"},
        "jobLocation": {"@type": "Place", "address": {
            "@type": "PostalAddress", "addressLocality": "Елабужский район",
            "streetAddress": "особая экономическая зона Алабуга, улица Ш-2",
        }},
    }
    html = f"""
    <html><head><script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></head><body>
      <h1 data-qa="vacancy-title">Младший системный администратор Linux</h1>
      <div data-qa="vacancy-company-name">Алабуга. Эксплуатация объектов</div>
      <div data-qa="vacancy-salary">от 127 500 ₽ за месяц до вычета налогов</div>
      <div data-qa="vacancy-experience">не требуется</div>
      <div data-qa="common-employment-text">Тип занятости Полная занятость</div>
      <div data-qa="work-schedule-by-days-text">График: 5/2</div>
      <div data-qa="work-formats-text">Формат работы: на месте работодателя</div>
      <div data-qa="vacancy-view-raw-address">Елабужский район, особая экономическая зона Алабуга, улица Ш-2, 4/1</div>
      <div data-qa="vacancy-description">Обязанности: настраивать Linux и сети. Требования: Python, SQL, без опыта.</div>
      <span data-qa="skills-element">Linux</span><span data-qa="skills-element">Python</span>
      <time datetime="2026-10-20T11:51:31.227Z">20 октября 2026</time>
    </body></html>
    """
    v = _web_source()._parse_detail("138304972", html)
    assert v.id == "138304972"
    assert v.title == "Младший системный администратор Linux"
    assert v.company == "Алабуга. Эксплуатация объектов"
    assert v.city == "ОЭЗ Алабуга"
    assert v.salary_from == 127500
    assert v.experience_id == "noExperience"
    assert v.work_format == "Офис"
    assert "Полная занятость" in v.employment
    assert "5/2" in v.schedule
    assert "Linux" in v.description
    assert "Python" in v.key_skills
    assert v.required_years == 0
    assert v.published_at.startswith("2026-10-20")
    assert v.updated_at_source == "published_fallback"
    assert v.enriched is True


def test_api_item_mapping():
    source = object.__new__(HHAPISource)
    source.name = "hh_api"
    item = {
        "id": "999", "name": "Junior Python Developer",
        "employer": {"id": "42", "name": "Компания"},
        "salary": {"from": 55000, "to": None, "currency": "RUR", "gross": True},
        "area": {"name": "Набережные Челны"},
        "address": {"city": "Набережные Челны", "raw": "Набережные Челны, проспект Мира, 1"},
        "experience": {"id": "noExperience", "name": "Без опыта"},
        "employment": {"name": "Полная занятость"},
        "schedule": {"name": "Полный день"},
        "snippet": {"responsibility": "Разработка API", "requirement": "Python, SQL"},
        "published_at": "2026-11-01T12:00:00+0300",
        "alternate_url": "https://hh.ru/vacancy/999",
    }
    v = source._map_item(item)
    assert v.source == "hh_api"
    assert v.salary_from == 55000
    assert v.city == "Набережные Челны"
    assert v.experience_id == "noExperience"
    assert v.url == "https://hh.ru/vacancy/999"
    assert "API" in v.responsibilities
