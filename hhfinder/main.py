"""Точка входа, логирование и режим скриншотов для проверки интерфейса."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def setup_logging(log_dir: Path | None = None) -> None:
    root = logging.getLogger()
    if getattr(setup_logging, "_configured", False):
        return
    if log_dir is None:
        from .config import LOG_DIR
        log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    setup_logging._configured = True  # type: ignore[attr-defined]

    def hook(exc_type, exc_value, exc_tb):
        logging.critical("Необработанная ошибка", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = hook


def _capture_one(app: QApplication, window, out_path: Path, page: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if page:
        window.set_page(page)

    def shoot() -> None:
        QApplication.processEvents()
        window.grab().save(str(out_path))
        app.quit()

    QTimer.singleShot(750, shoot)
    app.exec()


def _capture_all(app: QApplication, window, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = ["home", "all", "best", "categories", "favorites", "settings"]

    def save_current(index: int) -> None:
        QApplication.processEvents()
        window.grab().save(str(out_dir / f"{index + 1:02d}_{pages[index]}.png"))
        step(index + 1)

    def step(index: int) -> None:
        if index >= len(pages):
            app.quit()
            return
        window.set_page(pages[index])
        QTimer.singleShot(420, lambda idx=index: save_current(idx))

    QTimer.singleShot(750, lambda: step(0))
    app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HH Job Finder — поиск вакансий HH для начинающего специалиста")
    parser.add_argument("--data-dir", help="Каталог с SQLite, настройками и логами")
    parser.add_argument("--no-auto", action="store_true", help="Не запускать автоматическое обновление")
    parser.add_argument("--screenshot", help="Сохранить один PNG в offscreen-режиме и выйти")
    parser.add_argument("--screenshots", help="Сохранить PNG всех разделов в каталог и выйти")
    parser.add_argument("--page", default="home", help="Раздел для --screenshot: home/all/best/categories/favorites/settings")
    parser.add_argument("--report", help="Сформировать автономный HTML-отчёт из реальной БД и выйти")
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["HHF_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    setup_logging()

    # Импорты config/DB делаются ПОСЛЕ установки HHF_DATA_DIR.
    from .config import DB_PATH, SCREENSHOT_DIR, Settings
    from .db import Database
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    db = Database(DB_PATH)

    if args.report:
        from .report import generate_report
        out = Path(args.report).expanduser().resolve()
        generate_report(db, out)
        print(f"Отчёт сохранён: {out}")
        return 0

    screenshot_mode = bool(args.screenshot or args.screenshots)
    if screenshot_mode:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    settings = Settings.load()
    window = MainWindow(settings, db, no_auto=args.no_auto or screenshot_mode)
    window.resize(1600, 1000)
    window.show()

    if args.screenshots:
        _capture_all(app, window, Path(args.screenshots).expanduser().resolve())
        return 0
    if args.screenshot:
        _capture_one(app, window, Path(args.screenshot).expanduser().resolve(), args.page)
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
