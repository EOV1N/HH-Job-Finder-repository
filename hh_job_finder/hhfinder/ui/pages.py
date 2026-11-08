"""Разделы приложения: Главная, Категории и Настройки."""
from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config import AREA_INFO, EXPERIENCE_INFO, KEYWORD_GROUPS, Settings
from ..models import Vacancy
from ..utils import human_date, shorten
from .browser import VacancyBrowser
from .theme import COLORS
from .widgets import BarChart, StatTile, salary_text


class HomePage(QWidget):
    vacancySelected = Signal(str)
    showNewRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)
        content = QWidget()
        self.scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(22, 20, 22, 24)
        root.setSpacing(16)

        self.source_label = QLabel("Источник данных ещё не проверялся")
        self.source_label.setObjectName("hint")
        root.addWidget(self.source_label)
        self.warning = QLabel()
        self.warning.setObjectName("card")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(
            f"background:#33271b; border:1px solid #6a5230; border-radius:12px; "
            f"padding:12px; color:{COLORS['amber']};"
        )
        self.warning.hide()
        root.addWidget(self.warning)

        tiles = QGridLayout()
        tiles.setSpacing(12)
        self.tiles = {
            "total": StatTile("Найдено вакансий", "—", "после исключения дубликатов"),
            "new": StatTile("Новых с прошлого просмотра", "—", "отметьте просмотренным", COLORS["green"]),
            "avg": StatTile("Средняя оценка", "—", "по активным вакансиям", COLORS["blue"]),
            "best": StatTile("Лучшее совпадение", "—", "максимум 100 баллов", COLORS["accent2"]),
            "salary": StatTile("Средняя зарплата", "—", "нормализованно ₽/мес", COLORS["amber"]),
        }
        for i, tile in enumerate(self.tiles.values()):
            tiles.addWidget(tile, 0, i)
        root.addLayout(tiles)

        charts = QHBoxLayout()
        charts.setSpacing(12)
        self.score_chart = BarChart("Распределение оценок")
        self.city_chart = BarChart("Вакансии по городам", color=COLORS["blue"])
        charts.addWidget(self.score_chart, 1)
        charts.addWidget(self.city_chart, 1)
        root.addLayout(charts)

        lower = QGridLayout()
        lower.setSpacing(12)
        new_box = QGroupBox("Новые вакансии")
        new_layout = QVBoxLayout(new_box)
        self.new_list = QListWidget()
        self.new_list.setMinimumHeight(220)
        self.new_list.itemDoubleClicked.connect(self._item_selected)
        new_layout.addWidget(self.new_list)
        show_new = QPushButton("Показать только новые")
        show_new.clicked.connect(self.showNewRequested.emit)
        new_layout.addWidget(show_new)

        changes_box = QGroupBox("Последние изменения зарплаты и описаний")
        changes_layout = QVBoxLayout(changes_box)
        self.changes_list = QListWidget()
        self.changes_list.setMinimumHeight(220)
        self.changes_list.itemDoubleClicked.connect(self._item_selected)
        changes_layout.addWidget(self.changes_list)

        runs_box = QGroupBox("История запусков")
        runs_layout = QVBoxLayout(runs_box)
        self.runs_table = QTableWidget(0, 6)
        self.runs_table.setHorizontalHeaderLabels(["Дата", "Источник", "Статус", "Найдено", "Новых", "Ошибки"])
        self.runs_table.verticalHeader().hide()
        self.runs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.runs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.runs_table.setMinimumHeight(220)
        runs_layout.addWidget(self.runs_table)

        lower.addWidget(new_box, 0, 0)
        lower.addWidget(changes_box, 0, 1)
        lower.addWidget(runs_box, 1, 0, 1, 2)
        root.addLayout(lower)
        root.addStretch(1)

    def _item_selected(self, item: QListWidgetItem) -> None:
        vid = item.data(Qt.ItemDataRole.UserRole)
        if vid:
            self.vacancySelected.emit(str(vid))

    def set_data(
        self,
        stats: dict[str, Any],
        items: list[Vacancy],
        new_items: list[Vacancy],
        changes: Iterable[Any],
        runs: Iterable[Any],
    ) -> None:
        self.tiles["total"].set_value(f"{stats.get('total', 0):,}".replace(",", "\u202f"), "уникальных активных вакансий")
        self.tiles["new"].set_value(str(stats.get("new_count", 0)), "нажмите «Отметить просмотренным»")
        self.tiles["avg"].set_value(str(stats.get("avg_score", 0)), "средний балл по всем активным")
        self.tiles["best"].set_value(str(int(stats.get("max_score", 0))), "лучшая оценка соответствия")
        avg_salary = stats.get("avg_salary", 0)
        self.tiles["salary"].set_value(
            f"{int(avg_salary):,}".replace(",", "\u202f") + " ₽" if avg_salary else "—",
            f"у {stats.get('with_salary', 0)} вакансий указан доход",
        )

        source = stats.get("last_source") or "ещё нет запусков"
        api_status = stats.get("last_api_status") or ""
        label = "официальный API HH" if source == "hh_api" else "щадящий резервный режим hh.ru" if source == "hh_web" else source
        self.source_label.setText(f"Последний запуск: {label} • {shorten(api_status, 150)}")
        if "403" in api_status or "OAuth" in api_status or "токен" in api_status.lower():
            self.warning.setText(
                "Официальный GET /vacancies API HH требует OAuth-токен: анонимный запрос возвращает 403. "
                "Справочники API используются, а вакансии собраны через щадящий резервный режим публичных страниц hh.ru. "
                "Добавьте токен в Настройках, чтобы перейти на официальный источник."
            )
            self.warning.show()
        else:
            self.warning.hide()

        bins = stats.get("score_bins", [0] * 5)
        self.score_chart.set_values(list(zip(
            ["0–19", "20–39", "40–59", "60–79", "80–100"], bins,
        )), unit="", color=COLORS["accent"])
        cities = sorted(stats.get("by_city", {}).items(), key=lambda x: x[1], reverse=True)[:8]
        self.city_chart.set_values(cities, unit="", color=COLORS["blue"])

        self.new_list.clear()
        for v in new_items[:10]:
            text = f"{int(v.score)} • {v.title}  |  {v.company}  |  {salary_text(v)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, v.id)
            item.setToolTip(v.score_explanation)
            self.new_list.addItem(item)
        if not new_items:
            self.new_list.addItem("Новых вакансий пока нет")

        self.changes_list.clear()
        rows = list(changes)
        for row in rows[:10]:
            data = dict(row) if not isinstance(row, dict) else row
            text = (
                f"{human_date(data.get('changed_at'), True)} • {shorten(str(data.get('title') or data.get('vacancy_id')), 34)} • "
                f"{data.get('field')}: {shorten(str(data.get('old_value')), 28)} → {shorten(str(data.get('new_value')), 28)}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, data.get("vacancy_id"))
            self.changes_list.addItem(item)
        if not rows:
            self.changes_list.addItem("Изменений пока не зафиксировано")

        run_rows = list(runs)
        self.runs_table.setRowCount(len(run_rows))
        for i, row in enumerate(run_rows):
            data = dict(row) if not isinstance(row, dict) else row
            values = [
                human_date(data.get("started_at"), True),
                "API" if data.get("source") == "hh_api" else "hh.ru" if data.get("source") == "hh_web" else "—",
                str(data.get("status", "")),
                str(data.get("unique_count", data.get("found", 0))),
                str(data.get("new_count", 0)),
                str(len(data.get("errors", "[]"))) if isinstance(data.get("errors"), str) and len(data.get("errors")) > 4 else "0",
            ]
            for j, value in enumerate(values):
                self.runs_table.setItem(i, j, QTableWidgetItem(value))
        self.runs_table.resizeRowsToContents()


class CategoriesPage(QWidget):
    categorySelected = Signal(str)

    def __init__(self, changes_provider=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.browser = VacancyBrowser("table", changes_provider)
        left = QFrame()
        left.setObjectName("card")
        left.setMinimumWidth(300)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)
        hint = QLabel("Кликните по категории, чтобы отфильтровать таблицу.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        self.count_chart = BarChart("Количество вакансий")
        self.score_chart = BarChart("Средняя оценка", color=COLORS["accent2"])
        self.count_chart.barClicked.connect(self.categorySelected.emit)
        self.score_chart.barClicked.connect(self.categorySelected.emit)
        left_layout.addWidget(self.count_chart, 1)
        left_layout.addWidget(self.score_chart, 1)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([330, 950])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def set_data(self, stats: dict[str, Any], items: list[Vacancy]) -> None:
        category_stats = stats.get("by_category", {})
        counts = sorted(((k, v["count"]) for k, v in category_stats.items()), key=lambda x: x[1], reverse=True)
        averages = sorted(
            ((k, round(v["score_sum"] / max(1, v["count"]), 1)) for k, v in category_stats.items()),
            key=lambda x: x[1], reverse=True,
        )
        self.count_chart.set_values(counts, unit="", color=COLORS["accent"])
        self.score_chart.set_values(averages, unit="", color=COLORS["accent2"])
        self.browser.set_items(items)

    def set_changes_provider(self, provider) -> None:
        self.browser.set_changes_provider(provider)


class SettingsPage(QWidget):
    settingsSaved = Signal(object)
    runNow = Signal()
    testApi = Signal()
    getToken = Signal(str, str)

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)
        content = QWidget()
        self.scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)

        title = QLabel("Настройки поиска")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        self.api_status = QLabel("Статус API ещё не проверялся")
        self.api_status.setObjectName("hint")
        self.api_status.setWordWrap(True)
        root.addWidget(self.api_status)

        geo = QGroupBox("География и опыт")
        geo_layout = QGridLayout(geo)
        self.area_boxes: dict[str, QCheckBox] = {}
        for i, key in enumerate(("1641", "1633", "alabuga")):
            label = "ОЭЗ «Алабуга» (весь Татарстан + фильтр по слову «Алабуга»)" if key == "alabuga" else AREA_INFO[key]["name"]
            box = QCheckBox(label)
            self.area_boxes[key] = box
            geo_layout.addWidget(box, i // 2, i % 2)
        self.exp_boxes: dict[str, QCheckBox] = {}
        for i, (key, label) in enumerate(EXPERIENCE_INFO.items()):
            if key in ("noExperience", "between1And3"):
                box = QCheckBox(label)
                self.exp_boxes[key] = box
                geo_layout.addWidget(box, 2 + i, 0, 1, 2)
        root.addWidget(geo)

        cats = QGroupBox("Направления и широкий поиск")
        cats_layout = QGridLayout(cats)
        self.group_boxes: dict[str, QCheckBox] = {}
        for i, name in enumerate(KEYWORD_GROUPS):
            box = QCheckBox(name)
            self.group_boxes[name] = box
            cats_layout.addWidget(box, i // 2, i % 2)
        self.broad_box = QCheckBox("Широкие текстовые запросы (все свежие вакансии, стажировки, офис, производство и т.д.)")
        self.roles_box = QCheckBox("Широкие категории профессиональных ролей HH")
        self.alabuga_box = QCheckBox("Отдельные запросы по ОЭЗ «Алабуга»")
        cats_layout.addWidget(self.broad_box, 4, 0, 1, 2)
        cats_layout.addWidget(self.roles_box, 5, 0, 1, 2)
        cats_layout.addWidget(self.alabuga_box, 6, 0, 1, 2)
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("Дополнительные ключевые слова через запятую или с новой строки")
        cats_layout.addWidget(QLabel("Свои ключевые слова"), 7, 0)
        cats_layout.addWidget(self.custom_edit, 7, 1)
        root.addWidget(cats)

        search_box = QGroupBox("Частота, глубина поиска и фильтры")
        form = QFormLayout(search_box)
        self.period_spin = QSpinBox(); self.period_spin.setRange(1, 90); self.period_spin.setSuffix(" дн.")
        self.pages_spin = QSpinBox(); self.pages_spin.setRange(1, 10); self.pages_spin.setSuffix(" стр.")
        self.details_spin = QSpinBox(); self.details_spin.setRange(0, 1000); self.details_spin.setSuffix(" карт.")
        self.delay_spin = QDoubleSpinBox(); self.delay_spin.setRange(0.35, 5.0); self.delay_spin.setSingleStep(0.1); self.delay_spin.setSuffix(" с")
        self.concurrency_spin = QSpinBox(); self.concurrency_spin.setRange(1, 6)
        self.refresh_combo = QComboBox()
        for value, label in [(0, "Выключено"), (15, "15 минут"), (30, "30 минут"), (60, "1 час"),
                             (120, "2 часа"), (240, "4 часа"), (480, "8 часов"), (1440, "24 часа")]:
            self.refresh_combo.addItem(label, value)
        self.auto_box = QCheckBox("Автоматически обновлять результаты")
        self.web_box = QCheckBox("Разрешить щадящий резервный режим публичных страниц hh.ru при 403 API")
        self.strict_box = QCheckBox("Исключать вакансии с фактическим опытом более 3 лет (проверять описание)")
        self.excluded_box = QCheckBox("Показывать исключённые вакансии")
        self.no_salary_box = QCheckBox("Показывать вакансии без указанной зарплаты")
        self.target_only_box = QCheckBox("По умолчанию показывать только целевые города и удалённые вакансии")
        self.min_salary_spin = QSpinBox(); self.min_salary_spin.setRange(0, 1_000_000); self.min_salary_spin.setSingleStep(5000); self.min_salary_spin.setSuffix(" ₽/мес")
        self.prefer_api_box = QCheckBox("Сначала пробовать официальный API (рекомендуется)")
        for label, widget in [
            ("Период поиска", self.period_spin), ("Страниц на запрос", self.pages_spin),
            ("Описаний за запуск", self.details_spin), ("Пауза между запросами", self.delay_spin),
            ("Параллельных запросов", self.concurrency_spin), ("Периодичность обновления", self.refresh_combo),
            ("Минимальная зарплата", self.min_salary_spin),
        ]:
            form.addRow(label, widget)
        for box in (
            self.auto_box, self.web_box, self.strict_box, self.excluded_box,
            self.no_salary_box, self.target_only_box, self.prefer_api_box,
        ):
            form.addRow("", box)
        web_note = QLabel(
            "Резервный режим — однопользовательский и ограниченный по частоте. "
            "robots.txt hh.ru не рекомендует массовый обход URL с параметрами для общих краулеров; "
            "при получении OAuth-токена приложение автоматически использует официальный API."
        )
        web_note.setObjectName("hint")
        web_note.setWordWrap(True)
        form.addRow("", web_note)
        root.addWidget(search_box)

        api = QGroupBox("Официальный API HeadHunter")
        api_form = QFormLayout(api)
        self.token_edit = QLineEdit(); self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Bearer access_token приложения или пользователя")
        self.client_id_edit = QLineEdit(); self.client_id_edit.setPlaceholderText("client_id из dev.hh.ru")
        self.client_secret_edit = QLineEdit(); self.client_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret_edit.setPlaceholderText("client_secret из dev.hh.ru")
        self.ua_edit = QLineEdit()
        api_form.addRow("Access token", self.token_edit)
        api_form.addRow("Client ID", self.client_id_edit)
        api_form.addRow("Client secret", self.client_secret_edit)
        api_form.addRow("HH-User-Agent", self.ua_edit)
        api_buttons = QHBoxLayout()
        test_btn = QPushButton("Проверить доступ к API")
        test_btn.clicked.connect(self.testApi.emit)
        token_btn = QPushButton("Получить токен приложения")
        token_btn.clicked.connect(lambda: self.getToken.emit(self.client_id_edit.text().strip(), self.client_secret_edit.text().strip()))
        api_buttons.addWidget(test_btn)
        api_buttons.addWidget(token_btn)
        api_buttons.addStretch(1)
        api_form.addRow("", api_buttons)
        root.addWidget(api)

        action_row = QHBoxLayout()
        save_btn = QPushButton("Сохранить настройки")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.save)
        run_btn = QPushButton("Запустить поиск сейчас")
        run_btn.clicked.connect(self.runNow.emit)
        action_row.addWidget(save_btn)
        action_row.addWidget(run_btn)
        action_row.addStretch(1)
        root.addLayout(action_row)

        history = QGroupBox("История поисковых запросов")
        history_layout = QVBoxLayout(history)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Дата", "Запрос", "Найдено", "Страниц", "Ошибка"])
        self.history_table.verticalHeader().hide()
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.setMinimumHeight(240)
        history_layout.addWidget(self.history_table)
        root.addWidget(history)
        root.addStretch(1)
        self.load_settings()

    def load_settings(self) -> None:
        s = self.settings
        for key, box in self.area_boxes.items():
            box.setChecked(bool(s.areas.get(key, False)))
        for key, box in self.exp_boxes.items():
            box.setChecked(bool(s.experience.get(key, False)))
        for key, box in self.group_boxes.items():
            box.setChecked(bool(s.enabled_groups.get(key, True)))
        self.broad_box.setChecked(s.broad_enabled)
        self.roles_box.setChecked(s.role_categories_enabled)
        self.alabuga_box.setChecked(s.alabuga_enabled)
        self.custom_edit.setText(s.custom_keywords)
        self.period_spin.setValue(s.search_period_days)
        self.pages_spin.setValue(s.pages_per_query)
        self.details_spin.setValue(s.max_details_per_run)
        self.delay_spin.setValue(s.request_delay)
        self.concurrency_spin.setValue(s.max_concurrency)
        idx = self.refresh_combo.findData(s.refresh_minutes)
        self.refresh_combo.setCurrentIndex(max(0, idx))
        self.auto_box.setChecked(s.auto_refresh)
        self.web_box.setChecked(s.allow_web_fallback)
        self.strict_box.setChecked(s.strict_max_experience)
        self.excluded_box.setChecked(s.show_excluded)
        self.no_salary_box.setChecked(s.include_no_salary)
        self.target_only_box.setChecked(s.only_target_cities)
        self.min_salary_spin.setValue(s.min_salary)
        self.prefer_api_box.setChecked(s.prefer_api)
        self.token_edit.setText(s.api_access_token)
        self.client_id_edit.setText(s.api_client_id)
        self.client_secret_edit.setText(s.api_client_secret)
        self.ua_edit.setText(s.api_user_agent)

    def collect_settings(self) -> Settings:
        s = self.settings
        s.areas = {key: box.isChecked() for key, box in self.area_boxes.items()}
        s.experience = {key: box.isChecked() for key, box in self.exp_boxes.items()}
        s.enabled_groups = {key: box.isChecked() for key, box in self.group_boxes.items()}
        s.broad_enabled = self.broad_box.isChecked()
        s.role_categories_enabled = self.roles_box.isChecked()
        s.alabuga_enabled = self.alabuga_box.isChecked()
        s.custom_keywords = self.custom_edit.text()
        s.search_period_days = self.period_spin.value()
        s.pages_per_query = self.pages_spin.value()
        s.max_details_per_run = self.details_spin.value()
        s.request_delay = self.delay_spin.value()
        s.max_concurrency = self.concurrency_spin.value()
        s.refresh_minutes = int(self.refresh_combo.currentData() or 0)
        s.auto_refresh = self.auto_box.isChecked()
        s.allow_web_fallback = self.web_box.isChecked()
        s.strict_max_experience = self.strict_box.isChecked()
        s.show_excluded = self.excluded_box.isChecked()
        s.include_no_salary = self.no_salary_box.isChecked()
        s.only_target_cities = self.target_only_box.isChecked()
        s.min_salary = self.min_salary_spin.value()
        s.prefer_api = self.prefer_api_box.isChecked()
        s.api_access_token = self.token_edit.text().strip()
        s.api_client_id = self.client_id_edit.text().strip()
        s.api_client_secret = self.client_secret_edit.text().strip()
        s.api_user_agent = self.ua_edit.text().strip() or "HHJobFinder/1.0 (contact: user@localhost)"
        s.validate()
        return s

    def save(self) -> None:
        self.settingsSaved.emit(self.collect_settings())

    def set_api_status(self, text: str) -> None:
        self.api_status.setText(shorten(text, 500))

    def set_token(self, token: str) -> None:
        self.token_edit.setText(token)
        self.settings.api_access_token = token

    def set_history(self, queries: Iterable[Any]) -> None:
        rows = list(queries)
        self.history_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            data = dict(row) if not isinstance(row, dict) else row
            values = [
                human_date(data.get("created_at"), True),
                str(data.get("query", "")),
                str(data.get("found", 0)),
                str(data.get("pages", 0)),
                shorten(str(data.get("error", "")), 80),
            ]
            for j, value in enumerate(values):
                self.history_table.setItem(i, j, QTableWidgetItem(value))
        self.history_table.resizeRowsToContents()
