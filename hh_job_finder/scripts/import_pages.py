#!/usr/bin/env python3
"""Импорт HTML-страниц вакансий, сохранённых пользователем в браузере.

Это легальный способ догрузить описания, если hh.ru временно показывает капчу
для автоматических запросов. Страницы читаются локально, сеть не используется.

    python scripts/import_pages.py ~/Downloads/vacancy_138256023.html
    python scripts/import_pages.py ~/Downloads/hh_pages/*.html
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
argv = sys.argv[1:]
for i, arg in enumerate(argv):
    if arg == "--data-dir" and i + 1 < len(argv):
        os.environ["HHF_DATA_DIR"] = str(Path(argv[i + 1]).expanduser().resolve())
    elif arg.startswith("--data-dir="):
        os.environ["HHF_DATA_DIR"] = str(Path(arg.split("=", 1)[1]).expanduser().resolve())

from hhfinder.config import DB_PATH, DEFAULT_RATES, Settings  # noqa: E402
from hhfinder.db import Database  # noqa: E402
from hhfinder.scoring import score_vacancy  # noqa: E402
from hhfinder.sources.hh_web import HHWebSource  # noqa: E402
from hhfinder.utils import classify_category, monthly_rub_amount  # noqa: E402


def vacancy_id(path: Path, html: str) -> str | None:
    m = re.search(r"(\d{6,})", path.stem)
    if m:
        return m.group(1)
    for pattern in (
        r'href=["\']https?://hh\.ru/vacancy/(\d+)',
        r'data-vacancy-id=["\'](\d+)',
        r'"identifier"\s*:\s*\{[^}]*"value"\s*:\s*(\d+)',
    ):
        m = re.search(pattern, html, re.I)
        if m:
            return m.group(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт сохранённых HTML-страниц вакансий HH")
    parser.add_argument("paths", nargs="+", help="Файлы или glob-шаблоны HTML")
    parser.add_argument("--data-dir", help="Каталог с БД")
    args = parser.parse_args()

    files: list[Path] = []
    for pattern in args.paths:
        matches = glob.glob(str(Path(pattern).expanduser()))
        files.extend(Path(m).resolve() for m in matches)
    files = [p for p in dict.fromkeys(files) if p.is_file()]
    if not files:
        print("HTML-файлы не найдены", file=sys.stderr)
        return 1

    settings = Settings.load()
    db = Database(DB_PATH)
    parser_source = object.__new__(HHWebSource)
    parser_source.name = "hh_web_import"
    added = updated = skipped = 0

    for path in files:
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
            vid = vacancy_id(path, html)
            if not vid:
                skipped += 1
                print(f"Пропущен {path.name}: не найден ID вакансии")
                continue
            v = parser_source._parse_detail(vid, html)
            if not v.title:
                skipped += 1
                print(f"Пропущен {path.name}: не удалось разобрать заголовок")
                continue
            existing = db.get_vacancy(vid)
            if existing:
                existing.merge(v, keep_search=True)
                if not existing.search_tags:
                    existing.search_tags = ["Импорт сохранённой страницы"]
                v = existing
            else:
                v.search_tags = ["Импорт сохранённой страницы"]
            v.category = classify_category(v.title, v.description, v.category)
            v.salary_monthly_rub = monthly_rub_amount(
                v.salary_from, v.salary_to, v.currency, v.salary_frequency, DEFAULT_RATES,
            )
            score_vacancy(v, DEFAULT_RATES, settings.strict_max_experience)
            db.upsert_detail(v)
            if existing:
                updated += 1
            else:
                added += 1
        except Exception as exc:
            skipped += 1
            print(f"Ошибка {path.name}: {exc}", file=sys.stderr)
    print(f"Импорт завершён: добавлено {added}, обновлено {updated}, пропущено {skipped}")
    return 0 if added or updated else 1


if __name__ == "__main__":
    raise SystemExit(main())
