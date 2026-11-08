"""Автономный HTML-отчёт из реальной SQLite-базы (без внешних ресурсов)."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Vacancy
from .utils import human_date, shorten


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _salary(v: Vacancy) -> str:
    return "Без з/п" if v.no_salary or not v.salary_display else v.salary_display


def _score_color(score: float) -> str:
    if score >= 80:
        return "#63e6be"
    if score >= 60:
        return "#5aa9ff"
    if score >= 40:
        return "#f2b45c"
    return "#f47d7d"


def _bar_rows(values: list[tuple[str, float]], color: str) -> str:
    if not values:
        return '<div class="muted">Нет данных</div>'
    max_value = max((abs(v) for _, v in values), default=1) or 1
    rows = []
    for label, value in values:
        width = max(2, min(100, abs(value) / max_value * 100))
        rows.append(
            f'<div class="bar-row"><div class="bar-label">{_e(label)}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%;background:{color}"></div></div>'
            f'<div class="bar-value">{value:g}</div></div>'
        )
    return "".join(rows)


def generate_report(db, out_path: str | Path, limit: int = 500) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stats = db.stats()
    all_items = db.get_vacancies(include_excluded=True)
    active = [v for v in all_items if not v.excluded]
    active.sort(key=lambda v: (v.score, v.published_at or ""), reverse=True)
    items = active[:limit]
    new_items = [v for v in active if v.is_new][:12]
    changes = db.get_changes(limit=12)
    runs = db.get_runs(6)

    source = stats.get("last_source") or "—"
    source_label = "официальный API HH" if source == "hh_api" else "щадящий резервный режим hh.ru" if source == "hh_web" else "ещё нет запуска"
    api_status = stats.get("last_api_status") or ""
    warning = ""
    if "403" in api_status or "OAuth" in api_status or "токен" in api_status.lower():
        warning = (
            '<div class="warning"><b>Ограничение API HH.</b> Анонимный GET /vacancies возвращает 403 и требует OAuth-токен. '
            'Справочники API используются, а вакансии в этом отчёте собраны через щадящий резервный режим публичных страниц hh.ru. '
            'Это реальные объявления, а не тестовые данные.</div>'
        )

    bins = stats.get("score_bins", [0] * 5)
    score_bars = _bar_rows(list(zip(["0–19", "20–39", "40–59", "60–79", "80–100"], bins)), "#63e6be")
    category_values = sorted(
        ((k, v["count"]) for k, v in stats.get("by_category", {}).items()),
        key=lambda x: x[1], reverse=True,
    )[:10]
    category_bars = _bar_rows(category_values, "#8b8cf7")
    city_values = sorted(stats.get("by_city", {}).items(), key=lambda x: x[1], reverse=True)[:8]
    city_bars = _bar_rows(city_values, "#5aa9ff")

    def tile(title: str, value: str, subtitle: str, color: str) -> str:
        return (
            f'<div class="tile"><div class="tile-title">{_e(title)}</div>'
            f'<div class="tile-value" style="color:{color}">{_e(value)}</div>'
            f'<div class="tile-sub">{_e(subtitle)}</div></div>'
        )

    kpis = "".join([
        tile("Активных вакансий", str(stats.get("total", 0)), "после дедупликации", "#63e6be"),
        tile("Новых", str(stats.get("new_count", 0)), "с прошлого просмотра", "#5ed6a4"),
        tile("Средняя оценка", str(stats.get("avg_score", 0)), "баллов из 100", "#5aa9ff"),
        tile("Лучшее совпадение", str(int(stats.get("max_score", 0))), "максимальный балл", "#8b8cf7"),
        tile("Средняя зарплата", f"{int(stats.get('avg_salary', 0)):,}".replace(",", " ") + " ₽" if stats.get("avg_salary") else "—", "нормализованно в месяц", "#f2b45c"),
        tile("Без зарплаты", str(stats.get("no_salary", 0)), "отмечены отдельно", "#f47d7d"),
    ])

    new_rows = []
    for v in new_items:
        new_rows.append(
            f'<li><span class="pill" style="color:{_score_color(v.score)}">{int(v.score)}</span> '
            f'<a href="{_e(v.url)}" target="_blank" rel="noopener">{_e(v.title)}</a> '
            f'<span class="muted">— {_e(v.company)} • {_e(_salary(v))}</span></li>'
        )
    new_html = "<ul class='list'>" + "".join(new_rows) + "</ul>" if new_rows else '<div class="muted">Новых вакансий нет</div>'

    change_rows = []
    for row in changes:
        d = dict(row) if not isinstance(row, dict) else row
        change_rows.append(
            f"<li><b>{_e(d.get('field'))}</b> • {_e(shorten(str(d.get('title') or d.get('vacancy_id')), 45))} "
            f"<span class='muted'>{_e(human_date(d.get('changed_at'), True))}</span><br>"
            f"<span class='muted'>{_e(shorten(str(d.get('old_value')), 90))} → {_e(shorten(str(d.get('new_value')), 90))}</span></li>"
        )
    changes_html = "<ul class='list'>" + "".join(change_rows) + "</ul>" if change_rows else '<div class="muted">Изменений пока не зафиксировано</div>'

    run_rows = []
    for row in runs:
        d = dict(row) if not isinstance(row, dict) else row
        run_rows.append(
            f"<tr><td>{_e(human_date(d.get('started_at'), True))}</td><td>{_e(d.get('source'))}</td>"
            f"<td>{_e(d.get('status'))}</td><td>{_e(d.get('unique_count'))}</td>"
            f"<td>{_e(d.get('new_count'))}</td></tr>"
        )
    runs_html = "".join(run_rows) or '<tr><td colspan="5" class="muted">Запусков пока нет</td></tr>'

    table_rows = []
    for v in items:
        table_rows.append(
            "<tr data-search='{}'>"
            "<td><span class='score' style='background:{}'>{}</span></td>"
            "<td><a href='{}' target='_blank' rel='noopener'>{}</a><div class='muted'>{}</div></td>"
            "<td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
            "</tr>".format(
                _e(" ".join([v.title, v.company, v.city, v.category, v.description[:200]]).lower()),
                _score_color(v.score), int(v.score), _e(v.url), _e(v.title),
                _e(shorten(v.score_explanation, 110)), _e(v.company), _e(_salary(v)),
                _e(v.city), _e(v.experience), _e(v.work_format),
                _e(human_date(v.published_at)), _e(v.category),
            )
        )

    css = """
    :root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b0f16;color:#e8eef7;font:14px/1.5 Arial, sans-serif}
    .wrap{max-width:1400px;margin:0 auto;padding:28px}h1{font-size:30px;margin:0 0 4px}h2{font-size:18px;margin:26px 0 12px}
    .muted{color:#8b9bb1}.sub{color:#8b9bb1;margin-bottom:20px}.warning{background:#33271b;border:1px solid #6a5230;color:#f2b45c;padding:14px 16px;border-radius:12px;margin:18px 0}
    .grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}.tile,.card{background:#111826;border:1px solid #273449;border-radius:14px;padding:16px}
    .tile-title{color:#8b9bb1;font-size:12px;text-transform:uppercase;letter-spacing:.5px}.tile-value{font-size:26px;font-weight:700;margin:5px 0}.tile-sub{color:#8b9bb1;font-size:12px}
    .charts{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.bar-row{display:grid;grid-template-columns:minmax(90px,38%) 1fr 48px;gap:8px;align-items:center;margin:8px 0;font-size:12px}
    .bar-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c3cede}.bar-track{background:#1d2a3d;height:12px;border-radius:6px;overflow:hidden}.bar-fill{height:100%;border-radius:6px}.bar-value{text-align:right;color:#e8eef7}
    .cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}.list{margin:0;padding-left:20px}.list li{margin:8px 0}a{color:#63e6be;text-decoration:none}a:hover{text-decoration:underline}
    .pill{font-weight:700}.score{display:inline-block;min-width:36px;text-align:center;color:#07141a;font-weight:700;border-radius:8px;padding:4px 6px}
    table{width:100%;border-collapse:collapse;background:#111826;border:1px solid #273449;border-radius:12px;overflow:hidden}th{background:#162033;color:#8b9bb1;text-align:left;padding:10px;font-size:12px}td{padding:10px;border-top:1px solid #1b2637;vertical-align:top}tr:hover td{background:#162033}
    .toolbar{display:flex;gap:10px;margin:12px 0}input,select{background:#162033;border:1px solid #273449;color:#e8eef7;border-radius:10px;padding:9px 11px}input{flex:1}
    footer{color:#8b9bb1;font-size:12px;margin-top:28px;border-top:1px solid #273449;padding-top:14px}
    @media(max-width:1000px){.grid,.charts{grid-template-columns:repeat(2,1fr)}.cols{grid-template-columns:1fr}}
    """
    js = """
    const q=document.getElementById('q'),cat=document.getElementById('cat'),rows=[...document.querySelectorAll('#vacancies tbody tr')];
    function filter(){const s=q.value.toLowerCase();const c=cat.value;rows.forEach(r=>{r.style.display=(!s||r.dataset.search.includes(s))&&(!c||r.dataset.search.includes(c.toLowerCase()))?'':'none'});}
    q.addEventListener('input',filter);cat.addEventListener('change',filter);
    """
    categories = sorted({v.category for v in active if v.category})
    options = "".join(f'<option value="{_e(c)}">{_e(c)}</option>' for c in categories)
    html_doc = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HH Job Finder — отчёт по реальным вакансиям</title><style>{css}</style></head><body><div class="wrap">
<h1>HH Job Finder</h1>
<div class="sub">Набережные Челны • Елабуга • ОЭЗ «Алабуга» &nbsp;|&nbsp; сформировано {_e(datetime.now().astimezone().strftime('%d.%m.%Y %H:%M'))} &nbsp;|&nbsp; источник: {_e(source_label)}</div>
{('<div class="card muted">Статус API: ' + _e(shorten(api_status, 260)) + '</div>') if api_status else ''}
{warning}
<div class="grid">{kpis}</div>
<h2>Оценки, категории и география</h2>
<div class="charts"><div class="card"><b>Распределение оценок</b>{score_bars}</div><div class="card"><b>Категории</b>{category_bars}</div><div class="card"><b>Города</b>{city_bars}</div></div>
<h2>Новые вакансии и изменения</h2>
<div class="cols"><div class="card"><b>Новые</b>{new_html}</div><div class="card"><b>Изменения зарплаты и описаний</b>{changes_html}</div></div>
<h2>История запусков</h2><div class="card"><table><thead><tr><th>Дата</th><th>Источник</th><th>Статус</th><th>Уникальных</th><th>Новых</th></tr></thead><tbody>{runs_html}</tbody></table></div>
<h2>Вакансии ({len(items)} из {len(active)})</h2>
<div class="toolbar"><input id="q" placeholder="Поиск по названию, компании, описанию…"><select id="cat"><option value="">Все категории</option>{options}</select></div>
<table id="vacancies"><thead><tr><th>Балл</th><th>Должность</th><th>Компания</th><th>Зарплата</th><th>Город</th><th>Опыт</th><th>Формат</th><th>Опубликовано</th><th>Категория</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table>
<footer>Все строки построены из локальной SQLite-базы приложения. Тестовые/синтетические вакансии в отчёт не добавляются.
Если HH не публикует отдельную дату обновления, приложение показывает дату публикации и отслеживает реальные изменения зарплаты/описания самостоятельно.
Оценка 0–100 детерминированная и объяснимая; это не LLM. Нормализованная зарплата — ориентир для фильтра, а не расчёт оклада на руки.</footer>
</div><script>{js}</script></body></html>"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
