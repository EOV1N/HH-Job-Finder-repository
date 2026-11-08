"""SQLite-хранилище: вакансии, история запросов, избранное и изменения."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import fields
from pathlib import Path
from typing import Any

from .config import DB_PATH
from .models import Vacancy
from .utils import content_hash, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS vacancies (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    company TEXT DEFAULT '',
    employer_id TEXT,
    salary_from REAL,
    salary_to REAL,
    currency TEXT,
    salary_display TEXT DEFAULT '',
    gross INTEGER,
    salary_frequency TEXT DEFAULT '',
    salary_monthly_rub REAL,
    no_salary INTEGER DEFAULT 1,
    city TEXT DEFAULT '',
    address TEXT DEFAULT '',
    experience TEXT DEFAULT '',
    experience_id TEXT DEFAULT '',
    required_years INTEGER,
    work_format TEXT DEFAULT '',
    employment TEXT DEFAULT '',
    schedule TEXT DEFAULT '',
    description TEXT DEFAULT '',
    responsibilities TEXT DEFAULT '',
    requirements TEXT DEFAULT '',
    key_skills TEXT DEFAULT '[]',
    labels TEXT DEFAULT '[]',
    published_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    updated_at_source TEXT DEFAULT 'published_fallback',
    url TEXT DEFAULT '',
    category TEXT DEFAULT 'Другие направления',
    search_tags TEXT DEFAULT '[]',
    score REAL DEFAULT 0,
    score_explanation TEXT DEFAULT '',
    score_factors TEXT DEFAULT '{}',
    is_favorite INTEGER DEFAULT 0,
    is_new INTEGER DEFAULT 0,
    enriched INTEGER DEFAULT 0,
    excluded INTEGER DEFAULT 0,
    exclusion_reason TEXT DEFAULT '',
    first_seen_at TEXT DEFAULT '',
    last_seen_at TEXT DEFAULT '',
    last_changed_at TEXT DEFAULT '',
    content_hash TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vacancies_score ON vacancies(score DESC);
CREATE INDEX IF NOT EXISTS idx_vacancies_published ON vacancies(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_vacancies_category ON vacancies(category);
CREATE INDEX IF NOT EXISTS idx_vacancies_city ON vacancies(city);
CREATE INDEX IF NOT EXISTS idx_vacancies_new ON vacancies(is_new);
CREATE INDEX IF NOT EXISTS idx_vacancies_enriched ON vacancies(enriched);

CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source TEXT DEFAULT '',
    api_status TEXT DEFAULT '',
    status TEXT DEFAULT 'running',
    queries_total INTEGER DEFAULT 0,
    pages_done INTEGER DEFAULT 0,
    found INTEGER DEFAULT 0,
    unique_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    changes_count INTEGER DEFAULT 0,
    details_done INTEGER DEFAULT 0,
    errors TEXT DEFAULT '[]',
    duration_seconds REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    params TEXT DEFAULT '{}',
    found INTEGER DEFAULT 0,
    pages INTEGER DEFAULT 0,
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    FOREIGN KEY (run_id) REFERENCES search_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_queries_run ON search_queries(run_id);

CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_changes_vacancy ON changes(vacancy_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
"""

SQL_TYPES = {
    "float": "REAL", "int": "INTEGER", "bool": "INTEGER",
    "str": "TEXT", "list": "TEXT", "dict": "TEXT",
}


