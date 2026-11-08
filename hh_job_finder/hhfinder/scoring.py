"""Детерминированная оценка соответствия вакансии профилю соискателя.

Это не LLM и не «магический» рейтинг: каждый балл объясним и хранится в БД
в поле score_factors. Оценка намеренно conservative — высокая зарплата сама по
себе не делает непрофильную вакансию подходящей.
"""
from __future__ import annotations

import re
from typing import Any

from .models import Vacancy
from .utils import (
    classify_category,
    infer_required_years,
    monthly_rub_amount,
    shorten,
)

PROFILE_SUMMARY = (
    "Бакалавриат «Информационные системы и технологии», небольшой практический "
    "опыт IT-специалистом на стажировке, Linux/Windows/Docker/Git/SQL/Python, "
    "API, БД, автоматизация, нейросети, рабочие места, сети, удалённое "
    "администрирование, изучает веб-разработку."
)

# Навык -> (регулярное выражение, вес). Веса небольшие, сумма ограничена.
SKILLS: dict[str, tuple[str, float]] = {
    "Python": (r"\bpython\b|питон", 5),
    "Linux": (r"\blinux\b|линукс", 4),
    "Windows": (r"\bwindows\b", 2),
    "Docker": (r"\bdocker\b|контейнер", 3),
    "Git": (r"\bgit\b|gitlab|github", 2),
    "SQL/БД": (r"\bsql\b|баз\w*\s+данн|postgres|mysql|sqlite|\bбд\b", 3),
    "API/интеграции": (r"\bapi\b|rest|интеграц", 3),
    "Автоматизация": (r"автоматизац|скрипт|robot|rpa", 4),
    "AI/нейросети": (r"нейросет|\bai\b|llm|prompt|искусственн\w*\s+интеллект|chatgpt", 4),
    "Техподдержка": (r"техническ\w*\s+поддерж|helpdesk|help desk|service desk|саппорт|support", 5),
    "Сети/инфраструктура": (r"\bсеть\b|сетев|администрир|рабоч\w*\s+мест|инфраструктур|серверн|удалённ\w*\s+администрир", 3),
    "Веб-разработка": (r"\bhtml\b|\bcss\b|javascript|frontend|front[- ]?end|backend|back[- ]?end|веб[- ]?разработ", 3),
    "Тестирование": (r"\bqa\b|тестирован|тестировщик|autotest", 2),
}

ROLE_FIT: dict[str, int] = {
    "IT и техподдержка": 15,
    "Разработка и тестирование": 14,
    "AI и автоматизация": 14,
    "Аналитика": 11,
    "Управление и администрирование": 7,
    "Продажи и клиенты": 5,
    "Дизайн и медиа": 6,
    "Производство и инженерия": 6,
    "Другие направления": 2,
}

MANUAL_ROLE_RE = re.compile(
    r"курьер|грузчик|разнорабоч|подсобн|уборщик|дворник|бариста|официант|продавец|"
    r"кассир|упаковщик|комплектовщик|сортировщик|мойщик|посудомой|охранник|вахтёр|"
    r"рабоч\w*\s+(?:по|на)|станочник|сборщик|оператор\s+(?:производственн|станков|линии)",
    re.I,
)
SENIOR_RE = re.compile(
    r"\bsenior\b|\blead\b|ведущ\w*\s+(?:специалист|разработчик|инженер)|руководитель|"
    r"начальник|\bmiddle\b|\bhead\b|директор|архитектор", re.I,
)
JUNIOR_RE = re.compile(
    r"\bjunior\b|\bjun\b|стажёр|стажер|младш\w*\s+специалист|начинающ\w*|"
    r"без опыта|обучени\w*\s+на\s+месте", re.I,
)
GROWTH_RE = re.compile(r"обучен|наставник|карьерн\w*\s+рост|развити|ментор|стажировк|повышени\w*\s+квалификац", re.I)
BAD_CONDITIONS_RE = re.compile(r"вахтов|ночн\w*\s+смен|вредн\w*\s+производ|разъездн|релокац|переезд|командировк", re.I)
GOOD_CONDITIONS_RE = re.compile(r"официальн\w*\s+трудоустройств|трудов\w*\s+договор|\b5/2\b|пятиднев|дмс|гибк\w*\s+график", re.I)


