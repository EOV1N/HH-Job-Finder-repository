"""Тесты очистки данных. Синтетические строки используются только как фикстуры."""
from hhfinder.utils import (
    classify_category,
    infer_required_years,
    monthly_rub_amount,
    normalize_city,
    normalize_experience,
    parse_iso_date,
    parse_salary,
    split_description_sections,
)


def test_parse_salary_from_card_data():
    result = parse_salary(
        "от 127\u202f500 ₽ за\u00a0месяц, до вычета налогов",
        ["127500", "RUB", "0"],
    )
    assert result["salary_from"] == 127500
    assert result["salary_to"] is None
    assert result["currency"] == "RUR"
    assert result["gross"] is True
    assert result["no_salary"] is False
    assert result["salary_frequency"] == "monthly"


def test_parse_salary_range_and_no_salary():
    result = parse_salary("75 000 – 90 000 ₽ за месяц", ["75000", "90000", "RUB"])
    assert result["salary_from"] == 75000
    assert result["salary_to"] == 90000
    assert parse_salary("Зарплата не указана")["no_salary"] is True


def test_monthly_rub_conversion():
    # rate из справочника HH: количество единиц валюты за 1 рубль.
    assert monthly_rub_amount(1000, None, "USD", "monthly", {"USD": 0.0125}) == 80000
    assert monthly_rub_amount(500, 700, "RUR", "monthly", {"RUR": 1.0}) == 500


def test_infer_required_years():
    assert infer_required_years("Опыт работы не требуется, обучение на месте") == 0
    assert infer_required_years("Требуется опыт работы от 5 лет") == 5
    assert infer_required_years("Опыт 1–3 года, знание Linux") == 3
    assert infer_required_years("Обязанности: настраивать рабочие места") is None


def test_split_description_sections():
    sections = split_description_sections(
        "Обязанности: настраивать рабочие места и сеть. "
        "Требования: знать Linux, Python и SQL. Условия: официальное трудоустройство, 5/2."
    )
    assert "настраивать" in sections["responsibilities"]
    assert "Linux" in sections["requirements"]
    assert "трудоустройство" in sections["conditions"]


def test_city_and_category():
    assert normalize_city("", "Елабужский район, особая экономическая зона Алабуга, улица Ш-2") == "ОЭЗ Алабуга"
    assert normalize_city("", "Набережные Челны, проспект Мира") == "Набережные Челны"
    assert normalize_city("Елабуга", "") == "Елабуга"
    assert classify_category("Системный администратор Linux") == "IT и техподдержка"
    assert classify_category("Junior Python Developer") == "Разработка и тестирование"
    assert classify_category("Менеджер по продажам") == "Продажи и клиенты"
    assert normalize_city("", "Москва, улица Тверская", work_format="Удалённо") == "Удалённо"


def test_normalize_experience_en_dash():
    assert normalize_experience("1–3 года", "")[1] == "between1And3"
    assert normalize_experience("не требуется", "")[1] == "noExperience"
    assert normalize_experience("Опыт 3–6 лет", "")[1] == "between3And6"


def test_parse_iso_date_always_timezone_aware():
    assert parse_iso_date("2026-11-01T10:00:00").tzinfo is not None
    assert parse_iso_date("2026-11-01T10:00:00+0300").tzinfo is not None
    assert parse_iso_date("2026-11-01").tzinfo is not None
