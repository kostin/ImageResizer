"""Отрисовка хода обработки.

В настоящем терминале показывается обновляемая строка с полосой, счётчиком
файлов и именем текущей картинки; сообщения журнала печатаются над полосой.
Когда вывод перенаправлен в файл или CI-лог, полоса отключается сама и остаются
обычные строки — иначе лог превратился бы в мусор из символов возврата каретки.
"""

from __future__ import annotations

import shutil
import sys
from typing import TextIO

from resizer import ProgressEvent

BAR_WIDTH = 20
_BAR_SOLID = ("█", "░")
_BAR_ASCII = ("#", "-")
_ELLIPSIS = "…"


def _can_encode(stream: TextIO, text: str) -> bool:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _truncate(text: str, limit: int, ellipsis: str = _ELLIPSIS) -> str:
    """Обрезает строку по центру, чтобы было видно и начало, и конец."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(ellipsis):
        return text[:limit]
    keep = limit - len(ellipsis)
    head = keep // 2 + keep % 2
    tail = keep - head
    if tail == 0:
        return text[:head] + ellipsis
    return text[:head] + ellipsis + text[-tail:]


class ProgressRenderer:
    """Прогресс-бар и журнал в одном объекте.

    :meth:`handle` принимает события обработки, :meth:`log` — обычные сообщения,
    :meth:`close` убирает полосу с экрана.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        enabled: bool | None = None,
        width: int | None = None,
    ) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.interactive = self._detect_interactive() if enabled is None else enabled
        self.width = width or self._detect_width()

        solid, empty = _BAR_SOLID
        if not _can_encode(self.stream, solid + empty + _ELLIPSIS):
            solid, empty = _BAR_ASCII
            self.ellipsis = "..."
        else:
            self.ellipsis = _ELLIPSIS
        self._solid = solid
        self._empty = empty

        self._last_line = ""
        self._last_length = 0

    # --- определение окружения -----------------------------------------

    def _detect_interactive(self) -> bool:
        isatty = getattr(self.stream, "isatty", None)
        if isatty is None:
            return False
        try:
            return bool(isatty())
        except (ValueError, OSError):
            return False

    def _detect_width(self) -> int:
        try:
            columns = shutil.get_terminal_size((100, 24)).columns
        except (ValueError, OSError):
            columns = 100
        return max(40, columns)

    # --- публичное API --------------------------------------------------

    def log(self, message: str) -> None:
        """Сообщение журнала: в терминале печатается над полосой."""
        if not self.interactive:
            self.stream.write(message + "\n")
            self.stream.flush()
            return

        previous = self._last_line
        self._clear()
        self.stream.write(message + "\n")
        if previous:
            self._draw(previous)

    def handle(self, event: ProgressEvent) -> None:
        """Обновляет полосу по событию обработки."""
        if not self.interactive:
            return

        if event.phase == "begin":
            if event.total <= 0:
                return
            self._draw(self._compose(0, event.total, "", "подготовка", 0.0))
            return

        if event.phase in {"start", "size", "done", "error"}:
            name = event.source.name if event.source is not None else ""
            total = event.total or 1
            self._draw(
                self._compose(
                    event.index, total, name, event.detail, event.fraction
                )
            )
            return

        if event.phase == "end":
            self.close()

    def close(self) -> None:
        """Убирает полосу, чтобы отчёт начинался с чистой строки."""
        if self.interactive:
            self._clear()

    # --- внутреннее -----------------------------------------------------

    def _compose(
        self,
        index: int,
        total: int,
        name: str,
        detail: str,
        fraction: float,
    ) -> str:
        bar_width = self._bar_width()
        filled = int(round(bar_width * min(max(fraction, 0.0), 1.0)))
        bar = self._solid * filled + self._empty * (bar_width - filled)
        prefix = f"[{bar}] {index}/{total}"
        available = self.width - 1

        detail_part = f" — {detail}" if detail else ""
        name_part = ""
        if name:
            # Имя файла важнее подробностей: если вместе не влезает, режем detail.
            room = available - len(prefix) - len(detail_part) - len(" — ")
            if room < 14:
                detail_part = ""
                room = available - len(prefix) - len(" — ")
            if room >= 8:
                name_part = " — " + _truncate(name, room, self.ellipsis)

        line = prefix + name_part + detail_part
        if len(line) > available:
            line = _truncate(line, available, self.ellipsis)
        return line

    def _bar_width(self) -> int:
        if self.width >= 80:
            return BAR_WIDTH
        if self.width >= 60:
            return 14
        return 10

    def _draw(self, line: str) -> None:
        padding = max(0, self._last_length - len(line))
        self.stream.write("\r" + line + " " * padding)
        self.stream.flush()
        self._last_line = line
        self._last_length = len(line)

    def _clear(self) -> None:
        if self._last_length:
            self.stream.write("\r" + " " * self._last_length + "\r")
            self.stream.flush()
        self._last_line = ""
        self._last_length = 0
