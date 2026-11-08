"""Фоновые QThread-задачи: поиск, проверка API и получение токена."""
from __future__ import annotations

import asyncio
import copy
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..collector import collect
from ..config import Settings
from ..db import Database
from ..sources.base import RateLimiter
from ..sources.hh_api import HHAPISource
from ..sources.hh_web import HHWebSource

logger = logging.getLogger(__name__)


class SearchWorker(QThread):
    progress = Signal(str, int, int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: Settings, db_path: Path | str, parent=None):
        super().__init__(parent)
        self.settings = copy.deepcopy(settings)
        self.db_path = str(db_path)
        self._stop = threading.Event()
        self._main_task: asyncio.Task | None = None
        self._watch_task: asyncio.Task | None = None

    def stop(self) -> None:
        self._stop.set()

    def _emit(self, message: str, done: int, total: int) -> None:
        self.progress.emit(message, int(done), int(total))

    def run(self) -> None:  # noqa: D102
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(self._async_run())
            self.completed.emit(summary)
        except Exception as exc:
            logger.exception("Фоновая задача поиска завершилась ошибкой")
            self.failed.emit(str(exc))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    async def _async_run(self):
        db = Database(self.db_path)
        self._watch_task = asyncio.create_task(self._watch_stop())
        self._main_task = asyncio.create_task(
            collect(db, self.settings, self._emit, self._stop)
        )
        try:
            return await self._main_task
        finally:
            if self._watch_task and not self._watch_task.done():
                self._watch_task.cancel()
                await asyncio.gather(self._watch_task, return_exceptions=True)

    async def _watch_stop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(0.2)
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()


class ApiTestWorker(QThread):
    result = Signal(dict)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = copy.deepcopy(settings)

    def run(self) -> None:  # noqa: D102
        try:
            self.result.emit(asyncio.run(self._check()))
        except Exception as exc:
            logger.exception("Проверка API завершилась ошибкой")
            self.result.emit({"error": str(exc)})

    async def _check(self) -> dict:
        limiter = RateLimiter(0.8)
        api = HHAPISource(self.settings, limiter)
        web = HHWebSource(self.settings, limiter)
        try:
            try:
                api_result = await api.test()
            except Exception as exc:
                api_result = {"ok": False, "message": f"Ошибка API: {exc}"}
            if self.settings.allow_web_fallback:
                try:
                    web_result = await web.test()
                except Exception as exc:
                    web_result = {"ok": False, "message": f"Ошибка hh.ru: {exc}"}
            else:
                web_result = {"ok": False, "message": "Резервный режим отключён в настройках"}
            return {"api": api_result, "web": web_result}
        finally:
            await api.aclose()
            await web.aclose()


class TokenWorker(QThread):
    result = Signal(dict)

    def __init__(self, settings: Settings, client_id: str, client_secret: str, parent=None):
        super().__init__(parent)
        self.settings = copy.deepcopy(settings)
        self.client_id = client_id
        self.client_secret = client_secret

    def run(self) -> None:  # noqa: D102
        try:
            self.result.emit(asyncio.run(self._get()))
        except Exception as exc:
            logger.exception("Не удалось получить токен приложения")
            self.result.emit({"ok": False, "error": str(exc)})

    async def _get(self) -> dict:
        if not self.client_id or not self.client_secret:
            return {"ok": False, "error": "Сначала заполните client_id и client_secret зарегистрированного приложения HH."}
        limiter = RateLimiter(0.8)
        api = HHAPISource(self.settings, limiter)
        try:
            data = await api.get_app_token(self.client_id, self.client_secret)
            token = str(data.get("access_token") or "")
            if not token:
                return {"ok": False, "error": f"HH не вернул access_token: {str(data)[:300]}"}
            return {
                "ok": True,
                "access_token": token,
                "expires_in": data.get("expires_in"),
                "token_type": data.get("token_type"),
            }
        finally:
            await api.aclose()
