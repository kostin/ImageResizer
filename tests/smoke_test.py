"""Проверка собранного исполняемого файла.

Запускает бинарник на временной папке с картинками и проверяет, что рядом
появились JPEG-копии 762x1100 и 1524x2200 в пределах 5 МБ, а повторный запуск
не размножает файлы.

Использование::

    python tests/smoke_test.py dist/ImageResizer.exe
    python tests/smoke_test.py dist/ImageResizer
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

MAX_BYTES = 5 * 1024 * 1024
EXPECTED = {"762x1100": (762, 1100), "1524x2200": (1524, 2200)}


def fail(message: str) -> None:
    print(f"ОШИБКА: {message}", file=sys.stderr)
    raise SystemExit(1)


def configure_streams() -> None:
    """UTF-8 вывод: приложение печатает по-русски, а консоль Windows бывает cp866/cp1252."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def make_images(folder: Path) -> None:
    Image.new("RGB", (900, 1200), (180, 60, 40)).save(folder / "portrait.png")
    Image.new("RGB", (2600, 1000), (40, 120, 180)).save(folder / "landscape.jpg")
    Image.new("RGBA", (600, 900), (0, 0, 0, 0)).save(folder / "alpha.png")
    Image.effect_noise((1524, 2200), 90).convert("RGB").save(folder / "noise.png")


def run(binary: Path, folder: Path) -> str:
    process = subprocess.run(
        [str(binary), "--dir", str(folder), "--no-pause"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if process.returncode != 0:
        print(process.stdout)
        print(process.stderr, file=sys.stderr)
        fail(f"приложение завершилось с кодом {process.returncode}")
    return process.stdout


def check_outputs(folder: Path, expected_files: set[str]) -> None:
    present = {path.name for path in folder.iterdir()}
    for name in sorted(expected_files):
        if name not in present:
            fail(f"не создан файл {name}; в папке: {sorted(present)}")

    for name in sorted(expected_files):
        path = folder / name
        prefix = name.split("_", 1)[0]
        if prefix not in EXPECTED:
            continue
        if path.read_bytes()[:3] != b"\xff\xd8\xff":
            fail(f"{name} не является JPEG")
        with Image.open(path) as opened:
            if opened.format != "JPEG":
                fail(f"{name}: формат {opened.format}")
            if opened.size != EXPECTED[prefix]:
                fail(f"{name}: размер {opened.size}, ожидали {EXPECTED[prefix]}")
        size = path.stat().st_size
        if size > MAX_BYTES:
            fail(f"{name}: вес {size} больше {MAX_BYTES}")


def main(argv: list[str]) -> int:
    configure_streams()
    if len(argv) != 2:
        print(__doc__)
        return 2

    binary = Path(argv[1]).resolve()
    if not binary.is_file():
        fail(f"нет файла {binary}")

    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        make_images(folder)

        output = run(binary, folder)
        print(output)

        expected = set()
        for stem in ("portrait", "landscape", "alpha", "noise"):
            for prefix in EXPECTED:
                expected.add(f"{prefix}_{stem}.jpg")
        check_outputs(folder, expected)

        first_run = {path.name for path in folder.iterdir()}
        run(binary, folder)
        second_run = {path.name for path in folder.iterdir()}
        if first_run != second_run:
            fail(f"повторный запуск добавил файлы: {sorted(second_run - first_run)}")

    print("SMOKE OK: бинарник работает и создаёт корректные копии")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
