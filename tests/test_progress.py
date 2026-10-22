"""Тесты отрисовки прогресса (без внешних зависимостей)."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resizer import ProgressEvent  # noqa: E402
from progress import ProgressRenderer  # noqa: E402


class AsciiStream(io.StringIO):
    """Поток с узкой кодировкой — как консоль без юникода."""

    encoding = "ascii"


class ProgressRendererTest(unittest.TestCase):
    def test_disabled_mode_prints_plain_lines_only(self) -> None:
        stream = io.StringIO()
        renderer = ProgressRenderer(stream, enabled=False)

        renderer.handle(ProgressEvent("begin", total=3))
        renderer.handle(ProgressEvent("start", 1, 3, 0.0, Path("a.png")))
        renderer.log("сообщение")
        renderer.close()

        self.assertEqual(stream.getvalue(), "сообщение\n")

    def test_bar_shows_counter_name_and_detail(self) -> None:
        stream = io.StringIO()
        renderer = ProgressRenderer(stream, enabled=True, width=80)
        source = Path("photo.png")

        renderer.handle(ProgressEvent("begin", total=3))
        renderer.handle(ProgressEvent("start", 1, 3, 0.0, source))
        renderer.handle(
            ProgressEvent("size", 1, 3, 1 / 6, source, "762x1100 → 0.6 МБ")
        )

        output = stream.getvalue()
        self.assertIn("\r", output)
        self.assertIn("1/3", output)
        self.assertIn("photo.png", output)
        self.assertIn("762x1100", output)
        self.assertIn("█", output)
        self.assertIn("░", output)

    def test_long_name_is_truncated_to_terminal_width(self) -> None:
        stream = io.StringIO()
        renderer = ProgressRenderer(stream, enabled=True, width=40)
        name = "очень-длинное-имя-картинки-которое-точно-не-влезает.png"

        renderer.handle(ProgressEvent("start", 1, 10, 0.0, Path(name)))

        last_frame = stream.getvalue().split("\r")[-1]
        self.assertLessEqual(len(last_frame), 39)
        self.assertIn("…", last_frame)

    def test_log_message_goes_above_and_bar_is_redrawn(self) -> None:
        stream = io.StringIO()
        renderer = ProgressRenderer(stream, enabled=True, width=80)
        renderer.handle(ProgressEvent("start", 1, 2, 0.0, Path("a.png")))

        renderer.log("предупреждение")

        output = stream.getvalue()
        self.assertIn("предупреждение\n", output)
        self.assertIn("a.png", output.split("\n")[-1])

    def test_close_removes_the_bar(self) -> None:
        stream = io.StringIO()
        renderer = ProgressRenderer(stream, enabled=True, width=80)
        renderer.handle(ProgressEvent("start", 2, 2, 0.5, Path("b.png")))
        before = len(stream.getvalue())

        renderer.close()

        self.assertGreater(len(stream.getvalue()), before)
        self.assertTrue(stream.getvalue().endswith("\r"))

    def test_ascii_fallback_for_narrow_encoding(self) -> None:
        stream = AsciiStream()
        renderer = ProgressRenderer(stream, enabled=True, width=60)

        renderer.handle(ProgressEvent("begin", total=1))
        renderer.handle(
            ProgressEvent("size", 1, 1, 1.0, Path("a.png"), "762x1100 → 1 КБ")
        )

        output = stream.getvalue()
        self.assertNotIn("█", output)
        self.assertIn("#", output)
        self.assertEqual(renderer.ellipsis, "...")

    def test_zero_total_begin_draws_nothing(self) -> None:
        stream = io.StringIO()
        renderer = ProgressRenderer(stream, enabled=True, width=80)

        renderer.handle(ProgressEvent("begin", total=0))

        self.assertEqual(stream.getvalue(), "")

    def test_full_run_draws_every_file(self) -> None:
        import tempfile

        from PIL import Image

        from resizer import process_folder

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            Image.new("RGB", (300, 400), (10, 20, 30)).save(folder / "one.png")
            Image.new("RGB", (300, 400), (30, 20, 10)).save(folder / "two.png")

            stream = io.StringIO()
            renderer = ProgressRenderer(stream, enabled=True, width=100)
            summary = process_folder(
                folder, log=renderer.log, progress=renderer.handle
            )

            output = stream.getvalue()
            self.assertIn("one.png", output)
            self.assertIn("two.png", output)
            self.assertIn("2/2", output)
            self.assertEqual(len(summary.outputs), 4)
            self.assertTrue(renderer.interactive)


if __name__ == "__main__":
    unittest.main(verbosity=2)