def _sql_type(py_type: str) -> str:
    for key, sql in SQL_TYPES.items():
        if key in py_type.lower():
            return sql
    return "TEXT"


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(vacancies)")}
            for f in fields(Vacancy):
                if f.name not in existing:
                    conn.execute(
                        f"ALTER TABLE vacancies ADD COLUMN {f.name} {_sql_type(str(f.type))} DEFAULT ''"
                    )

    # ---------- запуски и история ----------
    def create_run(self, source: str, api_status: str, queries_total: int) -> int:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO search_runs(started_at, source, api_status, status, queries_total) "
                "VALUES (?, ?, ?, 'running', ?)",
                (now_iso(), source, api_status, queries_total),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, summary: Any, status: str = "ok") -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE search_runs SET finished_at=?, source=?, api_status=?, status=?, "
                "queries_total=?, pages_done=?, found=?, unique_count=?, new_count=?, "
                "updated_count=?, changes_count=?, details_done=?, errors=?, duration_seconds=? "
                "WHERE id=?",
                (
                    now_iso(), summary.source, summary.api_status, status,
                    summary.queries_total, summary.pages_done, summary.found, summary.unique,
                    summary.new_count, summary.updated_count, summary.changes_count,
                    summary.details_done, json.dumps(summary.errors, ensure_ascii=False),
                    summary.duration_seconds, run_id,
                ),
            )
            self.set_meta("last_run_at", now_iso(), conn)
            self.set_meta("last_source", summary.source, conn)
            self.set_meta("last_api_status", summary.api_status, conn)
            self.set_meta("last_new_count", str(summary.new_count), conn)

    def log_query(self, run_id: int, query: Any, found: int, pages: int, error: str = "") -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO search_queries(run_id, query, params, found, pages, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, query.label, query.storage_value(), found, pages,
                    error[:500], now_iso(),
                ),
            )

    def get_runs(self, limit: int = 12) -> list[sqlite3.Row]:
        with closing(self._connect()) as conn:
            return list(conn.execute("SELECT * FROM search_runs ORDER BY id DESC LIMIT ?", (limit,)))

    def get_queries(self, run_id: int, limit: int = 100) -> list[sqlite3.Row]:
        with closing(self._connect()) as conn:
            return list(conn.execute(
                "SELECT * FROM search_queries WHERE run_id=? ORDER BY id LIMIT ?", (run_id, limit),
            ))

    def set_meta(self, key: str, value: str, conn: sqlite3.Connection | None = None) -> None:
        if conn is not None:
            conn.execute(
                "INSERT INTO meta(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)),
            )
            return
        with closing(self._connect()) as own, own:
            self.set_meta(key, value, own)

    def get_meta(self, key: str, default: str = "") -> str:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    # ---------- вакансии ----------
    def _insert_full(self, conn: sqlite3.Connection, v: Vacancy, now: str) -> None:
        data = v.db_values()
        data.update({
            "first_seen_at": now, "last_seen_at": now,
            "is_new": 1, "is_favorite": 0,
        })
        columns = list(data.keys())
        sql = (
            f"INSERT INTO vacancies ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})"
        )
        conn.execute(sql, [data[c] for c in columns])

    def upsert_partial(self, v: Vacancy) -> bool:
        """Сохраняет карточку из выдачи. Возвращает True, если вакансия новая."""
        now = now_iso()
        v.first_seen_at = v.first_seen_at or now
        v.last_seen_at = now
        v.content_hash = v.content_hash or content_hash(v.title, v.salary_display, v.experience_id)
        with closing(self._connect()) as conn, conn:
            old = conn.execute("SELECT * FROM vacancies WHERE id=?", (v.id,)).fetchone()
            if old is None:
                self._insert_full(conn, v, now)
                return True
            old_v = Vacancy.from_row(old)
            tags = list(dict.fromkeys([*old_v.search_tags, *v.search_tags]))
            labels = list(dict.fromkeys([*old_v.labels, *v.labels]))
            category = v.category if old_v.category in {"", "Широкий поиск", "Другие направления"} else old_v.category
            base_sets = (
                "last_seen_at=?, search_tags=?, labels=?, category=?, "
                "title=CASE WHEN title='' THEN ? ELSE title END, "
                "company=CASE WHEN company='' THEN ? ELSE company END, "
                "url=CASE WHEN url='' THEN ? ELSE url END, "
                "source=CASE WHEN source='' THEN ? ELSE source END"
            )
            params: list[Any] = [
                now, json.dumps(tags, ensure_ascii=False), json.dumps(labels, ensure_ascii=False),
                category, v.title, v.company, v.url, v.source,
            ]
            extra_sets = ""
            if not old_v.enriched:
                # Обновляем сниппеты и предварительную оценку только у кратких
                # карточек. Полное описание не перезаписывается урывками из выдачи.
                extra_sets = (
                    ", responsibilities=CASE WHEN ?<>'' THEN ? ELSE responsibilities END, "
                    "requirements=CASE WHEN ?<>'' THEN ? ELSE requirements END, "
                    "required_years=COALESCE(?, required_years), "
                    "score=?, score_explanation=?, score_factors=?, "
                    "excluded=?, exclusion_reason=?, "
                    "salary_monthly_rub=COALESCE(?, salary_monthly_rub), "
                    "work_format=CASE WHEN ?<>'' AND work_format='' THEN ? ELSE work_format END, "
                    "employment=CASE WHEN ?<>'' AND employment='' THEN ? ELSE employment END, "
                    "schedule=CASE WHEN ?<>'' AND schedule='' THEN ? ELSE schedule END, "
                    "published_at=CASE WHEN ?<>'' AND published_at='' THEN ? ELSE published_at END, "
                    "updated_at=CASE WHEN ?<>'' AND updated_at='' THEN ? ELSE updated_at END, "
                    "content_hash=CASE WHEN ?<>'' THEN ? ELSE content_hash END"
                )
                params.extend([
                    v.responsibilities, v.responsibilities,
                    v.requirements, v.requirements,
                    v.required_years,
                    v.score, v.score_explanation, json.dumps(v.score_factors, ensure_ascii=False),
                    int(v.excluded), v.exclusion_reason,
                    v.salary_monthly_rub,
                    v.work_format, v.work_format,
                    v.employment, v.employment,
                    v.schedule, v.schedule,
                    v.published_at, v.published_at,
                    v.updated_at, v.updated_at,
                    v.content_hash, v.content_hash,
                ])
            conn.execute(
                f"UPDATE vacancies SET {base_sets}{extra_sets} WHERE id=?",
                [*params, v.id],
            )
            return False

    def upsert_detail(self, v: Vacancy) -> tuple[bool, int]:
        """Обновляет полную карточку, фиксирует изменения зарплаты и описания."""
        now = now_iso()
        with closing(self._connect()) as conn, conn:
            old_row = conn.execute("SELECT * FROM vacancies WHERE id=?", (v.id,)).fetchone()
            if old_row is None:
                self._insert_full(conn, v, now)
                return False, 0
            old = Vacancy.from_row(old_row)
            changes: list[tuple[str, str, str]] = []

            def check(field: str, a: str, b: str, only_if_old: bool = True) -> None:
                if only_if_old and not a.strip():
                    return
                if a.strip() != b.strip():
                    changes.append((field, a[:1000], b[:1000]))

            # Первая загрузка полной карточки — это обогащение, а не изменение
            # вакансии работодателем. Иначе более подробный текст зарплаты
            # («… за месяц до вычета налогов») создавал бы ложную историю.
            if old.enriched:
                check("Зарплата", old.salary_display or "", v.salary_display or "")
                check("Описание", old.description or "", v.description or "")
                check("Название", old.title or "", v.title or "")
                check("Опыт", old.experience or "", v.experience or "")
                check("Формат работы", old.work_format or "", v.work_format or "")

            data = v.db_values()
            # Служебные поля не перезаписываются подробной карточкой.
            data.pop("id", None)
            for key in ("is_favorite", "is_new", "first_seen_at"):
                data[key] = int(old.is_favorite) if key == "is_favorite" else (
                    int(old.is_new) if key == "is_new" else old.first_seen_at
                )
            data["enriched"] = 1
            data["last_seen_at"] = now
            data["last_changed_at"] = now if changes else (old.last_changed_at or "")
            data["content_hash"] = content_hash(
                v.title, v.salary_display, v.description, v.experience_id, v.work_format,
            )
            if changes:
                data["updated_at"] = now
                data["updated_at_source"] = "change_tracking"
            elif v.updated_at_source == "published_fallback" and old.updated_at_source == "change_tracking":
                data["updated_at"] = old.updated_at
                data["updated_at_source"] = old.updated_at_source
            columns = [c for c in data if c != "id"]
            sql = (
                f"UPDATE vacancies SET {', '.join(f'{c}=?' for c in columns)} WHERE id=?"
            )
            conn.execute(sql, [data[c] for c in columns] + [v.id])
            for field, old_value, new_value in changes:
                conn.execute(
                    "INSERT INTO changes(vacancy_id, changed_at, field, old_value, new_value) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (v.id, now, field, old_value, new_value),
                )
            return bool(changes), len(changes)

    def get_vacancies(self, include_excluded: bool = True) -> list[Vacancy]:
        with closing(self._connect()) as conn:
            sql = "SELECT * FROM vacancies"
            if not include_excluded:
                sql += " WHERE excluded=0"
            sql += " ORDER BY first_seen_at DESC, score DESC"
            return [Vacancy.from_row(r) for r in conn.execute(sql)]

    def get_vacancy(self, vacancy_id: str) -> Vacancy | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM vacancies WHERE id=?", (vacancy_id,)).fetchone()
            return Vacancy.from_row(row) if row else None

    def need_details(self, limit: int) -> list[Vacancy]:
        if limit <= 0:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM vacancies WHERE enriched=0 AND excluded=0 "
                "ORDER BY is_new DESC, score DESC, first_seen_at DESC LIMIT ?", (limit,),
            )
            return [Vacancy.from_row(r) for r in rows]

    def set_favorite(self, vacancy_id: str, value: bool) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE vacancies SET is_favorite=? WHERE id=?", (int(value), vacancy_id))

    def mark_seen(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE vacancies SET is_new=0 WHERE is_new=1")
            self.set_meta("last_acknowledged_at", now_iso(), conn)

    def get_changes(self, vacancy_id: str | None = None, limit: int = 30) -> list[sqlite3.Row]:
        with closing(self._connect()) as conn:
            if vacancy_id:
                return list(conn.execute(
                    "SELECT c.*, v.title FROM changes c LEFT JOIN vacancies v ON v.id=c.vacancy_id "
                    "WHERE c.vacancy_id=? ORDER BY c.changed_at DESC LIMIT ?", (vacancy_id, limit),
                ))
            return list(conn.execute(
                "SELECT c.*, v.title FROM changes c LEFT JOIN vacancies v ON v.id=c.vacancy_id "
                "ORDER BY c.changed_at DESC LIMIT ?", (limit,),
            ))

    def rescore_all(self, rates: dict[str, float], strict_max_experience: bool) -> int:
        from .scoring import score_vacancy
        rows = self.get_vacancies(include_excluded=True)
        with closing(self._connect()) as conn, conn:
            for v in rows:
                score_vacancy(v, rates, strict_max_experience)
                conn.execute(
                    "UPDATE vacancies SET score=?, score_explanation=?, score_factors=?, "
                    "excluded=?, exclusion_reason=?, salary_monthly_rub=?, required_years=?, category=? "
                    "WHERE id=?",
                    (
                        v.score, v.score_explanation, json.dumps(v.score_factors, ensure_ascii=False),
                        int(v.excluded), v.exclusion_reason, v.salary_monthly_rub,
                        v.required_years, v.category, v.id,
                    ),
                )
        return len(rows)

    def stats(self) -> dict[str, Any]:
        items = self.get_vacancies(include_excluded=True)
        active = [v for v in items if not v.excluded]
        salaries = [v.salary_monthly_rub for v in active if v.salary_monthly_rub and v.salary_monthly_rub > 0]
        by_category: dict[str, dict[str, float]] = {}
        by_city: dict[str, int] = {}
        by_format: dict[str, int] = {}
        by_source: dict[str, int] = {}
        bins = [0] * 5  # 0-19, 20-39, 40-59, 60-79, 80-100
        for v in active:
            cat = by_category.setdefault(v.category, {"count": 0, "score_sum": 0.0})
            cat["count"] += 1
            cat["score_sum"] += v.score
            by_city[v.city or "Не указан"] = by_city.get(v.city or "Не указан", 0) + 1
            by_format[v.work_format or "Не указан"] = by_format.get(v.work_format or "Не указан", 0) + 1
            by_source[v.source or "неизвестно"] = by_source.get(v.source or "неизвестно", 0) + 1
            bins[min(4, int(v.score // 20))] += 1
        last_run = None
        with closing(self._connect()) as conn:
            last_run = conn.execute("SELECT * FROM search_runs ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "total": len(active),
            "total_all": len(items),
            "new_count": sum(1 for v in active if v.is_new),
            "favorites": sum(1 for v in active if v.is_favorite),
            "with_salary": len(salaries),
            "no_salary": sum(1 for v in active if v.no_salary),
            "avg_score": round(sum(v.score for v in active) / len(active), 1) if active else 0.0,
            "avg_salary": round(sum(salaries) / len(salaries)) if salaries else 0,
            "max_score": max((v.score for v in active), default=0),
            "by_category": by_category,
            "by_city": by_city,
            "by_format": by_format,
            "by_source": by_source,
            "score_bins": bins,
            "last_run": dict(last_run) if last_run else None,
            "last_api_status": self.get_meta("last_api_status", ""),
            "last_source": self.get_meta("last_source", ""),
        }
