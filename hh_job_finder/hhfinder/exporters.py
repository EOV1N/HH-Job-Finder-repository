"""Экспорт реальных вакансий из SQLite в XLSX, CSV и JSON."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .models import Vacancy

COLUMNS: list[tuple[str, str]] = [
    ("score", "Оценка"),
    ("id", "ID вакансии"),
    ("title", "Должность"),
    ("company", "Компания"),
    ("salary_from", "Зарплата от"),
    ("salary_to", "Зарплата до"),
    ("currency", "Валюта"),
    ("salary_display", "Зарплата (как на HH)"),
    ("salary_monthly_rub", "Зарплата ₽/мес (нормализованная)"),
    ("no_salary", "Без указанной зарплаты"),
    ("city", "Город"),
    ("address", "Адрес"),
    ("experience", "Требуемый опыт"),
    ("required_years", "Лет опыта из описания"),
    ("work_format", "Формат работы"),
    ("employment", "Тип занятости"),
    ("schedule", "График работы"),
    ("responsibilities", "Обязанности"),
    ("requirements", "Требования"),
    ("key_skills", "Ключевые навыки"),
    ("published_at", "Дата публикации"),
    ("updated_at", "Дата обновления"),
    ("updated_at_source", "Источник даты обновления"),
    ("url", "Ссылка на вакансию"),
    ("category", "Категория"),
    ("search_tags", "Найдено по запросам"),
    ("score_explanation", "Почему такая оценка"),
    ("score_factors", "Составляющие оценки"),
    ("is_new", "Новая"),
    ("is_favorite", "В избранном"),
    ("enriched", "Описание загружено"),
    ("excluded", "Исключена"),
    ("exclusion_reason", "Причина исключения"),
    ("first_seen_at", "Впервые найдена"),
    ("last_seen_at", "Последний раз найдена"),
    ("last_changed_at", "Изменение зафиксировано"),
    ("source", "Источник данных"),
    ("description", "Полное описание"),
]

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(x) for x in value)
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    text = CONTROL_RE.sub(" ", str(value))
    # Ячейка Excel не может содержать больше 32767 символов.
    return text[:32000] if len(text) > 32000 else text


def build_records(items: Iterable[Vacancy]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for v in items:
        raw = v.to_dict(human=True)
        records.append({label: _cell(raw.get(key)) for key, label in COLUMNS})
    return records


def export_vacancies(items: Iterable[Vacancy], path: str | Path, fmt: str | None = None) -> Path:
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    records = build_records(items)
    headers = [label for _, label in COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers, delimiter=";", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        return path

    if fmt == "json":
        payload = {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "count": len(records),
            "note": "Реальные вакансии из локальной базы HH Job Finder; тестовые данные не используются.",
            "vacancies": records,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    if fmt == "xlsx":
        import pandas as pd
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        df = pd.DataFrame(records, columns=headers)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Вакансии")
            ws = writer.sheets["Вакансии"]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            fill = PatternFill("solid", fgColor="162033")
            font = Font(color="EAF2FF", bold=True)
            for cell in ws[1]:
                cell.fill = fill
                cell.font = font
                cell.alignment = Alignment(vertical="center", wrap_text=True)
            ws.row_dimensions[1].height = 30
            widths = {
                "Должность": 34, "Компания": 28, "Зарплата (как на HH)": 25,
                "Город": 20, "Адрес": 34, "Обязанности": 45, "Требования": 45,
                "Ключевые навыки": 30, "Ссылка на вакансию": 34,
                "Почему такая оценка": 46, "Полное описание": 60,
                "Найдено по запросам": 35, "Категория": 26,
            }
            for idx, header in enumerate(headers, start=1):
                ws.column_dimensions[get_column_letter(idx)].width = min(60, max(11, widths.get(header, len(header) + 4)))
            url_col = headers.index("Ссылка на вакансию") + 1
            for row in range(2, ws.max_row + 1):
                cell = ws.cell(row=row, column=url_col)
                if cell.value and str(cell.value).startswith("http"):
                    cell.hyperlink = str(cell.value)
                    cell.style = "Hyperlink"
                for col in range(1, ws.max_column + 1):
                    ws.cell(row=row, column=col).alignment = Alignment(vertical="top", wrap_text=col in (17, 18, 27, 39))

            # Лист со сводкой по текущей выгрузке.
            cities = Counter(r["Город"] for r in records)
            categories = Counter(r["Категория"] for r in records)
            summary_rows = [
                ("Сформировано", datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")),
                ("Вакансий в выгрузке", len(records)),
                ("Средняя оценка", round(sum(float(r["Оценка"] or 0) for r in records) / len(records), 1) if records else 0),
                ("Без указанной зарплаты", sum(1 for r in records if r["Без указанной зарплаты"] == "Да")),
                ("Новых", sum(1 for r in records if r["Новая"] == "Да")),
                ("В избранном", sum(1 for r in records if r["В избранном"] == "Да")),
                ("", ""),
                ("Город", "Количество"),
                *cities.most_common(12),
                ("", ""),
                ("Категория", "Количество"),
                *categories.most_common(12),
            ]
            ws2 = writer.book.create_sheet("Сводка", 0)
            for row in summary_rows:
                ws2.append(list(row))
            ws2.column_dimensions["A"].width = 34
            ws2.column_dimensions["B"].width = 24
            for cell in ws2[1]:
                cell.font = Font(bold=True, color="EAF2FF")
                cell.fill = fill
        return path

    raise ValueError(f"Неподдерживаемый формат экспорта: {fmt}")