def _matched_skills(text: str, title: str) -> tuple[list[str], float]:
    found: list[str] = []
    total = 0.0
    for name, (pattern, weight) in SKILLS.items():
        if re.search(pattern, text, re.I):
            found.append(name)
            total += weight
            if re.search(pattern, title, re.I):
                total += 0.5
    return found, min(22.0, total)


def _salary_points(v: Vacancy, rates: dict[str, float]) -> tuple[float, str]:
    monthly = v.salary_monthly_rub
    if monthly is None and (v.salary_from is not None or v.salary_to is not None):
        monthly = monthly_rub_amount(
            v.salary_from, v.salary_to, v.currency, v.salary_frequency, rates,
        )
        v.salary_monthly_rub = monthly
    if monthly is None or monthly <= 0:
        return 0.0, "зарплата не указана"
    if monthly >= 100_000:
        return 12.0, f"доход около {int(monthly):,} ₽/мес".replace(",", "\u202f")
    if monthly >= 70_000:
        return 9.0, f"доход около {int(monthly):,} ₽/мес".replace(",", "\u202f")
    if monthly >= 50_000:
        return 7.0, f"доход около {int(monthly):,} ₽/мес".replace(",", "\u202f")
    if monthly >= 35_000:
        return 4.0, f"доход около {int(monthly):,} ₽/мес".replace(",", "\u202f")
    return 2.0, f"доход около {int(monthly):,} ₽/мес".replace(",", "\u202f")


def _realism(v: Vacancy, inferred_years: int | None) -> tuple[float, list[str], list[str]]:
    points = 0.0
    positives: list[str] = []
    negatives: list[str] = []
    if v.experience_id == "noExperience":
        points += 14
        positives.append("официально «без опыта»")
    elif v.experience_id == "between1And3":
        points += 7
        positives.append("требуется опыт 1–3 года")
    elif v.experience_id in {"between3And6", "moreThan6"}:
        points -= 18
        negatives.append("в метаданных указан опыт более 3 лет")
    else:
        points += 3

    if inferred_years == 0:
        points += 4
        positives.append("в описании подтверждено «без опыта»")
    elif inferred_years in (1, 2):
        points += 2
    elif inferred_years == 3:
        pass
    elif inferred_years is not None and inferred_years > 3:
        points -= 22
        negatives.append(f"в описании фактически требуется от {inferred_years} лет")

    if JUNIOR_RE.search(f"{v.title} {shorten(v.description, 300)}"):
        points += 5
        positives.append("есть признаки начальной позиции/стажировки")
    if SENIOR_RE.search(v.title):
        points -= 12
        negatives.append("название указывает на уровень выше junior")
    return min(16.0, points), positives, negatives


def _conditions(v: Vacancy) -> tuple[float, list[str], list[str]]:
    blob = " ".join([
        v.work_format, v.employment, v.schedule, v.responsibilities,
        v.requirements, shorten(v.description, 1000),
    ])
    points = 0.0
    positives: list[str] = []
    negatives: list[str] = []
    if v.work_format == "Удалённо":
        points += 4
        positives.append("удалённый формат")
    elif v.work_format == "Гибрид":
        points += 3
        positives.append("гибридный формат")
    elif v.work_format == "Офис":
        points += 1
    if GROWTH_RE.search(blob):
        points += 4
        positives.append("есть обучение/развитие")
    if GOOD_CONDITIONS_RE.search(blob):
        points += 3
        positives.append("понятные условия занятости")
    if BAD_CONDITIONS_RE.search(blob):
        points -= 7
        negatives.append("есть вахта/ночные смены/релокация или разъезды")
    if v.work_format == "Разъездной":
        points -= 3
    return max(-10.0, min(8.0, points)), positives, negatives


