"""Тесты ядра ImageResizer (без внешних зависимостей, только Pillow)."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

import resizer  # noqa: E402

PORTRAIT = (800, 1200)
LANDSCAPE = (2400, 1000)


class ResizerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self._temporary.name)
        self.messages: list[str] = []

    def tearDown(self) -> None:
        self._temporary.cleanup()

    # --- помощники -----------------------------------------------------

    def make_image(
        self,
        name: str,
        size: tuple[int, int] = PORTRAIT,
        color: object = (120, 40, 200),
        mode: str = "RGB",
        **save_options: object,
    ) -> Path:
        path = self.folder / name
        Image.new(mode, size, color).save(path, **save_options)
        return path

    def make_noise(self, name: str, size: tuple[int, int], seed: int = 1) -> Path:
        """Шумная картинка: сжимается плохо, хорошо проверяет лимит веса."""
        image = Image.effect_noise(size, 80).convert("RGB")
        rng = Image.effect_noise(size, 80)
        image = Image.merge("RGB", (image.convert("L"), rng, image.convert("L")))
        path = self.folder / name
        image.save(path)
        image.close()
        return path

    def run_folder(self, **kwargs: object) -> resizer.Summary:
        return resizer.process_folder(self.folder, log=self.messages.append, **kwargs)

    def assert_output(self, path: Path, size: tuple[int, int]) -> None:
        self.assertTrue(path.is_file(), f"нет файла {path}")
        self.assertEqual(path.read_bytes()[:3], b"\xff\xd8\xff", "это не JPEG")
        with Image.open(path) as opened:
            self.assertEqual(opened.size, size)
            self.assertEqual(opened.format, "JPEG")
        self.assertLessEqual(path.stat().st_size, resizer.MAX_BYTES)

    # --- тесты ---------------------------------------------------------

    def test_creates_both_sizes_with_resolution_prefix(self) -> None:
        self.make_image("photo.png")

        summary = self.run_folder()

        self.assertEqual(summary.failed, [])
        names = {output.path.name for output in summary.outputs}
        self.assertEqual(names, {"762x1100_photo.jpg", "1524x2200_photo.jpg"})
        self.assert_output(self.folder / "762x1100_photo.jpg", (762, 1100))
        self.assert_output(self.folder / "1524x2200_photo.jpg", (1524, 2200))

    def test_center_crop_fills_frame_and_cuts_sides(self) -> None:
        # По краям красные полосы, в середине зелёная — при кадрировании по центру
        # красные полосы должны исчезнуть, а не сплющиться.
        image = Image.new("RGB", (2000, 1000), (0, 160, 0))
        image.paste((220, 0, 0), (0, 0, 400, 1000))
        image.paste((220, 0, 0), (1600, 0, 2000, 1000))
        image.save(self.folder / "wide.png")
        image.close()

        self.run_folder()

        with Image.open(self.folder / "762x1100_wide.jpg") as opened:
            self.assertEqual(opened.size, (762, 1100))
            left = opened.getpixel((5, 550))
            middle = opened.getpixel((381, 550))
            right = opened.getpixel((756, 550))

        for pixel in (left, middle, right):
            self.assertGreater(pixel[1], 100, f"ожидали зелёный, получили {pixel}")
            self.assertLess(pixel[0], 100, f"ожидали зелёный, получили {pixel}")

    def test_transparent_png_gets_white_background(self) -> None:
        image = Image.new("RGBA", (600, 900), (0, 0, 0, 0))
        image.paste((10, 120, 200, 255), (100, 100, 500, 800))
        image.save(self.folder / "alpha.png")
        image.close()

        self.run_folder()

        with Image.open(self.folder / "1524x2200_alpha.jpg") as opened:
            corner = opened.getpixel((2, 2))
        self.assertTrue(all(channel > 240 for channel in corner), f"угол не белый: {corner}")

    def test_landscape_png_processed_without_distortion(self) -> None:
        self.make_image("land.png", size=LANDSCAPE, color=(10, 90, 200))

        summary = self.run_folder()

        self.assertEqual(len(summary.outputs), 2)
        self.assert_output(self.folder / "762x1100_land.jpg", (762, 1100))
        self.assert_output(self.folder / "1524x2200_land.jpg", (1524, 2200))

    def test_weight_limit_is_respected_for_noisy_image(self) -> None:
        self.make_noise("noise.png", (1524, 2200))
        limit = 300 * 1024

        summary = self.run_folder(limit=limit)

        self.assertEqual(summary.failed, [])
        for output in summary.outputs:
            self.assertLessEqual(output.size_bytes, limit, output.path.name)
            self.assertLess(output.quality, resizer.JPEG_QUALITY_MAX)
            self.assertTrue(output.within_limit)
            self.assertLessEqual(output.path.stat().st_size, limit)

    def test_broken_image_reported_and_others_processed(self) -> None:
        (self.folder / "broken.jpg").write_bytes(b"not an image at all")
        self.make_image("good.png")

        summary = self.run_folder()

        self.assertEqual(len(summary.failed), 1)
        self.assertEqual(summary.failed[0].source.name, "broken.jpg")
        self.assertIn("распознать", summary.failed[0].error or "")
        self.assertEqual(len(summary.successful), 1)
        self.assertEqual(len(summary.outputs), 2)
        self.assertFalse((self.folder / "762x1100_broken.jpg").exists())

    def test_second_run_does_not_grow_outputs(self) -> None:
        self.make_image("photo.png")

        self.run_folder()
        first = {path.name for path in self.folder.iterdir()}
        second_summary = self.run_folder()
        second = {path.name for path in self.folder.iterdir()}

        self.assertEqual(first, second)
        self.assertEqual(len(second_summary.sources), 1)
        self.assertEqual(second_summary.sources[0].source.name, "photo.png")

    def test_same_stem_different_extensions_do_not_overwrite(self) -> None:
        self.make_image("cat.jpg")
        self.make_image("cat.png", color=(20, 200, 40))

        summary = self.run_folder()

        names = sorted(output.path.name for output in summary.outputs)
        self.assertEqual(
            names,
            [
                "1524x2200_cat.jpg",
                "1524x2200_cat_1.jpg",
                "762x1100_cat.jpg",
                "762x1100_cat_1.jpg",
            ],
        )
        self.assertEqual(len({output.path.name for output in summary.outputs}), 4)

    def test_foreign_non_jpeg_file_is_not_overwritten(self) -> None:
        self.make_image("photo.png")
        foreign = self.folder / "762x1100_photo.jpg"
        foreign.write_bytes(b"my own data")

        summary = self.run_folder()

        self.assertEqual(foreign.read_bytes(), b"my own data")
        self.assertEqual(len(summary.outputs), 1)
        self.assertIn("пропуск 762x1100", "\n".join(self.messages))

    def test_hidden_and_service_files_are_ignored(self) -> None:
        self.make_image(".hidden.png")
        self.make_image("photo.png")
        (self.folder / ".DS_Store").write_bytes(b"junk")
        (self.folder / "notes.txt").write_text("не картинка", encoding="utf-8")

        summary = self.run_folder()

        self.assertEqual(len(summary.sources), 1)
        self.assertEqual(summary.sources[0].source.name, "photo.png")

    def test_empty_folder_is_not_an_error(self) -> None:
        summary = self.run_folder()

        self.assertEqual(summary.sources, [])
        self.assertEqual(summary.outputs, [])
        self.assertIn("нет картинок", self.messages[-1])

    def test_animated_gif_uses_first_frame(self) -> None:
        frames = [Image.new("RGB", (300, 400), color) for color in ((255, 0, 0), (0, 255, 0))]
        frames[0].save(
            self.folder / "anim.gif",
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
        )
        for frame in frames:
            frame.close()

        summary = self.run_folder()

        self.assertEqual(summary.failed, [])
        self.assert_output(self.folder / "762x1100_anim.jpg", (762, 1100))

    def test_cmyk_and_grayscale_sources(self) -> None:
        Image.new("CMYK", (900, 1200), (0, 0, 0, 0)).save(self.folder / "cmyk.jpg")
        Image.new("L", (700, 1000), 128).save(self.folder / "gray.png")

        summary = self.run_folder()

        self.assertEqual(summary.failed, [])
        self.assertEqual(len(summary.outputs), 4)
        self.assert_output(self.folder / "762x1100_cmyk.jpg", (762, 1100))
        self.assert_output(self.folder / "1524x2200_gray.jpg", (1524, 2200))

    def test_uppercase_extension_is_recognised(self) -> None:
        self.make_image("PHOTO.PNG")

        summary = self.run_folder()

        self.assertEqual(len(summary.outputs), 2)
        self.assertTrue((self.folder / "762x1100_PHOTO.jpg").is_file())

    def test_outputs_are_not_treated_as_sources_even_if_jpeg(self) -> None:
        Image.new("RGB", (762, 1100), (0, 0, 0)).save(self.folder / "1524x2200_x.jpg")
        self.assertTrue(resizer.is_generated_name("762x1100_anything.jpg"))
        self.assertTrue(resizer.is_generated_name("1524x2200_a.png"))

        summary = self.run_folder()

        self.assertEqual(summary.sources, [])

    def test_output_name_and_helpers(self) -> None:
        self.assertEqual(resizer.output_name(762, 1100, "фото"), "762x1100_фото.jpg")
        self.assertEqual(resizer.output_name(762, 1100, "a", 2), "762x1100_a_2.jpg")
        self.assertEqual(resizer.human_size(512), "512 Б")
        self.assertEqual(resizer.human_size(2048), "2 КБ")
        self.assertEqual(resizer.human_size(5 * 1024 * 1024), "5.00 МБ")
        self.assertFalse(resizer.is_generated_name("обычное.jpg"))

    def test_quality_search_prefers_higher_quality(self) -> None:
        image = Image.new("RGB", (762, 1100), (30, 60, 90))
        data, quality, within = resizer.encode_jpeg_under_limit(image, 20_000)
        image.close()

        self.assertTrue(within)
        self.assertLessEqual(len(data), 20_000)
        self.assertGreater(quality, resizer.JPEG_QUALITY_MIN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
