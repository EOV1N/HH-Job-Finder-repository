"""Универсальный просмотрщик: таблица или карточки + панель деталей."""
from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QListWidget, QListWidgetItem, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..models import Vacancy
from .detail import VacancyDetailPanel
from .table import VacancyTableView
from .widgets import VacancyCard

ChangesProvider = Callable[[str], Iterable] | None


class VacancyBrowser(QWidget):
    favoriteToggled = Signal(str, bool)
    openRequested = Signal(str)
    exportRequested = Signal(object)

    def __init__(self, mode: str = "table", changes_provider: ChangesProvider = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.mode = "cards" if mode == "cards" else "table"
        self.items: list[Vacancy] = []
        self.changes_provider = changes_provider
        self.card_widgets: dict[str, VacancyCard] = {}
        self.selected_id: str | None = None

        self.stack = QStackedWidget()
        self.table = VacancyTableView()
        self.cards = QListWidget()
        self.cards.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.cards.setSpacing(4)
        self.cards.setUniformItemSizes(True)
        self.cards.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.cards)
        self.detail = VacancyDetailPanel()
        self.stack.setCurrentIndex(1 if self.mode == "cards" else 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.stack)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 380])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.table.rowSelected.connect(self._on_table_selected)
        self.table.favoriteToggled.connect(self._on_favorite)
        self.table.openRequested.connect(self.openRequested.emit)
        self.cards.itemClicked.connect(self._on_card_item_clicked)
        self.detail.favoriteToggled.connect(self._on_favorite)
        self.detail.openRequested.connect(self.openRequested.emit)
        self.detail.exportRequested.connect(self.exportRequested.emit)

    # ---------- данные ----------
    def set_items(self, items: list[Vacancy]) -> None:
        self.items = list(items)
        self.table.set_items(self.items)
        if self.mode == "cards":
            self._populate_cards(self.items[:45])
        if self.items:
            self._show_detail(self.items[0])
        else:
            self.selected_id = None
            self.detail.clear()

    def _populate_cards(self, items: list[Vacancy]) -> None:
        self.cards.clear()
        self.card_widgets = {}
        for v in items:
            card = VacancyCard(v)
            card.selected.connect(self.select_vacancy)
            card.favoriteClicked.connect(self._on_favorite)
            card.openClicked.connect(self.openRequested.emit)
            item = QListWidgetItem()
            item.setSizeHint(QSize(720, 162))
            self.cards.addItem(item)
            self.cards.setItemWidget(item, card)
            self.card_widgets[v.id] = card

    def set_changes_provider(self, provider: ChangesProvider) -> None:
        self.changes_provider = provider

    def changes_for(self, vacancy_id: str) -> list:
        if self.changes_provider is None:
            return []
        try:
            return list(self.changes_provider(vacancy_id))
        except Exception:
            return []

    def _show_detail(self, v: Vacancy | None) -> None:
        if v is None:
            self.selected_id = None
            self.detail.clear()
            return
        self.selected_id = v.id
        for vid, card in self.card_widgets.items():
            card.set_selected(vid == v.id)
        self.detail.set_vacancy(v, self.changes_for(v.id))

    # ---------- сигналы ----------
    def _on_table_selected(self, v: Vacancy | None) -> None:
        self._show_detail(v)

    def _on_card_item_clicked(self, item: QListWidgetItem) -> None:
        widget = self.cards.itemWidget(item)
        if isinstance(widget, VacancyCard):
            self.select_vacancy(widget.v.id)

    def select_vacancy(self, vacancy_id: str) -> None:
        v = next((x for x in self.items if x.id == vacancy_id), None)
        if v:
            self._show_detail(v)

    def _on_favorite(self, vacancy_id: str, value: bool) -> None:
        self.update_favorite_local(vacancy_id, value)
        self.favoriteToggled.emit(vacancy_id, value)

    def update_favorite_local(self, vacancy_id: str, value: bool) -> None:
        for v in self.items:
            if v.id == vacancy_id:
                v.is_favorite = value
                self._show_detail(v)
                break
        self.table.update_favorite(vacancy_id, value)
        card = self.card_widgets.get(vacancy_id)
        if card:
            card.v.is_favorite = value
            card.fav_btn.setText("★" if value else "☆")

    def selected_vacancy(self) -> Vacancy | None:
        return next((v for v in self.items if v.id == self.selected_id), None)

    def item_count(self) -> int:
        return len(self.items)
