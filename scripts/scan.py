#!/usr/bin/env python3
"""Headless-сбор реальных вакансий без запуска GUI.

Пример:
    python scripts/scan.py --pages 2 --details 160 --delay 0.7
    python scripts/scan.py --enrich-only 200
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Обработка --data-dir до импорта config.py.
argv = sys.argv[1:]
for i, arg in enumerate(argv):
    if arg == "--data-dir" and i + 1 < len(argv):
        os.environ["HHF_DATA_DIR"] = str(Path(argv[i + 1]).expanduser().resolve())
    elif arg.startswith("--data-dir="):
        os.environ["HHF_DATA_DIR"] = str(Path(arg.split("=", 1)[1]).expanduser().resolve())

from hhfinder.collector import collect  # noqa: E402
from hhfinder.config import DB_PATH, LOG_DIR, Settings  # noqa: E402
from hhfinder.db import Database  # noqa: E402
from hhfinder.sources.base import RateLimiter  # noqa: E402
from hhfinder.sources.hh_api import HHAPISource  # noqa: E402
from hhfinder.sources.hh_web import HHWebSource  # noqa: E402
from hhfinder.scoring import score_vacancy  # noqa: E402
from hhfinder.utils import (  # noqa: E402
    classify_category, infer_required_years, monthly_rub_amount,
)


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "scan.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


async def enrich_only(db: Database, settings: Settings, limit: int) -> dict:
    """Догружает описания для уже сохранённых вакансий без повторного поиска."""
    api_limiter = RateLimiter(settings.request_delay)
    # Детальные страницы требуют более медленного режима, чем поисковая выдача.
    detail_limiter = RateLimiter(max(1.25, settings.request_delay * 1.8))
    api = HHAPISource(settings, api_limiter)
    web = HHWebSource(settings, detail_limiter)
    rates = await api.currency_rates()
    items = db.need_details(limit)
    semaphore = asyncio.Semaphore(min(2, settings.max_concurrency))
    captcha_event = asyncio.Event()
    done = errors = changed = skipped = 0

    async def one(item):
        nonlocal done, errors, changed, skipped
        if captcha_event.is_set():
            skipped += 1
            return
        async with semaphore:
            if captcha_event.is_set():
                skipped += 1
                return
            try:
                detail = await web.fetch_detail(item.id)
                if detail is None:
                    errors += 1
                    return
                base = db.get_vacancy(item.id) or item
                base.merge(detail, keep_search=True)
                base.category = classify_category(base.title, base.description, base.category)
                inferred = infer_required_years(
                    " ".join([base.requirements, base.description]), base.experience_id,
                )
                base.required_years = inferred if inferred is not None else detail.required_years
                base.salary_monthly_rub = monthly_rub_amount(
                    base.salary_from, base.salary_to, base.currency, base.salary_frequency, rates,
                )
                score_vacancy(base, rates, settings.strict_max_experience)
                has_changes, _ = db.upsert_detail(base)
                done += 1
                changed += int(has_changes)
            except Exception as exc:
                errors += 1
                text = str(exc)
                if "капча" in text.lower() or "captcha" in text.lower():
                    captcha_event.set()
                    logging.warning("HH запросил капчу; догрузка остановлена до следующего запуска")
                else:
                    logging.warning("Ошибка обогащения %s: %s", item.id, text)

    try:
        tasks = [asyncio.create_task(one(v)) for v in items]
        for idx, future in enumerate(asyncio.as_completed(tasks), start=1):
            await future
            if idx % 10 == 0 or idx == len(tasks):
                print(f"Описания: {done} загружено / {idx} проверено, ошибок: {errors}", flush=True)
    finally:
        await api.aclose()
        await web.aclose()
    return {
        "requested": len(items), "done": done, "changed": changed,
        "errors": errors, "skipped_after_captcha": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Сбор вакансий HH в SQLite")
    parser.add_argument("--data-dir", help="Каталог с БД и настройками")
    parser.add_argument("--pages", type=int, help="Страниц на поисковый запрос")
    parser.add_argument("--details", type=int, help="Максимум описаний за запуск")
    parser.add_argument("--delay", type=float, help="Пауза между HTTP-запросами, сек")
    parser.add_argument("--concurrency", type=int, help="Максимум параллельных запросов")
    parser.add_argument("--period", type=int, help="Период поиска в днях")
    parser.add_argument("--enrich-only", type=int, metavar="N", help="Только догрузить N описаний без поиска")
    args = parser.parse_args()
    setup_logging()

    settings = Settings.load()
    if args.pages is not None:
        settings.pages_per_query = args.pages
    if args.details is not None:
        settings.max_details_per_run = args.details
    if args.delay is not None:
        settings.request_delay = args.delay
    if args.concurrency is not None:
        settings.max_concurrency = args.concurrency
    if args.period is not None:
        settings.search_period_days = args.period
    settings.validate()
    db = Database(DB_PATH)

    if args.enrich_only is not None:
        result = asyncio.run(enrich_only(db, settings, args.enrich_only))
        print(f"Догрузка завершена: {result}", flush=True)
        return 0 if result["errors"] < max(1, result["requested"] // 2) else 1

    stop = threading.Event()

    def progress(message: str, done: int, total: int) -> None:
        print(f"[{done}/{total}] {message}", flush=True)

    started = time.monotonic()
    try:
        summary = asyncio.run(collect(db, settings, progress, stop))
    except KeyboardInterrupt:
        print("Прервано пользователем", file=sys.stderr)
        return 130
    except Exception as exc:
        logging.exception("Сбор завершился ошибкой")
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    print("\n=== ИТОГ ===")
    print(summary.headline())
    print(f"Источник: {summary.source}; страниц: {summary.pages_done}/{summary.queries_total} запросов; "
          f"описаний: {summary.details_done}; время: {time.monotonic() - started:.1f} с")
    print(f"Статус API: {summary.api_status}")
    if summary.errors:
        print(f"Ошибки ({len(summary.errors)}):", *summary.errors[:5], sep="\n - ")
    return 1 if summary.errors and not summary.unique else 0


if __name__ == "__main__":
    raise SystemExit(main())
