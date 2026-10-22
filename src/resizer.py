"""Ядро ImageResizer.

Модуль ищет картинки в папке, кадрирует их по центру под нужные пропорции и
сохраняет JPEG-копии 762x1100 и 1524x2200, подбирая качество сжатия так, чтобы
вес каждого файла не превышал 5 МБ.

Сам модуль ничего не печатает: сообщения передаются в callback ``log``, поэтому
его удобно тестировать и переиспользовать.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageOps, UnidentifiedImageError

__all__ = [
    "MAX_BYTES",
    "TARGET_SIZES",
    "Output",
    "SourceResult",
    "Summary",
    "encode_jpeg_under_limit",
    "fit",
    "human_size",
    "is_generated_name",
    "is_jpeg",
    "is_source_image",
    "list_sources",
    "normalize",
    "output_name",
    "process_folder",
    "write_atomic",
]

# Максимальный вес готового файла: 5 МБ.
MAX_BYTES = 5 * 1024 * 1024

# Размеры копий: (ширина, высота).
TARGET_SIZES: tuple[tuple[int, int], ...] = ((762, 1100), (1524, 2200))

JPEG_QUALITY_MIN = 1
JPEG_QUALITY_MAX = 95

_JPEG_MAGIC = b"\xff\xd8\xff"
_GENERATED_NAME = re.compile(r"^\d+x\d+_", re.IGNORECASE)

# Форматы, которые Pillow умеет прочитать «из коробки».
SOURCE_EXTENSIONS = frozenset(
    {
        ".avif",
        ".bmp",
        ".dib",
        ".gif",
        ".ico",
        ".jfif",
        ".jpe",
        ".jpeg",
        ".jpg",
        ".pbm",
        ".pcx",
        ".pgm",
        ".png",
        ".pnm",
        ".ppm",
        ".tga",
        ".tif",
        ".tiff",
        ".webp",
    }
)

LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class Output:
    """Одна созданная копия."""

    path: Path
    width: int
    height: int
    size_bytes: int
    quality: int
    within_limit: bool


@dataclass
class SourceResult:
    """Результат обработки одной исходной картинки."""

    source: Path
    outputs: list[Output] = field(default_factory=list)
    error: str | None = None


@dataclass
class Summary:
    """Итог обработки папки."""

    folder: Path
    sources: list[SourceResult] = field(default_factory=list)

    @property
    def successful(self) -> list[SourceResult]:
        return [item for item in self.sources if item.error is None]

    @property
    def failed(self) -> list[SourceResult]:
        return [item for item in self.sources if item.error is not None]

    @property
    def outputs(self) -> list[Output]:
        return [output for item in self.sources for output in item.outputs]

    @property
    def oversized(self) -> list[Output]:
        return [output for output in self.outputs if not output.within_limit]

    @property
    def total_bytes(self) -> int:
        return sum(output.size_bytes for output in self.outputs)


def human_size(size: int) -> str:
    """Человекочитаемый размер: «15 Б», «742 КБ», «4.81 МБ»."""
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} КБ"
    return f"{size / (1024 * 1024):.2f} МБ"


def is_generated_name(name: str) -> bool:
    """Похоже ли имя на созданную нами копию (начинается с разрешения)."""
    return bool(_GENERATED_NAME.match(name))


def is_jpeg(path: Path) -> bool:
    """Является ли файл JPEG-файлом (по сигнатуре)."""
    try:
        with open(path, "rb") as handle:
            return handle.read(len(_JPEG_MAGIC)) == _JPEG_MAGIC
    except OSError:
        return False


def is_source_image(path: Path) -> bool:
    """Подходит ли файл на роль исходной картинки."""
    try:
        if not path.is_file():
            return False
    except OSError:
        return False
    name = path.name
    if name.startswith(".") or name.startswith("~$"):
        return False
    if path.suffix.lower() not in SOURCE_EXTENSIONS:
        return False
    return not is_generated_name(name)


def list_sources(folder: Path) -> list[Path]:
    """Исходные картинки из папки (без вложенных папок), по алфавиту."""
    folder = Path(folder)
    try:
        entries = list(folder.iterdir())
    except OSError as exc:
        raise OSError(f"не удалось прочитать папку {folder}: {exc}") from exc
    sources = [path for path in entries if is_source_image(path)]
    sources.sort(key=lambda path: (path.name.casefold(), path.name))
    return sources


def output_name(width: int, height: int, stem: str, index: int = 0) -> str:
    """Имя копии: префикс-разрешение, затем исходное имя."""
    suffix = f"_{index}" if index else ""
    return f"{width}x{height}_{stem}{suffix}.jpg"


def normalize(image: Image.Image) -> Image.Image:
    """Разворачивает по EXIF и приводит картинку к RGB без прозрачности."""
    oriented = ImageOps.exif_transpose(image)
    if oriented is not None and oriented is not image:
        image = oriented
    if image.mode == "RGB":
        return image
    has_alpha = image.mode in {"RGBA", "LA", "PA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Заполняет кадр нужного размера, обрезая лишнее по центру."""
    width, height = size
    return ImageOps.fit(
        image,
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _encode(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
    )
    return buffer.getvalue()


def encode_jpeg_under_limit(
    image: Image.Image,
    limit: int = MAX_BYTES,
) -> tuple[bytes, int, bool]:
    """Кодирует JPEG с максимальным качеством, при котором файл влезает в лимит.

    Возвращает ``(данные, качество, уложились_ли_в_лимит)``. Если даже минимальное
    качество не помогает, отдаёт его и ``False`` — файл всё равно создаётся.
    """
    best = _encode(image, JPEG_QUALITY_MAX)
    if len(best) <= limit:
        return best, JPEG_QUALITY_MAX, True

    low, high = JPEG_QUALITY_MIN, JPEG_QUALITY_MAX - 1
    candidate: tuple[bytes, int] | None = None
    while low <= high:
        middle = (low + high) // 2
        data = _encode(image, middle)
        if len(data) <= limit:
            candidate = (data, middle)
            low = middle + 1
        else:
            high = middle - 1

    if candidate is None:
        return _encode(image, JPEG_QUALITY_MIN), JPEG_QUALITY_MIN, False
    return candidate[0], candidate[1], True


def write_atomic(data: bytes, destination: Path) -> None:
    """Пишет файл через временный, чтобы не оставлять недописанных копий."""
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _resolve_destination(
    folder: Path,
    width: int,
    height: int,
    stem: str,
    produced: set[str],
) -> Path | None:
    """Подбирает свободное имя копии; ``None`` — писать нельзя (чужой файл)."""
    index = 0
    while True:
        name = output_name(width, height, stem, index)
        key = name.casefold()
        destination = folder / name
        if key in produced:
            index += 1
            continue
        if destination.exists() and not is_jpeg(destination):
            return None
        return destination


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "файл не найден"
    if isinstance(exc, PermissionError):
        return "нет доступа к файлу"
    if isinstance(exc, UnidentifiedImageError):
        return "не удалось распознать формат картинки"
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _process_source(
    source: Path,
    folder: Path,
    sizes: Sequence[tuple[int, int]],
    limit: int,
    produced: set[str],
    result: SourceResult,
    emit: LogCallback,
) -> None:
    with Image.open(source) as opened:
        image = normalize(opened)
        try:
            for width, height in sizes:
                canvas = fit(image, (width, height))
                try:
                    data, quality, within_limit = encode_jpeg_under_limit(canvas, limit)
                finally:
                    canvas.close()

                destination = _resolve_destination(
                    folder, width, height, source.stem, produced
                )
                if destination is None:
                    emit(
                        f"    пропуск {width}x{height}: файл с таким именем уже есть "
                        "и это не JPEG — чтобы не перезаписать чужой файл"
                    )
                    continue

                write_atomic(data, destination)
                produced.add(destination.name.casefold())
                output = Output(
                    path=destination,
                    width=width,
                    height=height,
                    size_bytes=len(data),
                    quality=quality,
                    within_limit=within_limit,
                )
                result.outputs.append(output)

                note = "" if within_limit else (
                    f" — ВНИМАНИЕ: не удалось уложиться в {human_size(limit)}"
                )
                emit(
                    f"    {destination.name} — {width}x{height}, "
                    f"{human_size(len(data))}, качество {quality}{note}"
                )
        finally:
            image.close()


def process_folder(
    folder: Path,
    *,
    sizes: Sequence[tuple[int, int]] = TARGET_SIZES,
    limit: int = MAX_BYTES,
    log: LogCallback | None = None,
) -> Summary:
    """Обрабатывает все картинки папки (без вложенных папок).

    Существующие копии перезаписываются, чужие не-JPEG файлы с совпадающим именем
    не трогаются. Ошибки по отдельным картинкам не прерывают обработку.
    """
    folder = Path(folder)
    emit: LogCallback = log or (lambda _message: None)

    sources = list_sources(folder)
    summary = Summary(folder=folder)
    if not sources:
        emit("В папке нет картинок — обрабатывать нечего.")
        return summary

    emit(f"Найдено картинок: {len(sources)}")
    produced: set[str] = set()

    for number, source in enumerate(sources, start=1):
        emit(f"[{number}/{len(sources)}] {source.name}")
        result = SourceResult(source=source)
        try:
            _process_source(source, folder, sizes, limit, produced, result, emit)
        except Exception as exc:  # noqa: BLE001 — одна битая картинка не должна рушить всё
            result = SourceResult(source=source, error=_describe_error(exc))
            emit(f"    ошибка: {result.error}")
        summary.sources.append(result)

    return summary
