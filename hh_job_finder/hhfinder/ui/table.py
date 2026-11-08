"""Виртуализированная таблица вакансий с делегатом оценки."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableView,
    QWidget,
)

from ..models import Vacancy
from ..utils import human_date, parse_iso_date
from .theme import COLORS
from .widgets import salary_text, score_color

HEADERS = [
    "Оценка", "Должность", "Компания", "Зарплата", "Город",
    "Опыт", "Формат", "Опубликовано", "★",
]


class VacancyTableModel(QAbstractTableModel):
    def __init__(self, items: list[Vacancy] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.items = list(items or [])

    def set_items(self, items: list[Vacancy]) -> None:
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.items)):
            return None
        v = self.items[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.UserRole:
            return v
        if role == Qt.ItemDataRole.DisplayRole:
            values = [
                str(int(v.score)),
                v.title or "Без названия",
                v.company or "—",
                salary_text(v),
                v.city or "—",
                v.experience or "—",
                v.work_format or "—",
                human_date(v.published_at),
                "★" if v.is_favorite else "☆",
            ]
            return values[col]
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 0:
                return v.score_explanation or "Оценка соответствия профилю"
            if col == 1:
                return f"{v.title}\n{v.company}\n{v.score_explanation}"
            if col == 3:
                return v.salary_display or "Зарплата не указана"
            if col == 8:
                return "Нажмите, чтобы добавить/убрать из избранного"
            return None
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return QBrush(QColor(score_color(v.score)))
            if col == 3 and v.no_salary:
                return QBrush(QColor(COLORS["amber"]))
            if col == 8 and v.is_favorite:
                return QBrush(QColor(COLORS["amber"]))
            if col in (2, 7):
                return QBrush(QColor(COLORS["muted"]))
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 6, 7, 8):
                return int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.FontRole and col == 0:
            font = QFont()
            font.setBold(True)
            return font
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(HEADERS):
            return HEADERS[section]
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.DescendingOrder) -> None:
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        if column == 0:
            self.items.sort(key=lambda v: v.score, reverse=reverse)
        elif column == 1:
            self.items.sort(key=lambda v: v.title.lower(), reverse=reverse)
        elif column == 2:
            self.items.sort(key=lambda v: v.company.lower(), reverse=reverse)
        elif column == 3:
            self.items.sort(key=lambda v: v.salary_monthly_rub or 0, reverse=reverse)
        elif column == 4:
            self.items.sort(key=lambda v: v.city.lower(), reverse=reverse)
        elif column == 5:
            self.items.sort(key=lambda v: v.experience.lower(), reverse=reverse)
        elif column == 6:
            self.items.sort(key=lambda v: v.work_format.lower(), reverse=reverse)
        elif column == 7:
            self.items.sort(
                key=lambda v: parse_iso_date(v.published_at) or parse_iso_date("1970-01-01"),
                reverse=reverse,
            )
        elif column == 8:
            self.items.sort(key=lambda v: int(v.is_favorite), reverse=reverse)
        self.layoutChanged.emit()

    def update_favorite(self, vacancy_id: str, value: bool) -> None:
        for row, v in enumerate(self.items):
            if v.id == vacancy_id:
                v.is_favorite = value
                self.dataChanged.emit(self.index(row, 8), self.index(row, 8))
                break


class ScoreDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:  # noqa: N802
        v = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(v, Vacancy):
            super().paint(painter, option, index)
            return
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#243a50"))
        rect = option.rect.adjusted(10, 17, -10, -17)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1d2a3d"))
        painter.drawRoundedRect(rect, 6, 6)
        width = max(4, int(rect.width() * min(100, max(0, v.score)) / 100))
        fill = rect.adjusted(0, 0, -(rect.width() - width), 0)
        painter.setBrush(QColor(score_color(v.score)))
        painter.drawRoundedRect(fill, 6, 6)
        # Светлая «таблетка» поверх шкалы: обе цифры одинаково читаются
        # независимо от длины закрашенной части.
        center = option.rect.center()
        pill = QRectF(center.x() - 19, center.y() - 10, 38, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#eaf2ff"))
        painter.drawRoundedRect(pill, 7, 7)
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor("#07141a"))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, str(int(v.score)))
        painter.restore()


class VacancyTableView(QTableView):
    rowSelected = Signal(object)
    favoriteToggled = Signal(str, bool)
    openRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.model_ = VacancyTableModel([], self)
        self.setModel(self.model_)
        self.setItemDelegateForColumn(0, ScoreDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(54)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        header = self.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        for col in (0, 4, 5, 6, 7, 8):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 92)
        self.setColumnWidth(3, 190)
        self.setColumnWidth(8, 44)
        # Формат и дата полностью видны в панели деталей; скрываем их в узкой
        # таблице, чтобы названия должности и компании не обрезались.
        self.setColumnHidden(6, True)
        self.setColumnHidden(7, True)
        header.sortIndicatorChanged.connect(self.model_.sort)
        self.clicked.connect(self._on_clicked)
        self.doubleClicked.connect(self._on_double_clicked)
        self.selectionModel().currentRowChanged.connect(self._on_current_changed)

    def set_items(self, items: list[Vacancy]) -> None:
        self.model_.set_items(items)
        self.clearSelection()
        if items:
            self.selectRow(0)
            self.scrollToTop()

    def items(self) -> list[Vacancy]:
        return self.model_.items

    def selected_vacancy(self) -> Vacancy | None:
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        value = idx.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, Vacancy) else None

    def update_favorite(self, vacancy_id: str, value: bool) -> None:
        self.model_.update_favorite(vacancy_id, value)

    def _on_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        v = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(v, Vacancy):
            return
        if index.column() == 8:
            self.favoriteToggled.emit(v.id, not v.is_favorite)
        else:
            self.rowSelected.emit(v)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        v = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(v, Vacancy):
            self.openRequested.emit(v.url)

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if current.isValid():
            self.rowSelected.emit(current.data(Qt.ItemDataRole.UserRole))
        else:
            self.rowSelected.emit(None)