def score_vacancy(
    vacancy: Vacancy,
    rates: dict[str, float] | None = None,
    strict_max_experience: bool = True,
) -> Vacancy:
    rates = rates or {"RUR": 1.0}
    v = vacancy
    if v.category in {"", "Широкий поиск"}:
        v.category = classify_category(v.title, v.description, v.category)
    if v.required_years is None and v.description:
        v.required_years = infer_required_years(
            " ".join([v.requirements, v.description]), v.experience_id,
        )

    blob = " ".join([
        v.title, v.company, v.description, v.responsibilities,
        v.requirements, " ".join(v.key_skills), " ".join(v.labels),
    ])
    matched, skill_points = _matched_skills(blob, v.title)
    role_points = float(ROLE_FIT.get(v.category, 3))
    manual = bool(MANUAL_ROLE_RE.search(f"{v.title} {shorten(v.description, 200)}"))
    if manual:
        role_points = min(role_points, 2.0)

    realism_points, realism_pos, realism_neg = _realism(v, v.required_years)
    salary_points, salary_text = _salary_points(v, rates)
    condition_points, condition_pos, condition_neg = _conditions(v)

    city = (v.city or "").lower()
    if any(x in city for x in ("челн", "елабуг", "алабуга")):
        location_points = 4.0
    elif city in {"", "не указан"}:
        location_points = 0.0
    elif "удал" in city:
        location_points = 2.0
    else:
        location_points = -10.0

    alignment_penalty = 0.0
    core_categories = {
        "IT и техподдержка", "Разработка и тестирование",
        "AI и автоматизация", "Аналитика",
    }
    if manual:
        alignment_penalty -= 12.0
    elif skill_points < 4 and v.category not in core_categories:
        # Высокая зарплата не должна превращать непрофильную вакансию
        # (HR, массовые продажи, курьер) в «лучшее совпадение».
        alignment_penalty -= 12.0
    elif v.category == "Продажи и клиенты" and not re.search(r"it|техн|support|поддерж", blob, re.I):
        alignment_penalty -= 6.0

    factors: dict[str, float] = {
        "base": 10.0,
        "skills": round(skill_points, 1),
        "role": round(role_points, 1),
        "realism": round(realism_points, 1),
        "salary": round(salary_points, 1),
        "conditions": round(condition_points, 1),
        "location": round(location_points, 1),
        "alignment": round(alignment_penalty, 1),
    }
    total = sum(factors.values())
    v.score = float(max(0, min(100, round(total))))
    v.score_factors = factors

    positives: list[str] = []
    if matched:
        positives.append("совпали навыки: " + ", ".join(matched[:5]))
    positives.extend(realism_pos[:2])
    positives.extend(condition_pos[:1])
    salary_neg = [] if salary_points > 0 else ["зарплата не указана"]
    negatives = [*realism_neg, *condition_neg, *salary_neg]
    if alignment_penalty <= -10:
        negatives.append("профильная подготовка почти не используется")
    if v.experience_id == "between1And3" and v.required_years is None:
        negatives.append("требуется коммерческий опыт 1–3 года")

    # Исключение только по ФАКТИЧЕСКОМУ опыту >3 лет, а не по отсутствию Junior.
    excluded = False
    reason = ""
    if v.experience_id in {"between3And6", "moreThan6"}:
        excluded, reason = True, "В метаданных HH указан опыт более 3 лет"
    elif v.required_years is not None and v.required_years > 3:
        excluded = True
        reason = f"В описании требуется опыт от {v.required_years} лет"
    if strict_max_experience and excluded:
        v.excluded = True
        v.exclusion_reason = reason
        v.score = min(v.score, 15)
        negatives.insert(0, reason)
    else:
        v.excluded = False
        v.exclusion_reason = ""

    summary = []
    if positives:
        summary.append("; ".join(positives[:3]))
    if salary_points:
        summary.append(salary_text)
    if negatives:
        summary.append("минусы: " + "; ".join(negatives[:3]))
    explanation = ". ".join(x for x in summary if x)
    if explanation:
        explanation += "."
    v.score_explanation = shorten(explanation, 420)
    return v


def preliminary_score(v: Vacancy, rates: dict[str, float], strict: bool = True) -> Vacancy:
    """Оценка по карточке поиска до загрузки полного описания."""
    return score_vacancy(v, rates, strict)
