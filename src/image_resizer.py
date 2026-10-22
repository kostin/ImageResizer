"""ImageResizer — консольное приложение для подготовки JPEG-копий картинок.

Для каждой картинки, лежащей рядом с исполняемым файлом, создаёт две копии в
формате JPEG: 762x1100 и 1524x2200. Кадр заполняется по центру (лишнее
обрезается), вес каждого файла не превышает 5 МБ, а имя копии начинается с
разрешения: ``762x1100_имя.jpg`` и ``1524x2200_имя.jpg``.

Во время работы показывает прогресс-бар с именем текущей картинки, в конце —
краткий отчёт. Если вывод перенаправлен в файл (CI, лог), вместо полосы
печатаются обычные строки.

Примеры запуска::

    ImageResizer                 # обработать папку, где лежит программа
    ImageResizer --dir ./фото    # обработать другую папку
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import progress
import resizer

APP_NAME = "ImageResizer"
APP_VERSION = "1.1.0"


def app_directory() -> Path:
    """Папка, в которой лежит исполняемый файл (а не текущая папка процесса)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _configure_streams() -> None:
    """Не падать на символах, которые не влезают в кодировку консоли."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _build_parser() -> argparse.ArgumentParser:
    sizes = ", ".join(f"{width}x{height}" for width, height in resizer.TARGET_SIZES)
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Создаёт JPEG-копии картинок ({sizes}) из папки, в которой лежит "
            "программа. Максимальный вес копии — 5 МБ, кадрирование по центру."
        ).format(sizes=sizes),
    )
    parser.add_argument(
        "--dir",
        metavar="ПАПКА",
        help="обработать указанную папку вместо папки программы",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="не рисовать прогресс-бар, печатать по строке на файл",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="не ждать нажатия Enter после завершения",
    )
    return parser


def _pause(arguments: list[str], no_pause: bool) -> None:
    """Ждёт Enter только при запуске двойным щелчком, чтобы окно не закрывалось."""
    if no_pause or arguments:
        return
    stream = sys.stdin
    if stream is None:
        return
    try:
        interactive = stream.isatty()
    except (ValueError, OSError):
        interactive = False
    if not interactive:
        return
    try:
        input("\nНажмите Enter, чтобы закрыть окно...")
    except (EOFError, KeyboardInterrupt):
        pass


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение: 1 картинка, 2 картинки, 5 картинок."""
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def format_duration(seconds: float) -> str:
    """Длительность: «3.4 с» или «1 мин 05 с»."""
    if seconds < 60:
        return f"{seconds:.1f} с"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes} мин {rest:02d} с"


def _print_report(summary: resizer.Summary, elapsed: float) -> None:
    """Краткий отчёт: сколько сделано, сколько весит, что пошло не так."""
    print()
    if not summary.sources:
        print("Итог: картинок не найдено.")
        return

    sources = len(summary.sources)
    copies = len(summary.outputs)
    errors = len(summary.failed)
    print(
        "Итог: {sources} {sources_word} → {copies} {copies_word}, {size}, "
        "время {elapsed}, ошибок {errors}".format(
            sources=sources,
            sources_word=_plural(sources, "картинка", "картинки", "картинок"),
            copies=copies,
            copies_word=_plural(copies, "копия", "копии", "копий"),
            size=resizer.human_size(summary.total_bytes),
            elapsed=format_duration(elapsed),
            errors=errors,
        )
    )

    for width, height in resizer.TARGET_SIZES:
        selected = [
            output
            for output in summary.outputs
            if (output.width, output.height) == (width, height)
        ]
        if not selected:
            continue
        total = sum(output.size_bytes for output in selected)
        print(
            "  {label}: {count} {word}, {size}".format(
                label=f"{width}x{height}",
                count=len(selected),
                word=_plural(len(selected), "файл", "файла", "файлов"),
                size=resizer.human_size(total),
            )
        )

    if summary.failed:
        print("\nНе удалось обработать:")
        for result in summary.failed:
            print(f"  • {result.source.name}: {result.error}")

    if summary.warnings:
        shown = summary.warnings[:10]
        print(f"\nПредупреждения ({len(summary.warnings)}):")
        for warning in shown:
            print(f"  • {warning}")
        if len(summary.warnings) > len(shown):
            print(f"  • ...и ещё {len(summary.warnings) - len(shown)}")


def main(argv: list[str] | None = None) -> int:
    _configure_streams()
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(arguments)

    folder = Path(args.dir).expanduser() if args.dir else app_directory()
    try:
        folder = folder.resolve()
    except OSError:
        folder = folder.absolute()

    sizes = ", ".join(f"{width}x{height}" for width, height in resizer.TARGET_SIZES)
    print(f"{APP_NAME} {APP_VERSION}: папка {folder}")
    print(
        f"Размеры: {sizes}; лимит веса: {resizer.human_size(resizer.MAX_BYTES)}; "
        "кадрирование по центру"
    )
    print()

    renderer = progress.ProgressRenderer(
        enabled=False if args.no_progress else None
    )

    exit_code = 0
    if not folder.is_dir():
        print(f"Ошибка: папка не найдена — {folder}")
        exit_code = 2
    else:
        started = time.perf_counter()
        try:
            summary = resizer.process_folder(
                folder, log=renderer.log, progress=renderer.handle
            )
        except KeyboardInterrupt:
            renderer.close()
            print("\nПрервано пользователем.")
            _pause(arguments, args.no_pause)
            return 130
        except OSError as exc:
            renderer.close()
            print(f"Ошибка: {exc}")
            _pause(arguments, args.no_pause)
            return 2
        else:
            elapsed = time.perf_counter() - started
            renderer.close()
            _print_report(summary, elapsed)
            exit_code = 1 if summary.failed else 0

    _pause(arguments, args.no_pause)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
