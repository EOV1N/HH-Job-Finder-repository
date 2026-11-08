"""Утилиты очистки текста, зарплат, дат, городов и классификации."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from bs4 import BeautifulSoup

CURRENCY_SYMBOLS = {
    "₽": "RUR", "руб": "RUR", "рублей": "RUR", "rur": "RUR", "rub": "RUR",
    "$": "USD", "usd": "USD", "доллар": "USD",
    "€": "EUR", "eur": "EUR", "евро": "EUR",
    "₸": "KZT", "kzt": "KZT", "тенге": "KZT",
    "₴": "UAH", "uah": "UAH", "грив": "UAH",
}
CURRENCY_CODES = {"RUR", "RUB", "USD", "EUR", "KZT", "UAH", "AZN", "BYR", "GEL", "KGS", "UZS"}
SPACES = "\u00a0\u202f\u2009\u2007\u2060 "


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text.replace("\u200b", ""))
    return text.strip()


def html_to_text(value: Any) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(html.unescape(str(value)), "lxml")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
        li.append("\n")
    for tag in soup.find_all(["p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "tr"]):
        tag.insert_before("\n")
        tag.append("\n")
    raw = soup.get_text("\n")
    lines = [clean_text(line) for line in raw.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def shorten(text: str, limit: int = 500) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(f"[{re.escape(SPACES)}]", "", str(value))
    s = s.replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return None
    return float(s)


def detect_currency(text: str, hint: str | None = None) -> str | None:
    if hint:
        code = str(hint).upper()
        if code in CURRENCY_CODES:
            return "RUR" if code == "RUB" else code
    low = text.lower()
    for token, code in CURRENCY_SYMBOLS.items():
        if token in low:
            return code
    for code in CURRENCY_CODES:
        if re.search(rf"\b{code.lower()}\b", low):
            return "RUR" if code == "RUB" else code
    return None


def detect_frequency(text: str) -> str:
    low = text.lower()
    rules = [
        (r"за\s*час|в\s*час|почасов", "hourly"),
        (r"за\s*смену|в\s*смену|посменн", "shift"),
        (r"за\s*день|в\s*день|ежеднев", "daily"),
        (r"за\s*неделю|в\s*неделю|еженедель", "weekly"),
        (r"за\s*год|в\s*год|годов", "annual"),
        (r"за\s*месяц|в\s*месяц|ежемесяч|месяц", "monthly"),
    ]
    for pattern, name in rules:
        if re.search(pattern, low):
            return name
    return "monthly"  # большинство вакансий HH указывают доход за месяц


def parse_salary(
    text: str,
    data_values: Iterable[Any] | None = None,
    currency_hint: str | None = None,
) -> dict[str, Any]:
    """Разбирает зарплату из карточки hh.ru или поля API.

    data_values — значения тегов <data value="...">: они точнее, чем регулярное
    выражение по тексту, и позволяют отличить сумму от опыта «1-3 года».
    """
    display = clean_text(text)
    result: dict[str, Any] = {
        "salary_from": None, "salary_to": None, "currency": detect_currency(display, currency_hint),
        "salary_display": display, "gross": None, "salary_frequency": "",
        "no_salary": True,
    }
    if not display or any(x in display.lower() for x in (
        "з/п не указана", "зарплата не указана", "не указана", "по договорённости", "по договоренности",
    )):
        return result

    numbers: list[float] = []
    for raw in data_values or []:
        num = parse_number(raw)
        if num is not None and num >= 1000:
            numbers.append(num)
    if not numbers:
        # Убираем пробелы и неразрывные пробелы, затем ищем суммы от 1000.
        flat = re.sub(f"[{re.escape(SPACES)}]", "", display)
        for match in re.finditer(r"(?<!\d)(\d{3,7})(?!\d)", flat):
            num = float(match.group(1))
            if num >= 1000:
                numbers.append(num)
    # Убираем дубликаты, сохраняя порядок.
    numbers = list(dict.fromkeys(numbers))
    if not numbers:
        return result

    low = display.lower()
    result["no_salary"] = False
    result["salary_frequency"] = detect_frequency(display)
    if "до вычета" in low or "gross" in low:
        result["gross"] = True
    elif "на руки" in low or "за вычетом" in low or "net" in low:
        result["gross"] = False

    if len(numbers) >= 2:
        result["salary_from"], result["salary_to"] = numbers[0], numbers[1]
    elif low.startswith("от ") or re.search(r"^от\s", low):
        result["salary_from"] = numbers[0]
    elif low.startswith("до ") or re.search(r"^до\s", low):
        result["salary_to"] = numbers[0]
    else:
        # Точная сумма без «от/до»: сохраняем как обе границы.
        result["salary_from"] = result["salary_to"] = numbers[0]
    return result


def monthly_rub_amount(
    salary_from: float | None,
    salary_to: float | None,
    currency: str | None,
    frequency: str,
    rates: dict[str, float],
) -> float | None:
    amount = salary_from if salary_from is not None else salary_to
    if amount is None or amount <= 0:
        return None
    code = (currency or "RUR").upper()
    code = "RUR" if code == "RUB" else code
    rate = float(rates.get(code, 1.0) or 1.0)
    if rate <= 0:
        rate = 1.0
    rub = amount / rate  # в справочнике HH rate — количество валюты за 1 рубль
    multipliers = {
        "hourly": 160.0, "shift": 21.0, "daily": 21.0,
        "weekly": 4.3, "monthly": 1.0, "annual": 1 / 12,
    }
    return round(rub * multipliers.get(frequency or "monthly", 1.0), 2)


MONTH_WORDS = {
    "год": 1, "года": 2, "лет": 3, "году": 1,
    "одного": 1, "двух": 2, "трех": 3, "трёх": 3, "четырех": 4,
    "четырёх": 4, "пяти": 5, "шести": 6, "семи": 7, "восьми": 8,
    "девяти": 9, "десяти": 10,
}


def infer_required_years(text: str, experience_id: str = "") -> int | None:
    """Оценка фактически требуемого опыта по тексту описания."""
    low = clean_text(text).lower().replace("–", "-").replace("—", "-")
    if not low:
        return None
    if any(x in low for x in ("без опыта", "опыт не требуется", "опыт работы не требуется", "не требуется опыт")):
        return 0
    if experience_id == "noExperience":
        # Метаданные говорят «без опыта», но текст может содержать «от 5 лет».
        pass

    candidates: list[int] = []
    patterns = [
        r"от\s*(\d{1,2})\s*(?:года|лет|год)\s*до\s*(\d{1,2})\s*(?:лет|года|год)",
        r"(?:опыт|стаж)[^.\n]{0,45}?(?:от|не менее|не меньше|более|больше|минимум|свыше)?\s*(\d{1,2})\s*\+?\s*(?:до\s*\d{1,2}\s*)?(?:лет|года|год)",
        r"(?:от|не менее|не меньше|более|больше|минимум|свыше)\s*(\d{1,2})\s*\+?\s*(?:лет|года|год)",
        r"(\d{1,2})\s*\+\s*(?:лет|года|год)",
        r"опыт[^.\n]{0,30}?(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(?:лет|года|год)",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, low, re.I):
            for group in m.groups():
                if group and group.isdigit():
                    n = int(group)
                    if 0 <= n <= 20:
                        candidates.append(n)
    for m in re.finditer(r"(?:от|не менее|не меньше|более|больше)\s*(одного|двух|трех|трёх|четырех|четырёх|пяти|шести|семи|восьми|девяти|десяти)\s*(?:лет|года|год)", low):
        candidates.append(MONTH_WORDS[m.group(1)])
    if not candidates:
        return None
    return max(candidates)


SECTION_PATTERNS = {
    "responsibilities": r"(?:обязанности|задачи|что\s+(?:нужно|предстоит|будете)\s+делать|чем\s+заниматься|функции)\s*[:\-–]?",
    "requirements": r"(?:требования|что\s+мы\s+ждём|что\s+мы\s+ждем|необходимые\s+навыки|ожидания|квалификация|что\s+нужно\s+знать|кандидат)\s*[:\-–]?",
    "conditions": r"(?:условия|мы\s+предлагаем|что\s+мы\s+предлагаем|формат\s+работы|график\s+работы)\s*[:\-–]?",
}


def split_description_sections(description: str) -> dict[str, str]:
    """Выделяет обязанности/требования/условия из уже очищенного текста."""
    text = clean_text(description).replace("\r", "\n")
    if not text:
        return {"responsibilities": "", "requirements": "", "conditions": "", "summary": ""}
    flat = re.sub(r"\s+", " ", text)
    marks: list[tuple[int, str, str]] = []
    for name, pattern in SECTION_PATTERNS.items():
        for m in re.finditer(pattern, flat, re.I):
            marks.append((m.start(), name, m.group(0)))
    marks.sort()
    sections: dict[str, str] = {k: "" for k in SECTION_PATTERNS}
    for idx, (start, name, heading) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(flat)
        body = flat[start + len(heading):end].strip(" :;-–•\n")
        if body and not sections[name]:
            sections[name] = shorten(body, 1200)
    summary = shorten(flat, 600)
    return {**sections, "summary": summary}


def normalize_city(
    city_hint: str = "",
    address: str = "",
    title: str = "",
    company: str = "",
    work_format: str = "",
) -> str:
    blob = " ".join([city_hint, address, title, company]).lower()
    if "алабуга" in blob:
        return "ОЭЗ Алабуга"
    if "елабужск" in blob or "елабуг" in blob:
        return "Елабуга"
    if "набережн" in blob or "челн" in blob:
        return "Набережные Челны"
    hint = clean_text(city_hint)
    remote = "удал" in (work_format or "").lower() or "гибрид" in (work_format or "").lower()
    if remote:
        # Для удалённой/гибридной вакансии город работодателя не должен
        # превращать предложение в «Москва» или «Новая Земля».
        return "Удалённо"
    if hint and hint.lower() not in {"россия", "республика татарстан"}:
        return hint
    addr = clean_text(address).split(",")[0].strip()
    if addr and addr.lower() not in {"россия", "республика татарстан"}:
        return addr[:80]
    return "Не указан"


def normalize_work_format(
    text: str = "",
    labels: Iterable[str] | None = None,
    address: str = "",
    api_formats: Iterable[Any] | None = None,
) -> str:
    ids: list[str] = []
    for item in api_formats or []:
        if isinstance(item, dict):
            ids.append(str(item.get("id", "")).upper())
        else:
            ids.append(str(item).upper())
    if "REMOTE" in ids and ("ON_SITE" in ids or "HYBRID" in ids):
        return "Гибрид"
    if "REMOTE" in ids:
        return "Удалённо"
    if "HYBRID" in ids:
        return "Гибрид"
    if "FIELD_WORK" in ids:
        return "Разъездной"
    if "ON_SITE" in ids:
        return "Офис"
    blob = " ".join([text, *(labels or [])]).lower()
    if "гибрид" in blob:
        return "Гибрид"
    if any(x in blob for x in ("удалённо", "удаленно", "remote", "можно удалённо", "из дома")):
        return "Удалённо"
    if "разъездн" in blob:
        return "Разъездной"
    if any(x in blob for x in ("на месте работодателя", "офис", "в офисе")) or clean_text(address):
        return "Офис"
    return "Не указан"


def normalize_experience(name: str = "", experience_id: str = "") -> tuple[str, str]:
    low = clean_text(name).lower().replace("–", "-").replace("—", "-")
    eid = experience_id
    if not eid:
        if "3-6" in low or "3 до 6" in low or "от 3 до 6" in low or "от 3 лет" in low:
            eid = "between3And6"
        elif "более 6" in low or "больше 6" in low or "от 6 лет" in low:
            eid = "moreThan6"
        elif (
            "1-3" in low or "1 до 3" in low or "от 1 года" in low
            or "от года" in low or "до 3 лет" in low
        ):
            eid = "between1And3"
        elif any(x in low for x in ("без опыта", "не требуется", "нет опыта", "опыт не нужен")):
            eid = "noExperience"
    names = {
        "noExperience": "Без опыта",
        "between1And3": "От 1 года до 3 лет",
        "between3And6": "От 3 до 6 лет",
        "moreThan6": "Более 6 лет",
    }
    return (clean_text(name) or names.get(eid, "Не указан"), eid)


def classify_category(title: str, description: str = "", fallback: str = "Другие направления") -> str:
    blob = f"{title} {shorten(description, 400)}".lower()
    rules: list[tuple[str, str]] = [
        ("AI и автоматизация", r"нейросет|нейронн|\bai\b|ai-|llm|prompt|искусственн\w*\s+интеллект|машинн\w*\s+обучен|автоматизац"),
        ("IT и техподдержка", r"системн\w*\s+администратор|helpdesk|help desk|service desk|техническ\w*\s+поддерж|it[- ]специалист|администратор сети|\blinux\b|\bwindows\b|инфраструктур|серверн|devops|настройк\w*\s+рабоч"),
        ("Разработка и тестирование", r"разработчик|developer|программист|frontend|front[- ]?end|backend|back[- ]?end|\bqa\b|тестировщик|javascript|\bpython\b|веб[- ]?разработ|1с[- ]?разработ"),
        ("Аналитика", r"аналитик|\banalyst\b|бизнес[- ]?анализ|системн\w*\s+анализ|данных|\bdata\b|\bsql\b|\bbi\b"),
        ("Дизайн и медиа", r"дизайн|\bsmm\b|контент|видеомонтаж|motion|монтажёр|монтажер|графичес\w*\s+дизайн|ai[- ]?видео|редактор|копирайт"),
        ("Управление и администрирование", r"координатор|project assistant|project manager|руководител\w*\s+проект|офис[- ]?менеджер|администратор|помощник руководителя|ассистент|секретарь|делопроизвод"),
        ("Продажи и клиенты", r"продаж|менеджер по работ\w*\s+с\s+клиент|клиентск\w*\s+сервис|customer support|оператор чата|\bcall[- ]?центр|продавец|кассир|сопровождени\w*\s+клиент"),
        ("Производство и инженерия", r"инженер|техник|лаборант|оператор|\bотк\b|производств|наладчик|слесарь|электрик|механик|сборщик|рабоч\w*\s+|технолог|оборудован"),
    ]
    for name, pattern in rules:
        if re.search(pattern, blob, re.I):
            return name
    if fallback and fallback not in {"Широкий поиск", ""}:
        return fallback
    return "Другие направления"


def parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()

    def aware(dt: datetime | None) -> datetime | None:
        # Часть полей HH приходит без смещения. Приводим всё к aware,
        # чтобы сортировка не смешивала naive и aware datetime.
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    try:
        return aware(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})([+-]\d{2}):?(\d{2})", raw)
    if m:
        try:
            return aware(datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{m.group(3)}:{m.group(4)}"))
        except ValueError:
            pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    return None


def human_date(value: str | None, with_time: bool = False) -> str:
    dt = parse_iso_date(value)
    if not dt:
        return "—"
    return dt.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def content_hash(*parts: Any) -> str:
    payload = "\x1f".join(clean_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def alabuga_match(v: Any) -> bool:
    blob = " ".join([
        getattr(v, "title", ""), getattr(v, "company", ""),
        getattr(v, "address", ""), getattr(v, "city", ""),
        getattr(v, "description", ""),
    ]).lower()
    return "алабуга" in blob
