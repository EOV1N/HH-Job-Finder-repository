"""Оркестратор сбора: API → резервный режим → дедупликация → обогащение → БД."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import fields
from typing import Any, Callable

from .config import DEFAULT_RATES, Settings
from .db import Database
from .models import RunSummary, Vacancy
from .queries import SearchQuery, build_queries
from .scoring import score_vacancy
from .sources.base import AuthRequired, RateLimiter, SourceError
from .sources.hh_api import HHAPISource
from .sources.hh_web import HHWebSource
from .utils import (
    alabuga_match,
    classify_category,
    clean_text,
    infer_required_years,
    monthly_rub_amount,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int, int], None] | None


class CollectionCancelled(Exception):
    pass


def _merge_partial(a: Vacancy, b: Vacancy) -> Vacancy:
    """Объединяет две карточки одной вакансии из разных запросов."""
    a.search_tags = list(dict.fromkeys([*a.search_tags, *b.search_tags]))
    a.labels = list(dict.fromkeys([*a.labels, *b.labels]))
    if b.category not in {"", "Широкий поиск", "Другие направления"} and a.category in {"", "Широкий поиск", "Другие направления"}:
        a.category = b.category
    skip = {
        "id", "search_tags", "labels", "category", "is_favorite", "is_new",
        "first_seen_at", "last_seen_at", "last_changed_at", "score",
        "score_explanation", "score_factors", "excluded", "exclusion_reason",
    }
    for f in fields(Vacancy):
        if f.name in skip:
            continue
        old = getattr(a, f.name)
        new = getattr(b, f.name)
        if old in (None, "", [], {}, 0, 0.0, False) and new not in (None, "", [], {}):
            setattr(a, f.name, new)
    if a.no_salary and not b.no_salary:
        for key in ("salary_from", "salary_to", "currency", "salary_display", "gross", "salary_frequency"):
            setattr(a, key, getattr(b, key))
        a.no_salary = False
    return a


def _prepare_card(v: Vacancy, query: SearchQuery, rates: dict[str, float], strict: bool) -> Vacancy:
    v.source = v.source or "hh_web"
    v.search_tags = [query.label]
    v.category = classify_category(v.title, "", query.category)
    v.salary_monthly_rub = monthly_rub_amount(
        v.salary_from, v.salary_to, v.currency, v.salary_frequency, rates,
    )
    v.url = v.url or f"https://hh.ru/vacancy/{v.id}"
    return score_vacancy(v, rates, strict)


async def collect(
    db: Database,
    settings: Settings,
    progress: ProgressCallback = None,
    stop_event: threading.Event | None = None,
) -> RunSummary:
    started = time.monotonic()
    limiter = RateLimiter(settings.request_delay)
    api = HHAPISource(settings, limiter)
    web: HHWebSource | None = None
    detail_source: HHWebSource | None = None
    source: HHAPISource | HHWebSource | None = None
    summary = RunSummary()
    summary.run_id = db.create_run("unknown", "инициализация", 0)
    api_status = ""
    rates: dict[str, float] = dict(DEFAULT_RATES)
    roles: dict[str, list[str]] = {}
    queries: list[SearchQuery] = []

    def emit(message: str, done: int, total: int) -> None:
        if progress:
            progress(message, done, max(1, total))

    def stopped() -> bool:
        return bool(stop_event and stop_event.is_set())

    def check_stop() -> None:
        if stopped():
            raise CollectionCancelled("Сбор остановлен пользователем")

    try:
        # Справочники HH доступны анонимно даже когда /vacancies закрыт.
        try:
            rates = await api.currency_rates()
            roles = await api.professional_roles()
            api_status = "Справочники API доступны"
        except Exception as exc:
            logger.warning("Справочники HH недоступны, используются значения по умолчанию: %s", exc)
            api_status = f"Справочники API недоступны: {exc}"

        if settings.prefer_api:
            try:
                test = await api.test()
                if test.get("ok"):
                    source = api
                    summary.source = "hh_api"
                    api_status = f"{api_status}; {test.get('message')}"
                else:
                    api_status = f"{api_status}; {test.get('message')}"
            except (AuthRequired, SourceError) as exc:
                api_status = f"{api_status}; {exc}"
        else:
            api_status = f"{api_status}; основной источник явно отключён в настройках"

        if source is None:
            if not settings.allow_web_fallback:
                raise SourceError(
                    "Официальный /vacancies недоступен, а резервный режим hh.ru отключён. "
                    "Добавьте OAuth-токен или включите резервный режим в настройках."
                )
            web = HHWebSource(settings, limiter)
            source = web
            summary.source = "hh_web"
            api_status += "; включён щадящий резервный режим публичных страниц hh.ru"

        summary.api_status = api_status
        queries = build_queries(settings, roles)
        summary.queries_total = len(queries)
        # Обновим исходные поля запуска сейчас, чтобы история была информативной.
        from contextlib import closing
        with closing(db._connect()) as conn, conn:
            conn.execute(
                "UPDATE search_runs SET source=?, api_status=?, queries_total=? WHERE id=?",
                (summary.source, api_status, len(queries), summary.run_id),
            )

        page_jobs: list[tuple[int, SearchQuery, int]] = [
            (qi, q, page) for qi, q in enumerate(queries) for page in range(q.pages)
        ]
        emit("Поиск вакансий", 0, len(page_jobs))
        semaphore = asyncio.Semaphore(settings.max_concurrency)
        query_found: dict[int, int] = {i: 0 for i in range(len(queries))}
        query_errors: dict[int, list[str]] = {i: [] for i in range(len(queries))}
        unique: dict[str, Vacancy] = {}
        pages_done = 0

        async def fetch_page(index: int, query: SearchQuery, page: int) -> tuple[int, list[Vacancy], str]:
            async with semaphore:
                check_stop()
                try:
                    items = await source.search(query, page)  # type: ignore[union-attr]
                    prepared: list[Vacancy] = []
                    for item in items:
                        if not item.id:
                            continue
                        if query.alabuga_only and not alabuga_match(item):
                            continue
                        prepared.append(_prepare_card(item, query, rates, settings.strict_max_experience))
                    return index, prepared, ""
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Ошибка запроса «%s», страница %s: %s", query.label, page, exc)
                    return index, [], str(exc)

        tasks = [asyncio.create_task(fetch_page(qi, q, p)) for qi, q, p in page_jobs]

        try:
            for future in asyncio.as_completed(tasks):
                index, items, error = await future
                check_stop()
                pages_done += 1
                summary.pages_done = pages_done
                summary.found += len(items)
                if error:
                    query_errors[index].append(error)
                    if len(summary.errors) < 20:
                        summary.errors.append(error[:200])
                else:
                    query_found[index] += len(items)
                for item in items:
                    if item.id in unique:
                        _merge_partial(unique[item.id], item)
                    else:
                        unique[item.id] = item
                if pages_done % 5 == 0 or pages_done == len(tasks):
                    emit(
                        f"Поиск: {pages_done}/{len(tasks)} страниц, уникальных: {len(unique)}",
                        pages_done, len(tasks),
                    )
        except (CollectionCancelled, asyncio.CancelledError):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        # Логируем историю поисковых запросов.
        for i, query in enumerate(queries):
            db.log_query(
                summary.run_id, query, query_found[i],
                query.pages, "; ".join(query_errors[i])[:500],
            )

        # Пересчитываем оценку после объединения карточек и сохраняем.
        new_count = 0
        for v in unique.values():
            v.salary_monthly_rub = monthly_rub_amount(
                v.salary_from, v.salary_to, v.currency, v.salary_frequency, rates,
            )
            score_vacancy(v, rates, settings.strict_max_experience)
            if db.upsert_partial(v):
                new_count += 1
        summary.unique = len(unique)
        summary.new_count = new_count
        emit("Сохранение и загрузка описаний", 0, 1)

        need = db.need_details(settings.max_details_per_run)
        if need:
            # Детальные страницы hh.ru чувствительнее к частоте запросов, чем поисковая
            # выдача. Используем отдельный медленный лимитер и не более 2 потоков.
            if web is not None:
                detail_limiter = RateLimiter(max(1.25, settings.request_delay * 1.8))
                detail_source = HHWebSource(settings, detail_limiter)
                active_detail_source: HHAPISource | HHWebSource = detail_source
                detail_concurrency = min(2, settings.max_concurrency)
            else:
                active_detail_source = source  # type: ignore[assignment]
                detail_concurrency = settings.max_concurrency
            detail_sem = asyncio.Semaphore(detail_concurrency)
            captcha_event = asyncio.Event()

            async def enrich_one(item: Vacancy) -> tuple[bool, bool, int, str, bool]:
                # success, changed, change_count, error, skipped_after_captcha
                if captcha_event.is_set():
                    return False, False, 0, "", True
                async with detail_sem:
                    if captcha_event.is_set():
                        return False, False, 0, "", True
                    check_stop()
                    try:
                        detail = await active_detail_source.fetch_detail(item.id)
                        if detail is None:
                            return False, False, 0, "вакансия недоступна", False
                        base = db.get_vacancy(item.id) or item
                        base.merge(detail, keep_search=True)
                        base.category = classify_category(base.title, base.description, base.category)
                        inferred_years = infer_required_years(
                            " ".join([base.requirements, base.description]), base.experience_id,
                        )
                        base.required_years = inferred_years if inferred_years is not None else detail.required_years
                        base.salary_monthly_rub = monthly_rub_amount(
                            base.salary_from, base.salary_to, base.currency,
                            base.salary_frequency, rates,
                        )
                        score_vacancy(base, rates, settings.strict_max_experience)
                        changed, change_count = db.upsert_detail(base)
                        return True, changed, change_count, "", False
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        error = str(exc)
                        if "капча" in error.lower() or "captcha" in error.lower():
                            captcha_event.set()
                            summary.captcha_stopped = True
                            logger.warning("HH запросил капчу; остальные описания будут догружены позже")
                        else:
                            logger.warning("Не удалось загрузить описание %s: %s", item.id, error)
                        return False, False, 0, error, False

            detail_tasks = [asyncio.create_task(enrich_one(v)) for v in need]
            processed = 0
            try:
                for future in asyncio.as_completed(detail_tasks):
                    success, changed, change_count, error, skipped = await future
                    check_stop()
                    processed += 1
                    if success:
                        summary.details_done += 1
                        if changed:
                            summary.updated_count += 1
                        summary.changes_count += change_count
                    elif not skipped:
                        summary.detail_errors += 1
                        if error and len(summary.errors) < 20:
                            summary.errors.append(error[:200])
                    if processed % 5 == 0 or processed == len(detail_tasks):
                        emit(
                            f"Описания: {summary.details_done} загружено, ошибок {summary.detail_errors} "
                            f"/ проверено {processed}",
                            processed, len(detail_tasks),
                        )
            except (CollectionCancelled, asyncio.CancelledError):
                for task in detail_tasks:
                    task.cancel()
                await asyncio.gather(*detail_tasks, return_exceptions=True)
                raise
            if summary.captcha_stopped:
                api_status += "; HH запросил капчу — оставшиеся описания будут догружены при следующем запуске"
                summary.api_status = api_status

        summary.duration_seconds = round(time.monotonic() - started, 2)
        db.finish_run(summary.run_id, summary, "ok")
        emit(summary.headline(), 1, 1)
        return summary

    except (CollectionCancelled, asyncio.CancelledError) as exc:
        summary.cancelled = True
        summary.duration_seconds = round(time.monotonic() - started, 2)
        summary.errors.append("Сбор остановлен пользователем")
        db.finish_run(summary.run_id, summary, "cancelled")
        logger.info("Сбор вакансий остановлен: %s", exc)
        return summary
    except Exception as exc:
        summary.duration_seconds = round(time.monotonic() - started, 2)
        summary.errors.append(str(exc))
        db.finish_run(summary.run_id, summary, "failed")
        logger.exception("Сбор вакансий завершился ошибкой")
        raise
    finally:
        sources_to_close = [api]
        if web is not None:
            sources_to_close.append(web)
        if detail_source is not None:
            sources_to_close.append(detail_source)
        for src in sources_to_close:
            try:
                await src.aclose()
            except Exception as exc:
                logger.debug("Ошибка при закрытии HTTP-клиента: %s", exc)
