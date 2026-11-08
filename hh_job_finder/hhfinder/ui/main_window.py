"""Главное окно PySide6: навигация, фильтры, фоновые задачи и экспорт."""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsOpacityEffect,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import DEFAULT_RATES, EXPORT_DIR, Settings
from ..db import Database
from ..exporters import export_vacancies
from ..filters import SORT_OPTIONS, FilterState, apply_filters, unique_options
from ..models import Vacancy
from .browser import VacancyBrowser
from .pages import CategoriesPage, HomePage, SettingsPage
from .theme import COLORS
from .workers import ApiTestWorker, SearchWorker, TokenWorker

logger = logging.getLogger(__name__)
PAGE_TITLES = [
    "Главная", "Все вакансии", "Лучшие совпадения",
    "Категории", "Избранное", "Настройки",
]
NAV_LABELS = [
    "⌂   Главная", "▦   Все вакансии", "✦   Лучшие совпадения",
    "◫   Категории", "★   Избранное", "⚙   Настройки",
]


class MainWindow(QMainWindow):
    shouldClose = Signal()

    def __init__(self, settings: Settings, db: Database, no_auto: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        self.no_auto = no_auto
        self.all_vacancies: list[Vacancy] = []
        self.stats: dict = {}
        self.worker: SearchWorker | None = None
        self.aux_workers: list = []
        self._initial_scan_done = False
        self.setWindowTitle("HH Job Finder — Набережные Челны • Елабуга • Алабуга")
        self.resize(1560, 960)
        self.setMinimumSize(1120, 720)
        self._build_ui()
        self._connect_signals()
        self.switch_page(0)
        self.reload_data()
        QTimer.singleShot(250, self._after_start)

    # ---------- построение интерфейса ----------
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(248)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(16, 20, 16, 18)
        side_layout.setSpacing(8)
        logo = QLabel("HH Job Finder")
        logo.setObjectName("logo")
        side_layout.addWidget(logo)
        subtitle = QLabel("Поиск работы для начинающего IT-специалиста")
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)
        side_layout.addWidget(subtitle)
        geo = QLabel("Набережные Челны\nЕлабуга • ОЭЗ «Алабуга»")
        geo.setObjectName("hint")
        geo.setWordWrap(True)
        side_layout.addWidget(geo)
        side_layout.addSpacing(16)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for i, label in enumerate(NAV_LABELS):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(button, i)
            self.nav_buttons.append(button)
            side_layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)
        side_layout.addStretch(1)

        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(12, 12, 12, 12)
        status_layout.setSpacing(5)
        status_title = QLabel("СТАТУС")
        status_title.setObjectName("hint")
        self.sidebar_new = QLabel("Новых: 0")
        self.sidebar_new.setObjectName("badgeNew")
        self.sidebar_source = QLabel("Источник: —")
        self.sidebar_source.setObjectName("hint")
        self.sidebar_source.setWordWrap(True)
        status_layout.addWidget(status_title)
        status_layout.addWidget(self.sidebar_new)
        status_layout.addWidget(self.sidebar_source)
        side_layout.addWidget(status_card)
        root.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(70)
        top = QHBoxLayout(topbar)
        top.setContentsMargins(22, 12, 22, 12)
        top.setSpacing(12)
        self.page_title = QLabel("Главная")
        self.page_title.setObjectName("pageTitle")
        top.addWidget(self.page_title)
        self.new_badge = QLabel("Новых: 0")
        self.new_badge.setObjectName("badgeNew")
        top.addWidget(self.new_badge)
        top.addStretch(1)
        self.source_status = QLabel("")
        self.source_status.setObjectName("hint")
        top.addWidget(self.source_status)
        self.search_btn = QPushButton("⟳  Обновить")
        self.search_btn.setObjectName("primary")
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn = QPushButton("Экспорт")
        self.mark_seen_btn = QPushButton("Прочитано")
        top.addWidget(self.mark_seen_btn)
        top.addWidget(self.export_btn)
        top.addWidget(self.search_btn)
        right_layout.addWidget(topbar)

        self.filterbar = QFrame()
        self.filterbar.setObjectName("filterbar")
        filters = QHBoxLayout(self.filterbar)
        filters.setContentsMargins(22, 10, 22, 10)
        filters.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по должности, компании, описанию…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(260)
        filters.addWidget(self.search_edit, 2)
        self.category_combo = QComboBox()
        self.city_combo = QComboBox()
        self.format_combo = QComboBox()
        self.sort_combo = QComboBox()
        for key, label in SORT_OPTIONS:
            self.sort_combo.addItem(label, key)
        for combo in (self.category_combo, self.city_combo, self.format_combo, self.sort_combo):
            combo.setMinimumWidth(140)
            filters.addWidget(combo, 1)
        self.min_salary_spin = QSpinBox()
        self.min_salary_spin.setRange(0, 1_000_000)
        self.min_salary_spin.setSingleStep(5000)
        self.min_salary_spin.setPrefix("от ")
        self.min_salary_spin.setSuffix(" ₽")
        self.min_salary_spin.setMaximumWidth(130)
        filters.addWidget(self.min_salary_spin)
        self.no_salary_box = QCheckBox("Без з/п")
        self.target_box = QCheckBox("Целевой регион")
        self.new_box = QCheckBox("Новые")
        self.excluded_box = QCheckBox("Исключённые")
        for box in (self.no_salary_box, self.target_box, self.new_box, self.excluded_box):
            filters.addWidget(box)
        reset_btn = QPushButton("Сброс")
        reset_btn.setObjectName("icon")
        filters.addWidget(reset_btn)
        self.reset_btn = reset_btn
        right_layout.addWidget(self.filterbar)

        self.stack = QStackedWidget()
        self.home = HomePage()
        self.all_browser = VacancyBrowser("table", self.changes_for)
        self.best_browser = VacancyBrowser("cards", self.changes_for)
        self.categories = CategoriesPage(self.changes_for)
        self.favorites_browser = VacancyBrowser("table", self.changes_for)
        self.settings_page = SettingsPage(self.settings)
        self.browsers = [
            self.all_browser, self.best_browser, self.categories.browser, self.favorites_browser,
        ]
        for widget in (
            self.home, self.all_browser, self.best_browser, self.categories,
            self.favorites_browser, self.settings_page,
        ):
            self.stack.addWidget(widget)
        right_layout.addWidget(self.stack, 1)

        statusbar = QFrame()
        statusbar.setObjectName("statusbar")
        statusbar.setFixedHeight(42)
        status_layout = QHBoxLayout(statusbar)
        status_layout.setContentsMargins(22, 6, 22, 6)
        status_layout.setSpacing(12)
        self.status_label = QLabel("Готово")
        self.status_label.setObjectName("hint")
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(260)
        self.progress_bar.hide()
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress_bar)
        right_layout.addWidget(statusbar)
        root.addWidget(right, 1)

        # Одна лёгкая анимация при переключении разделов, без анимации каждой строки.
        self.fade_effect = QGraphicsOpacityEffect(self.stack)
        self.fade_effect.setOpacity(1.0)
        self.stack.setGraphicsEffect(self.fade_effect)
        self.fade_anim = QPropertyAnimation(self.fade_effect, b"opacity", self)
        self.fade_anim.setDuration(190)
        self.fade_anim.setStartValue(0.65)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.refresh_views)
        self.auto_timer = QTimer(self)
        self.auto_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self.auto_timer.timeout.connect(lambda: self.start_search(False))
        self._restart_auto_timer()

        self.min_salary_spin.setValue(self.settings.min_salary)
        self.no_salary_box.setChecked(self.settings.include_no_salary)
        self.target_box.setChecked(self.settings.only_target_cities)
        self.excluded_box.setChecked(self.settings.show_excluded)

    def _connect_signals(self) -> None:
        for i, button in enumerate(self.nav_buttons):
            button.clicked.connect(lambda _, idx=i: self.switch_page(idx))
        self.search_btn.clicked.connect(self._search_button_clicked)
        self.export_btn.clicked.connect(self.export_current)
        self.mark_seen_btn.clicked.connect(self.mark_seen)
        self.reset_btn.clicked.connect(self.reset_filters)

        for widget in (
            self.search_edit, self.category_combo, self.city_combo, self.format_combo,
            self.sort_combo, self.min_salary_spin, self.no_salary_box, self.target_box,
            self.new_box, self.excluded_box,
        ):
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._filter_changed)
            elif isinstance(widget, (QComboBox, QSpinBox)):
                widget.currentIndexChanged.connect(self._filter_changed) if isinstance(widget, QComboBox) else widget.valueChanged.connect(self._filter_changed)
            else:
                widget.toggled.connect(self._filter_changed)

        for browser in self.browsers:
            browser.favoriteToggled.connect(self.on_favorite_toggled)
            browser.openRequested.connect(self.open_url)
            browser.exportRequested.connect(self.export_single)
        self.home.vacancySelected.connect(self.show_vacancy)
        self.home.showNewRequested.connect(self.show_new_only)
        self.categories.categorySelected.connect(self.on_category_selected)
        self.settings_page.settingsSaved.connect(self.on_settings_saved)
        self.settings_page.runNow.connect(lambda: self.start_search(True))
        self.settings_page.testApi.connect(self.test_api)
        self.settings_page.getToken.connect(self.get_token)

    def _after_start(self) -> None:
        if self._initial_scan_done or self.no_auto:
            return
        self._initial_scan_done = True
        if not self.stats.get("total_all") and self.settings.auto_refresh and self.settings.allow_web_fallback:
            QTimer.singleShot(500, lambda: self.start_search(False))

    # ---------- фильтры и данные ----------
    def _filter_changed(self, *_args) -> None:
        self.filter_timer.start(130)

    def _set_combo(self, combo: QComboBox, values: list[str], current: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(values)
        idx = combo.findText(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def current_filter_state(self) -> FilterState:
        return FilterState(
            search=self.search_edit.text(),
            category=self.category_combo.currentText() or "Все категории",
            city=self.city_combo.currentText() or "Все города",
            work_format=self.format_combo.currentText() or "Все форматы",
            min_salary=self.min_salary_spin.value(),
            include_no_salary=self.no_salary_box.isChecked(),
            only_new=self.new_box.isChecked(),
            only_favorites=False,
            show_excluded=self.excluded_box.isChecked(),
            only_target_cities=self.target_box.isChecked(),
            sort_by=str(self.sort_combo.currentData() or "score_desc"),
        )

    def reset_filters(self) -> None:
        self.search_edit.clear()
        self._set_combo(self.category_combo, ["Все категории"], "Все категории")
        self._set_combo(self.city_combo, ["Все города"], "Все города")
        self._set_combo(self.format_combo, ["Все форматы"], "Все форматы")
        self.sort_combo.setCurrentIndex(0)
        self.min_salary_spin.setValue(0)
        self.no_salary_box.setChecked(self.settings.include_no_salary)
        self.target_box.setChecked(self.settings.only_target_cities)
        self.new_box.setChecked(False)
        self.excluded_box.setChecked(self.settings.show_excluded)
        self.refresh_views()

    def reload_data(self) -> None:
        self.all_vacancies = self.db.get_vacancies(include_excluded=True)
        self.stats = self.db.stats()
        state = self.current_filter_state()
        options = unique_options(self.all_vacancies)
        self._set_combo(self.category_combo, options["categories"], state.category)
        self._set_combo(self.city_combo, options["cities"], state.city)
        self._set_combo(self.format_combo, options["formats"], state.work_format)
        self.refresh_views()
        runs = self.db.get_runs(10)
        queries = []
        for run in runs[:5]:
            try:
                queries.extend(self.db.get_queries(int(run["id"]), 60))
            except Exception:
                continue
        self.settings_page.set_history(queries[:200])
        self._update_header()

    def refresh_views(self) -> None:
        state = self.current_filter_state()
        active = apply_filters(self.all_vacancies, state)
        best = apply_filters(self.all_vacancies, replace(state, sort_by="score_desc"), limit=45)
        favorites = apply_filters(self.all_vacancies, replace(state, only_favorites=True))
        new_items = apply_filters(self.all_vacancies, replace(state, only_new=True, sort_by="date_desc"), limit=12)
        self.all_browser.set_items(active)
        self.best_browser.set_items(best)
        self.favorites_browser.set_items(favorites)
        self.categories.set_data(self.stats, active)
        self.home.set_data(
            self.stats, active, new_items,
            self.db.get_changes(limit=12), self.db.get_runs(8),
        )
        self._update_counts(len(active), len(favorites), len(best))

    def _update_header(self) -> None:
        source = self.stats.get("last_source") or "—"
        label = "официальный API" if source == "hh_api" else "hh.ru (резерв)" if source == "hh_web" else "ещё нет запуска"
        self.source_status.setText(f"{self.stats.get('total', 0)} вакансий • {label}")
        self.sidebar_source.setText(f"Источник: {label}\n{self.stats.get('last_api_status', '')[:110]}")
        new_count = int(self.stats.get("new_count", 0) or 0)
        self.new_badge.setText(f"Новых: {new_count}")
        self.new_badge.setVisible(new_count > 0)
        self.sidebar_new.setText(f"Новых: {new_count}")
        self.mark_seen_btn.setEnabled(new_count > 0)
        total = int(self.stats.get("total", 0) or 0)
        fav = int(self.stats.get("favorites", 0) or 0)
        self.nav_buttons[1].setText(f"▦   Все вакансии  {total}")
        self.nav_buttons[4].setText(f"★   Избранное  {fav}")

    def _update_counts(self, active: int, favorites: int, best: int) -> None:
        self.status_label.setText(
            f"Показано: {active} • избранных: {favorites} • лучших: {best}"
        )

    def changes_for(self, vacancy_id: str):
        return self.db.get_changes(vacancy_id, 10)

    # ---------- навигация ----------
    def switch_page(self, index: int) -> None:
        index = max(0, min(self.stack.count() - 1, int(index)))
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.page_title.setText(PAGE_TITLES[index])
        self.filterbar.setVisible(index not in (0, 5))
        self.fade_anim.stop()
        self.fade_anim.start()
        for browser in self.browsers:
            browser.set_changes_provider(self.changes_for)
        self.categories.set_changes_provider(self.changes_for)

    def set_page(self, name: str) -> None:
        names = ["home", "all", "best", "categories", "favorites", "settings"]
        self.switch_page(names.index(name) if name in names else 0)

    def show_vacancy(self, vacancy_id: str) -> None:
        self.switch_page(1)
        self.all_browser.select_vacancy(vacancy_id)

    def show_new_only(self) -> None:
        self.new_box.setChecked(True)
        self.switch_page(1)
        self.refresh_views()

    def on_category_selected(self, name: str) -> None:
        idx = self.category_combo.findText(name)
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        self.refresh_views()

    # ---------- поиск ----------
    def _search_button_clicked(self) -> None:
        if self.worker and self.worker.isRunning():
            self.stop_search()
        else:
            self.start_search(True)

    def start_search(self, manual: bool = True) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.worker = SearchWorker(self.settings, self.db.path)
        self.worker.progress.connect(self.on_progress)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        # Объект потока сохраняется в self.worker до следующего запуска: это
        # исключает удаление QThread во время завершения фоновых корутин.
        self.worker.start()
        self.search_btn.setText("■  Остановить")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.status_label.setText("Поиск запущен вручную…" if manual else "Автоматическое обновление…")

    def stop_search(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status_label.setText("Останавливаю фоновые запросы…")

    def on_progress(self, message: str, done: int, total: int) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(min(done, max(1, total)))
        self.status_label.setText(message)

    def on_completed(self, summary) -> None:
        self.search_btn.setText("⟳  Обновить")
        self.progress_bar.hide()
        self.reload_data()
        prefix = "Сбор остановлен" if getattr(summary, "cancelled", False) else "Поиск завершён"
        errors = len(getattr(summary, "errors", []) or [])
        self.status_label.setText(
            f"{prefix}: {getattr(summary, 'headline', lambda: '')()}"
            + (f" • ошибок: {errors}" if errors else "")
        )
        self.settings_page.set_api_status(getattr(summary, "api_status", "") or "Сбор завершён")

    def on_failed(self, error: str) -> None:
        self.search_btn.setText("⟳  Обновить")
        self.progress_bar.hide()
        self.status_label.setText(f"Ошибка поиска: {error}")
        logger.error("Поиск завершился ошибкой: %s", error)
        QMessageBox.warning(self, "Ошибка поиска", error[:1000])

    def _restart_auto_timer(self) -> None:
        self.auto_timer.stop()
        if self.no_auto or not self.settings.auto_refresh or self.settings.refresh_minutes <= 0:
            return
        self.auto_timer.start(self.settings.refresh_minutes * 60 * 1000)

    # ---------- действия ----------
    def on_favorite_toggled(self, vacancy_id: str, value: bool) -> None:
        self.db.set_favorite(vacancy_id, value)
        self.reload_data()
        self.status_label.setText("Добавлено в избранное" if value else "Удалено из избранного")

    def open_url(self, url: str) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def mark_seen(self) -> None:
        self.db.mark_seen()
        self.reload_data()
        self.status_label.setText("Новые вакансии отмечены просмотренными")

    def export_single(self, vacancy) -> None:
        self._export_items([vacancy], "Экспорт вакансии")

    def export_current(self) -> None:
        choice, ok = QInputDialog.getItem(
            self, "Экспорт", "Что экспортировать?",
            ["Текущая выборка", "Все вакансии", "Избранное", "Лучшие совпадения"], 0, False,
        )
        if not ok:
            return
        state = self.current_filter_state()
        if choice == "Текущая выборка":
            items = apply_filters(self.all_vacancies, state)
        elif choice == "Все вакансии":
            items = apply_filters(self.all_vacancies, replace(
                state, search="", category="Все категории", city="Все города",
                work_format="Все форматы", min_salary=0, only_new=False, only_favorites=False,
            ))
        elif choice == "Избранное":
            items = apply_filters(self.all_vacancies, replace(
                state, search="", category="Все категории", city="Все города",
                work_format="Все форматы", min_salary=0, only_new=False, only_favorites=True,
            ))
        else:
            items = apply_filters(self.all_vacancies, replace(state, sort_by="score_desc"), limit=100)
        self._export_items(items, "Экспорт вакансий")

    def _export_items(self, items: list[Vacancy], title: str) -> None:
        if not items:
            QMessageBox.information(self, title, "Нет вакансий для экспорта.")
            return
        default = EXPORT_DIR / f"hh_vacancies_{time.strftime('%Y%m%d_%H%M')}.xlsx"
        path, selected = QFileDialog.getSaveFileName(
            self, title, str(default),
            "Excel (*.xlsx);;CSV (*.csv);;JSON (*.json)",
        )
        if not path:
            return
        suffix = ".xlsx" if "Excel" in selected else ".csv" if "CSV" in selected else ".json"
        if not path.lower().endswith(suffix):
            path += suffix
        try:
            export_vacancies(items, Path(path))
            self.status_label.setText(f"Экспортировано {len(items)} вакансий: {path}")
            QMessageBox.information(self, title, f"Готово: {len(items)} вакансий\n{path}")
        except Exception as exc:
            logger.exception("Ошибка экспорта")
            QMessageBox.critical(self, title, str(exc))

    # ---------- настройки и проверка API ----------
    def on_settings_saved(self, updated: Settings) -> None:
        self.settings = updated
        self.settings.save()
        self.settings_page.settings = self.settings
        self.settings_page.load_settings()
        self.min_salary_spin.blockSignals(True)
        self.min_salary_spin.setValue(self.settings.min_salary)
        self.min_salary_spin.blockSignals(False)
        self.no_salary_box.blockSignals(True)
        self.no_salary_box.setChecked(self.settings.include_no_salary)
        self.no_salary_box.blockSignals(False)
        self.target_box.blockSignals(True)
        self.target_box.setChecked(self.settings.only_target_cities)
        self.target_box.blockSignals(False)
        self.excluded_box.blockSignals(True)
        self.excluded_box.setChecked(self.settings.show_excluded)
        self.excluded_box.blockSignals(False)
        self.db.rescore_all(DEFAULT_RATES, self.settings.strict_max_experience)
        self._restart_auto_timer()
        self.reload_data()
        self.status_label.setText("Настройки сохранены, оценки пересчитаны")

    def test_api(self) -> None:
        self.status_label.setText("Проверяю доступ к источникам…")
        worker = ApiTestWorker(self.settings)
        worker.result.connect(self.on_api_test_result)
        self._track_aux(worker)
        worker.start()

    def on_api_test_result(self, result: dict) -> None:
        if "error" in result:
            text = f"Ошибка проверки: {result['error']}"
        else:
            api = result.get("api", {})
            web = result.get("web", {})
            text = (
                f"Официальный API: {'доступен' if api.get('ok') else 'недоступен'}\n"
                f"{api.get('message', '')}\n\n"
                f"Резервный hh.ru: {'доступен' if web.get('ok') else 'недоступен'}\n"
                f"{web.get('message', '')}\n"
                f"{web.get('robots_warning', '')}"
            )
        self.settings_page.set_api_status(text.replace("\n", " • "))
        QMessageBox.information(self, "Проверка источников", text)

    def get_token(self, client_id: str, client_secret: str) -> None:
        if not client_id or not client_secret:
            QMessageBox.warning(
                self, "Токен приложения",
                "Укажите client_id и client_secret приложения, зарегистрированного в dev.hh.ru. "
                "Без зарегистрированного приложения HH не выдаёт токен.",
            )
            return
        worker = TokenWorker(self.settings, client_id, client_secret)
        worker.result.connect(self.on_token_result)
        self._track_aux(worker)
        worker.start()
        self.status_label.setText("Запрашиваю токен приложения…")

    def on_token_result(self, result: dict) -> None:
        if not result.get("ok"):
            QMessageBox.warning(self, "Токен приложения", result.get("error", "Не удалось получить токен"))
            self.status_label.setText("Не удалось получить токен приложения")
            return
        token = result["access_token"]
        self.settings_page.set_token(token)
        self.settings.api_access_token = token
        try:
            self.settings.api_token_expires_at = time.time() + float(result.get("expires_in") or 0)
        except (TypeError, ValueError):
            self.settings.api_token_expires_at = 0.0
        self.settings.save()
        self.status_label.setText("Токен приложения сохранён в локальных настройках")
        QMessageBox.information(
            self, "Токен приложения",
            "Токен получен и сохранён. Нажмите «Проверить доступ к API» и затем «Обновить», "
            "чтобы приложение использовало официальный источник.",
        )

    def _track_aux(self, worker) -> None:
        alive = []
        for existing in self.aux_workers:
            try:
                if existing.isRunning():
                    alive.append(existing)
            except RuntimeError:
                continue
        self.aux_workers = [*alive, worker]

    # ---------- завершение ----------
    def closeEvent(self, event) -> None:  # noqa: N802
        self.auto_timer.stop()
        self.filter_timer.stop()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(15000)
            if self.worker.isRunning():
                logger.warning("Фоновая задача не завершилась вовремя, принудительное завершение потока")
                self.worker.terminate()
                self.worker.wait(3000)
        for worker in self.aux_workers:
            if worker.isRunning():
                worker.wait(5000)
        try:
            self.settings.save()
        except Exception as exc:
            logger.warning("Не удалось сохранить настройки при выходе: %s", exc)
        self.shouldClose.emit()
        event.accept()
