"""Панель подробной информации о выбранной вакансии."""
from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

# QSizePolicy уже импортирован: используется, чтобы длинные строки не расширяли
# QScrollArea по горизонтали.

from ..models import Vacancy
from ..utils import human_date, shorten
from .theme import COLORS
from .widgets import FactorBars, ScoreBadge, chip, salary_text


class VacancyDetailPanel(QFrame):
    openRequested = Signal(str)
    favoriteToggled = Signal(str, bool)
    exportRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self.setMinimumWidth(330)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)
        self.v: Vacancy | None = None
        self._show_empty()

    def _new_content(self) -> tuple[QWidget, QVBoxLayout]:
        # takeWidget снимает старый контент с QScrollArea до установки нового:
        # иначе Qt может удалить C++-объект раньше, чем Python вызовет deleteLater.
        old = self.scroll.takeWidget()
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 20)
        layout.setSpacing(12)
        self.scroll.setWidget(content)
        viewport_width = self.scroll.viewport().width()
        if viewport_width > 0:
            content.setMaximumWidth(viewport_width)
        if old is not None:
            old.deleteLater()
        return content, layout

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        widget = self.scroll.widget()
        width = self.scroll.viewport().width()
        if widget is not None and width > 0:
            widget.setMaximumWidth(width)

    def _show_empty(self) -> None:
        _, layout = self._new_content()
        label = QLabel("Выберите вакансию, чтобы увидеть описание, требования и историю изменений.")
        label.setObjectName("muted")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addStretch(1)

    def clear(self) -> None:
        self.v = None
        self._show_empty()

    @staticmethod
    def _row(grid: QGridLayout, row: int, title: str, value: str, accent: bool = False) -> None:
        key = QLabel(title)
        key.setObjectName("muted")
        val = QLabel(value or "—")
        val.setWordWrap(True)
        val.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        if accent:
            val.setStyleSheet(f"color: {COLORS['blue']}; font-weight: 600;")
        grid.addWidget(key, row, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(val, row, 1)

    def set_vacancy(self, v: Vacancy | None, changes: Iterable[Any] | None = None) -> None:
        if v is None:
            self.clear()
            return
        self.v = v
        _, layout = self._new_content()

        head = QHBoxLayout()
        head.setSpacing(14)
        badge = ScoreBadge(v.score, 72)
        head.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        title = QLabel(v.title or "Без названия")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        company = QLabel(v.company or "Компания не указана")
        company.setObjectName("muted")
        company.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(company)
        head.addLayout(titles, 1)
        layout.addLayout(head)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(chip(v.category, accent=True))
        if v.is_new:
            chips.addWidget(chip("Новая", accent=True))
        if v.no_salary:
            chips.addWidget(chip("Без з/п", warn=True))
        if v.excluded:
            chips.addWidget(chip("Исключена: " + shorten(v.exclusion_reason, 30), warn=True))
        if not v.enriched:
            chips.addWidget(chip("Описание не загружено", warn=True))
        chips.addWidget(chip("HH API" if v.source == "hh_api" else "hh.ru web"))
        chips.addStretch(1)
        layout.addLayout(chips)

        actions = QHBoxLayout()
        fav = QPushButton("★" if v.is_favorite else "☆")
        fav.setObjectName("icon")
        fav.setFixedWidth(34)
        fav.setToolTip("В избранном. Нажмите, чтобы убрать" if v.is_favorite else "Добавить в избранное")
        fav.clicked.connect(lambda: self.favoriteToggled.emit(v.id, not v.is_favorite))
        open_btn = QPushButton("Открыть HH")
        open_btn.setObjectName("primary")
        open_btn.setToolTip("Открыть оригинальную вакансию на hh.ru")
        open_btn.clicked.connect(lambda: self.openRequested.emit(v.url))
        export_btn = QPushButton("Экспорт")
        export_btn.setObjectName("icon")
        export_btn.clicked.connect(lambda: self.exportRequested.emit(v))
        for button in (fav, open_btn, export_btn):
            button.setStyleSheet("padding: 6px 9px; font-size: 11px;")
        actions.addWidget(fav)
        actions.addWidget(open_btn)
        actions.addWidget(export_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        rows = [
            ("Зарплата", salary_text(v)),
            ("Нормализованно", f"{int(v.salary_monthly_rub):,}".replace(",", "\u202f") + " ₽/мес" if v.salary_monthly_rub else "—"),
            ("Город", v.city or "Не указан"),
            ("Адрес", v.address or "Не указан"),
            ("Опыт", v.experience or "Не указан"),
            ("Опыт из описания", "не определено" if v.required_years is None else f"от {v.required_years} лет"),
            ("Формат работы", v.work_format or "Не указан"),
            ("Тип занятости", v.employment or "Не указан"),
            ("График", v.schedule or "Не указан"),
            ("Опубликована", human_date(v.published_at, True)),
            ("ID / источник", f"{v.id}  •  {'официальный API' if v.source == 'hh_api' else 'публичная страница hh.ru'}"),
        ]
        for i, (key, value) in enumerate(rows):
            self._row(grid, i, key, value, accent=(key == "Зарплата" and not v.no_salary))
        if v.updated_at_source == "published_fallback":
            updated = human_date(v.updated_at, True) + " — HH не публикует дату обновления отдельно; показана дата публикации"
        elif v.updated_at_source == "change_tracking":
            updated = human_date(v.updated_at, True) + " — изменение зафиксировано приложением"
        else:
            updated = human_date(v.updated_at, True)
        self._row(grid, len(rows), "Обновлена", updated)
        if v.last_changed_at:
            self._row(grid, len(rows) + 1, "Изменение в базе", human_date(v.last_changed_at, True))
        link = QLabel(f'<a href="{v.url}" style="color:{COLORS["accent"]}">{v.url}</a>')
        link.setOpenExternalLinks(True)
        link.setWordWrap(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        grid.addWidget(QLabel("Ссылка"), len(rows) + 2, 0)
        grid.addWidget(link, len(rows) + 2, 1)
        layout.addLayout(grid)

        explanation = QLabel(v.score_explanation or "Объяснение появится после загрузки описания.")
        explanation.setWordWrap(True)
        explanation.setObjectName("hint")
        layout.addWidget(explanation)
        factors = FactorBars()
        factors.set_factors(v.score_factors or {})
        layout.addWidget(factors)

        def section(title: str, body: str) -> None:
            if not body:
                return
            heading = QLabel(title)
            heading.setObjectName("sectionTitle")
            layout.addWidget(heading)
            text = QLabel(shorten(body, 5000))
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.setStyleSheet(f"color: {COLORS['text']}; line-height: 140%;")
            layout.addWidget(text)

        if v.enriched and v.description:
            section("Обязанности", v.responsibilities)
            section("Требования", v.requirements)
            section("Полное описание", v.description)
        else:
            has_snippets = bool(v.responsibilities or v.requirements)
            note_text = (
                "Полное описание ещё не загружено. Ниже — краткие сниппеты из поисковой "
                "выдачи HH; приложение догрузит полный текст и проверит фактический опыт позже."
                if has_snippets else
                "Полное описание ещё не загружено. При следующем обновлении приложение "
                "догрузит обязанности, требования и проверит фактический опыт в тексте."
            )
            note = QLabel(note_text)
            note.setObjectName("hint")
            note.setWordWrap(True)
            layout.addWidget(note)
            section("Обязанности (сниппет HH)", v.responsibilities)
            section("Требования (сниппет HH)", v.requirements)

        if v.key_skills:
            heading = QLabel("Ключевые навыки")
            heading.setObjectName("sectionTitle")
            layout.addWidget(heading)
            skill_row = QHBoxLayout()
            skill_row.setSpacing(6)
            for skill in v.key_skills[:12]:
                skill_row.addWidget(chip(skill))
            skill_row.addStretch(1)
            layout.addLayout(skill_row)

        heading = QLabel("История изменений")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        change_rows = list(changes or [])
        if not change_rows:
            empty = QLabel("Изменений зарплаты или описания пока не зафиксировано.")
            empty.setObjectName("hint")
            layout.addWidget(empty)
        else:
            for row in change_rows[:8]:
                data = dict(row) if not isinstance(row, dict) else row
                text = (
                    f"{human_date(data.get('changed_at'), True)} • {data.get('field', '')}: "
                    f"{shorten(str(data.get('old_value', '')), 60)} → {shorten(str(data.get('new_value', '')), 60)}"
                )
                label = QLabel(text)
                label.setObjectName("hint")
                label.setWordWrap(True)
                layout.addWidget(label)
        layout.addStretch(1)
