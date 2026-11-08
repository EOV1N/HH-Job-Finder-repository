"""Конфигурация приложения: пути, профиль поиска и сохраняемые настройки."""
from __future__ import annotations

import copy
import json
import os
import stat
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("HHF_DATA_DIR", APP_ROOT / "data")).expanduser().resolve()
DB_PATH = DATA_DIR / "jobs.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_DIR = DATA_DIR / "logs"
EXPORT_DIR = DATA_DIR / "exports"
REPORT_DIR = APP_ROOT / "reports"
SCREENSHOT_DIR = APP_ROOT / "screenshots"

for _p in (DATA_DIR, LOG_DIR, EXPORT_DIR, REPORT_DIR, SCREENSHOT_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# Идентификаторы регионов взяты из официального справочника /areas.
AREA_INFO: dict[str, dict[str, str]] = {
    "1641": {"name": "Набережные Челны", "type": "city"},
    "1633": {"name": "Елабуга", "type": "city"},
    "1624": {"name": "Республика Татарстан", "type": "region"},
}

EXPERIENCE_INFO: dict[str, str] = {
    "noExperience": "Без опыта",
    "between1And3": "От 1 года до 3 лет",
    "between3And6": "От 3 до 6 лет",
    "moreThan6": "Более 6 лет",
}

KEYWORD_GROUPS: dict[str, list[str]] = {
    "IT и техподдержка": [
        "Системный администратор", "IT-специалист", "Helpdesk", "Service Desk",
        "Техническая поддержка", "Специалист технической поддержки", "Linux",
        "Windows", "Администратор сети",
    ],
    "Разработка и тестирование": [
        "Python Developer", "Junior Backend Developer", "Frontend Developer",
        "JavaScript", "QA Engineer", "Тестировщик ПО", "Junior Developer",
    ],
    "AI и автоматизация": [
        "AI Specialist", "AI Engineer", "Специалист по нейросетям",
        "AI-контент", "Специалист по автоматизации", "Prompt Engineer",
    ],
    "Аналитика": [
        "Системный аналитик", "Бизнес-аналитик", "Junior Analyst", "Аналитик данных",
    ],
    "Управление и администрирование": [
        "Координатор проектов", "Project Assistant", "Junior Project Manager",
        "Администратор", "Офис-менеджер", "Помощник руководителя",
    ],
    "Продажи и клиенты": [
        "Менеджер по продажам", "Менеджер по работе с клиентами",
        "Специалист клиентского сервиса", "Customer Support", "Оператор чата",
        "Менеджер по сопровождению клиентов",
    ],
    "Дизайн и медиа": [
        "Видеомонтажёр", "Motion Designer", "Графический дизайнер",
        "Контент-менеджер", "SMM-специалист", "AI-видеопродакшн",
    ],
    "Производство и инженерия": [
        "Инженер", "Технический специалист", "Инженер технической поддержки",
        "Оператор оборудования", "Специалист ОТК", "Техник", "Лаборант",
    ],
}

CATEGORY_ORDER = [*KEYWORD_GROUPS.keys(), "Другие направления"]

# Категории профессиональных ролей из /professional_roles. Используются для
# широкого поиска, который находит вакансии вне заданных ключевых слов.
ROLE_CATEGORY_GROUPS: dict[str, list[str]] = {
    "IT и разработка": ["11", "4"],
    "Администрирование и офис": ["5", "3", "12", "14"],
    "Продажи и обслуживание": ["1", "2", "20"],
    "Маркетинг, медиа, творчество": ["6", "24"],
    "Производство и рабочие профессии": ["7", "17", "18", "8"],
    "Транспорт и логистика": ["10", "19"],
    "Наука, образование, медицина": ["25", "23"],
    "Другие сферы": ["27", "15", "16", "21", "9", "22", "13", "26"],
}

BROAD_QUERIES: list[tuple[str, str, int]] = [
    ("Все свежие вакансии в целевых городах", "", 2),
    ("Начинающий специалист / стажировка", '"без опыта" OR "стажёр" OR "стажер" OR "младший специалист"', 1),
    ("Офис, координация, помощники", '"администратор" OR "офис-менеджер" OR "координатор" OR "ассистент" OR "помощник"', 1),
    ("Клиенты и поддержка", '"поддержка" OR "клиентский сервис" OR "оператор чата" OR "call-центр"', 1),
    ("Технические и инженерные специальности", '"техник" OR "лаборант" OR "инженер" OR "наладчик" OR "ОТК"', 1),
    ("Производство и операторы", '"оператор" OR "оператор оборудования" OR "сборщик" OR "контролёр"', 1),
    ("Творчество и контент", '"дизайнер" OR "контент" OR "SMM" OR "видеомонтаж" OR "нейросети"', 1),
]

DEFAULT_RATES: dict[str, float] = {
    "RUR": 1.0, "RUB": 1.0, "USD": 0.0125, "EUR": 0.0108,
    "KZT": 5.5, "BYR": 0.036, "UAH": 0.55, "AZN": 0.0207,
    "GEL": 0.033, "KGS": 1.06, "UZS": 140.0,
}


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class Settings:
    # География. "alabuga" включает весь Татарстан ТОЛЬКО для запросов со словом
    # «Алабуга» и последующей проверкой адреса/работодателя на ОЭЗ.
    areas: dict[str, bool] = field(default_factory=lambda: {
        "1641": True, "1633": True, "alabuga": True,
    })
    experience: dict[str, bool] = field(default_factory=lambda: {
        "noExperience": True, "between1And3": True,
    })
    enabled_groups: dict[str, bool] = field(default_factory=lambda: {
        name: True for name in KEYWORD_GROUPS
    })
    custom_keywords: str = ""
    broad_enabled: bool = True
    role_categories_enabled: bool = True
    alabuga_enabled: bool = True

    search_period_days: int = 30
    pages_per_query: int = 2
    max_details_per_run: int = 140
    request_delay: float = 0.75
    max_concurrency: int = 3
    timeout_seconds: float = 20.0

    auto_refresh: bool = True
    refresh_minutes: int = 120
    allow_web_fallback: bool = True
    strict_max_experience: bool = True
    show_excluded: bool = False
    include_no_salary: bool = True
    only_target_cities: bool = True
    min_salary: int = 0

    # Официальный API HH: анонимный GET /vacancies в 2026 году отвечает 403.
    # Токен приложения/пользователя можно ввести в настройках.
    api_access_token: str = ""
    api_client_id: str = ""
    api_client_secret: str = ""
    api_token_expires_at: float = 0.0
    api_user_agent: str = "HHJobFinder/1.0 (contact: user@localhost)"
    prefer_api: bool = True

    @property
    def selected_area_ids(self) -> list[str]:
        ids = [k for k in ("1641", "1633") if self.areas.get(k, False)]
        return ids or ["1641", "1633"]

    @property
    def selected_experience_ids(self) -> list[str]:
        ids = [k for k in ("noExperience", "between1And3") if self.experience.get(k, False)]
        return ids or ["noExperience", "between1And3"]

    @property
    def selected_groups(self) -> list[str]:
        return [k for k in KEYWORD_GROUPS if self.enabled_groups.get(k, True)]

    def validate(self) -> None:
        self.search_period_days = int(max(1, min(90, self.search_period_days)))
        self.pages_per_query = int(max(1, min(10, self.pages_per_query)))
        self.max_details_per_run = int(max(0, min(1000, self.max_details_per_run)))
        self.request_delay = float(max(0.35, min(5.0, self.request_delay)))
        self.max_concurrency = int(max(1, min(6, self.max_concurrency)))
        self.timeout_seconds = float(max(5.0, min(60.0, self.timeout_seconds)))
        self.refresh_minutes = int(max(0, min(1440, self.refresh_minutes)))
        self.min_salary = int(max(0, min(1_000_000, self.min_salary)))
        if not self.api_user_agent.strip():
            self.api_user_agent = "HHJobFinder/1.0 (contact: user@localhost)"

    def save(self, path: Path | None = None) -> None:
        path = path or SETTINGS_PATH
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or SETTINGS_PATH
        obj = cls()
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                merged = _deep_merge(asdict(obj), saved)
                obj = cls(**{k: v for k, v in merged.items() if k in cls.__dataclass_fields__})
            except (OSError, ValueError, TypeError) as exc:
                # Не мешаем запуску из-за повреждённого файла настроек.
                import logging
                logging.getLogger(__name__).warning("Не удалось прочитать настройки: %s", exc)
        obj.validate()
        return obj
