"""ImageResizer — консольное приложение для подготовки JPEG-копий картинок.

Для каждой картинки, лежащей рядом с исполняемым файлом, создаёт две копии в
формате JPEG: 762x1100 и 1524x2200. Кадр заполняется по центру (лишнее
обрезается), вес каждого файла не превышает 5 МБ, а имя копии начинается с
разрешения: ``762x1100_имя.jpg`` и ``1524x2200_имя.jpg``.

Примеры запуска::

    ImageResizer                 # обработать папку, где лежит программа
    ImageResizer --dir ./фото    # обработать другую папку
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import resizer

APP_NAME = "ImageResizer"


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


def _print_summary(summary: resizer.Summary, elapsed: float) -> None:
    print()
    if not summary.sources:
        print("Итог: картинок не найдено.")
        return

    print(
        "Итог: картинок {sources}, копий {outputs}, ошибок {errors}; "
        "всего {size}; время {elapsed:.1f} с".format(
            sources=len(summary.sources),
            outputs=len(summary.outputs),
            errors=len(summary.failed),
            size=resizer.human_size(summary.total_bytes),
            elapsed=elapsed,
        )
    )

    if summary.failed:
        print("\nНе удалось обработать:")
        for result in summary.failed:
            print(f"  • {result.source.name}: {result.error}")

    if summary.oversized:
        print("\nВнимание, превышен лимит веса:")
        for output in summary.oversized:
            print(f"  • {output.path.name}: {resizer.human_size(output.size_bytes)}")


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
    print(f"{APP_NAME}: папка {folder}")
    print(
        f"Размеры: {sizes}; лимит веса: {resizer.human_size(resizer.MAX_BYTES)}; "
        "кадрирование по центру"
    )
    print()

    exit_code = 0
    if not folder.is_dir():
        print(f"Ошибка: папка не найдена — {folder}")
        exit_code = 2
    else:
        started = time.perf_counter()
        try:
            summary = resizer.process_folder(folder, log=print)
        except OSError as exc:
            print(f"Ошибка: {exc}")
            exit_code = 2
        else:
            elapsed = time.perf_counter() - started
            _print_summary(summary, elapsed)
            exit_code = 1 if summary.failed else 0

    _pause(arguments, args.no_pause)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
