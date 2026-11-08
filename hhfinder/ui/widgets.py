"""Переиспользуемые виджеты: оценки, графики, KPI и карточки вакансий."""
from __future__ import annotations

import math
from typing import Iterable

from PySide6.QtCore import (
    QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..models import Vacancy
from ..utils import human_date, shorten
from .theme import COLORS


def score_color(score: float) -> str:
    if score >= 80:
        return COLORS["accent"]
    if score >= 60:
        return COLORS["blue"]
    if score >= 40:
        return COLORS["amber"]
    return COLORS["red"]


def salary_text(v: Vacancy) -> str:
    if v.no_salary or not v.salary_display:
        return "Без з/п"
    return shorten(v.salary_display, 34)


class ScoreBadge(QWidget):
    def __init__(self, score: float = 0, diameter: int = 64, parent: QWidget | None = None):
        super().__init__(parent)
        self.score = float(score)
        self.diameter = diameter
        self.setFixedSize(diameter, diameter)
        self.setToolTip("Оценка соответствия профилю: 0–100")

    def set_score(self, score: float) -> None:
        self.score = max(0.0, min(100.0, float(score)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin = 6
        rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        pen = QPen(QColor("#2a374c"))
        pen.setWidth(7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -360 * 16)
        color = QColor(score_color(self.score))
        pen.setColor(color)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, int(-360 * 16 * self.score / 100))
        painter.setPen(QColor(COLORS["text"]))
        font = QFont()
        font.setPointSize(max(11, int(self.diameter / 4.2)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, h * 0.20, w, h * 0.52), Qt.AlignmentFlag.AlignCenter, str(int(round(self.score))))
        painter.setPen(QColor(COLORS["muted"]))
        small = QFont()
        small.setPointSize(max(7, int(self.diameter / 9)))
        painter.setFont(small)
        painter.drawText(QRectF(0, h * 0.66, w, h * 0.20), Qt.AlignmentFlag.AlignCenter, "/ 100")


class BarChart(QWidget):
    barClicked = Signal(str)

    def __init__(self, title: str = "", parent: QWidget | None = None, color: str | None = None):
        super().__init__(parent)
        self.title = title
        self.values: list[tuple[str, float]] = []
        self.unit = ""
        self.color = color or COLORS["accent"]
        self._progress = 1.0
        self._rects: list[tuple[QRectF, str]] = []
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(520)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_animation)
        self.setMinimumHeight(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_values(self, values: Iterable[tuple[str, float]], unit: str = "", color: str | None = None) -> None:
        self.values = [(str(k), float(v)) for k, v in values if str(k)]
        self.unit = unit
        self.color = color or COLORS["accent"]
        self._progress = 0.0
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self.update()

    def _on_animation(self, value) -> None:
        self._progress = float(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.setPen(QColor(COLORS["text"]))
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(12, 20, self.title)
        if not self.values:
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(12, 50, "Нет данных")
            return
        top = 36
        available = max(40, h - top - 10)
        n = len(self.values)
        row_h = min(28, available / n)
        bar_h = min(13, row_h - 6)
        label_w = min(185, max(120, w * 0.36))
        value_w = 58
        bar_x = label_w + 8
        bar_w = max(20, w - bar_x - value_w - 12)
        max_value = max((abs(v) for _, v in self.values), default=1.0) or 1.0
        small_font = QFont()
        small_font.setPointSize(9)
        painter.setFont(small_font)
        self._rects = []
        for i, (label, value) in enumerate(self.values):
            y = top + i * row_h
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(QRectF(6, y, label_w - 4, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shorten(label, 28))
            bg = QRectF(bar_x, y + (row_h - bar_h) / 2, bar_w, bar_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1d2a3d"))
            painter.drawRoundedRect(bg, bar_h / 2, bar_h / 2)
            length = bar_w * min(1.0, abs(value) / max_value) * self._progress
            fill = QRectF(bar_x, bg.y(), length, bar_h)
            painter.setBrush(QColor(self.color))
            painter.drawRoundedRect(fill, bar_h / 2, bar_h / 2)
            painter.setPen(QColor(COLORS["text"]))
            text = f"{value:g}{self.unit}"
            painter.drawText(QRectF(bar_x + bar_w + 5, y, value_w, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            self._rects.append((QRectF(6, y, w - 12, row_h), label))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        point = QPointF(event.position()) if hasattr(event, "position") else QPointF(event.pos())
        for rect, label in self._rects:
            if rect.contains(point):
                self.barClicked.emit(label)
                return
        super().mousePressEvent(event)


class FactorBars(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.factors: dict[str, float] = {}
        self.setMinimumHeight(180)

    def set_factors(self, factors: dict[str, float]) -> None:
        self.factors = factors or {}
        self.setMinimumHeight(max(80, 23 * len(self.factors) + 24))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.factors:
            return
        labels = {
            "base": "База", "skills": "Навыки", "role": "Профиль роли",
            "realism": "Реалистичность", "salary": "Зарплата",
            "conditions": "Условия", "location": "География", "alignment": "Штрафы",
        }
        w, h = self.width(), self.height()
        row_h = min(25, (h - 16) / len(self.factors))
        label_w = 115
        center_x = label_w + (w - label_w - 55) / 2
        half = max(30, (w - label_w - 75) / 2)
        scale = max((abs(x) for x in self.factors.values()), default=1.0) or 1.0
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        for i, (key, value) in enumerate(self.factors.items()):
            y = 8 + i * row_h
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(QRectF(4, y, label_w - 6, row_h), Qt.AlignmentFlag.AlignVCenter, labels.get(key, key))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1d2a3d"))
            painter.drawRoundedRect(QRectF(center_x - half, y + row_h / 2 - 5, half * 2, 10), 5, 5)
            length = half * min(1.0, abs(value) / scale)
            color = QColor(COLORS["red"] if value < 0 else COLORS["accent"])
            painter.setBrush(color)
            if value >= 0:
                bar = QRectF(center_x, y + row_h / 2 - 5, length, 10)
            else:
                bar = QRectF(center_x - length, y + row_h / 2 - 5, length, 10)
            painter.drawRoundedRect(bar, 5, 5)
            painter.setPen(QColor(COLORS["text"]))
            painter.drawText(QRectF(w - 48, y, 44, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{value:+g}")


class StatTile(QFrame):
    def __init__(self, title: str, value: str = "—", subtitle: str = "", accent: str | None = None):
        super().__init__()
        self.setObjectName("card")
        self.setFixedHeight(104)
        self.accent = accent or COLORS["accent"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("muted")
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"font-size: 25px; font-weight: 700; color: {self.accent};")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("hint")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.subtitle_label)
        layout.addStretch(1)

    def set_value(self, value: str, subtitle: str = "") -> None:
        self.value_label.setText(value)
        if subtitle:
            self.subtitle_label.setText(subtitle)


def chip(text: str, accent: bool = False, warn: bool = False) -> QLabel:
    label = QLabel(shorten(text, 48))
    label.setObjectName("chipAccent" if accent else "chipWarn" if warn else "chip")
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return label


class VacancyCard(QFrame):
    selected = Signal(str)
    favoriteClicked = Signal(str, bool)
    openClicked = Signal(str)

    def __init__(self, vacancy: Vacancy, parent: QWidget | None = None):
        super().__init__(parent)
        self.v = vacancy
        self.setObjectName("vacancyCard")
        self.setFixedHeight(152)
        self.setProperty("selected", False)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(14)
        self.badge = ScoreBadge(vacancy.score, 64)
        root.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)

        center = QVBoxLayout()
        center.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(vacancy.title or "Без названия")
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        top.addWidget(title, 1)
        self.fav_btn = QPushButton("★" if vacancy.is_favorite else "☆")
        self.fav_btn.setObjectName("icon")
        self.fav_btn.setFixedWidth(34)
        self.fav_btn.setToolTip("Добавить/убрать из избранного")
        self.fav_btn.clicked.connect(self._fav)
        self.open_btn = QPushButton("↗")
        self.open_btn.setObjectName("icon")
        self.open_btn.setFixedWidth(34)
        self.open_btn.setToolTip("Открыть вакансию на hh.ru")
        self.open_btn.clicked.connect(lambda: self.openClicked.emit(self.v.url))
        top.addWidget(self.fav_btn)
        top.addWidget(self.open_btn)
        center.addLayout(top)

        company = QLabel(vacancy.company or "Компания не указана")
        company.setObjectName("muted")
        center.addWidget(company)
        meta = "  •  ".join(x for x in [
            salary_text(vacancy), vacancy.city, vacancy.experience or "Опыт не указан",
            vacancy.work_format or "Формат не указан",
        ] if x)
        meta_label = QLabel(meta)
        meta_label.setStyleSheet(f"color: {COLORS['blue'] if not vacancy.no_salary else COLORS['amber']}; font-weight: 600;")
        meta_label.setWordWrap(False)
        center.addWidget(meta_label)
        explanation = QLabel(vacancy.score_explanation or "Оценка пока без объяснения: описание ещё не загружено.")
        explanation.setObjectName("hint")
        explanation.setWordWrap(True)
        explanation.setMaximumHeight(34)
        explanation.setToolTip(vacancy.score_explanation)
        center.addWidget(explanation)
        root.addLayout(center, 1)

        chips = QVBoxLayout()
        chips.setSpacing(5)
        chips.addWidget(chip(vacancy.category, accent=True))
        if vacancy.is_new:
            new_label = QLabel("НОВАЯ")
            new_label.setObjectName("chipAccent")
            chips.addWidget(new_label)
        if vacancy.no_salary:
            chips.addWidget(chip("Без з/п", warn=True))
        if not vacancy.enriched:
            chips.addWidget(chip("Краткая карточка", warn=True))
        chips.addStretch(1)
        root.addLayout(chips)

    def _fav(self) -> None:
        self.favoriteClicked.emit(self.v.id, not self.v.is_favorite)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.selected.emit(self.v.id)
        super().mousePressEvent(event)

    def set_selected(self, value: bool) -> None:
        self.setProperty("selected", bool(value))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
