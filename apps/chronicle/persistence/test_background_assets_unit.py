"""Offline tests for Chronicle background candidate validation and display rules."""

from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from PIL import Image

import background_assets as backgrounds


def _image(format_name: str, *, size: tuple[int, int] = (4, 3)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (120, 80, 40)).save(output, format=format_name)
    return output.getvalue()


class BackgroundImageValidationTests(unittest.TestCase):
    def test_accepts_supported_encoded_formats_and_records_actual_dimensions(self) -> None:
        expected = {
            "PNG": ("image/png", "png"),
            "JPEG": ("image/jpeg", "jpeg"),
            "WEBP": ("image/webp", "webp"),
        }
        for format_name, (media_type, canonical) in expected.items():
            info = backgrounds.validate_image(
                _image(format_name),
                content_type=media_type,
                filename=f"scene.{('jpg' if canonical == 'jpeg' else canonical)}",
            )
            self.assertEqual(info["media_type"], media_type)
            self.assertEqual(info["image_format"], canonical)
            self.assertEqual((info["width"], info["height"]), (4, 3))
            self.assertEqual(info["byte_size"], len(_image(format_name)))

    def test_rejects_fake_mime_svg_html_and_mismatched_filename(self) -> None:
        png = _image("PNG")
        with self.assertRaises(backgrounds.BackgroundValidationError) as error:
            backgrounds.validate_image(png, content_type="text/html")
        self.assertEqual(error.exception.code, "unsupported_media_type")

        with self.assertRaises(backgrounds.BackgroundValidationError) as error:
            backgrounds.validate_image(b"<svg><script>alert(1)</script></svg>", content_type="image/png")
        self.assertEqual(error.exception.code, "decode_failed")

        with self.assertRaises(backgrounds.BackgroundValidationError) as error:
            backgrounds.validate_image(png, content_type="image/jpeg")
        self.assertEqual(error.exception.code, "media_type_mismatch")

        with self.assertRaises(backgrounds.BackgroundValidationError) as error:
            backgrounds.validate_image(png, filename="../scene.png")
        self.assertEqual(error.exception.code, "invalid_filename")

        with self.assertRaises(backgrounds.BackgroundValidationError) as error:
            backgrounds.validate_image(png, filename="scene.jpg")
        self.assertEqual(error.exception.code, "filename_format_mismatch")

    def test_rejects_size_and_pixel_limit_violations(self) -> None:
        png = _image("PNG")
        with self.assertRaises(backgrounds.BackgroundPayloadTooLarge):
            backgrounds.validate_image(png, max_bytes=len(png) - 1)

        with mock.patch.object(backgrounds, "MAX_IMAGE_PIXELS", 8):
            with self.assertRaises(backgrounds.BackgroundValidationError) as error:
                backgrounds.validate_image(png)
        self.assertEqual(error.exception.code, "pixel_limit_exceeded")

    def test_server_generates_uuid7_and_keeps_upload_limit_bounded(self) -> None:
        identifier = backgrounds.new_uuid7()
        self.assertEqual(identifier.version, 7)
        self.assertEqual(backgrounds.max_upload_bytes({}), 8 * 1024 * 1024)
        self.assertEqual(
            backgrounds.max_upload_bytes({"CHRONICLE_BACKGROUND_MAX_UPLOAD_BYTES": "42"}),
            42,
        )
        self.assertEqual(
            backgrounds.max_upload_bytes({"CHRONICLE_BACKGROUND_MAX_UPLOAD_BYTES": str(99 * 1024 * 1024)}),
            8 * 1024 * 1024,
        )
        with self.assertRaises(backgrounds.BackgroundValidationError):
            backgrounds.max_upload_bytes({"CHRONICLE_BACKGROUND_MAX_UPLOAD_BYTES": "0"})


class BackgroundStorageAndDisplayTests(unittest.TestCase):
    def test_storage_keys_are_server_relative_and_cannot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertEqual(
                backgrounds.resolve_storage_path(base, "assets/a/b.png").parent.name,
                "a",
            )
            for key in ("/outside.png", "assets/../outside.png", "assets/a\\b.png", ""):
                with self.assertRaises(backgrounds.BackgroundValidationError, msg=key):
                    backgrounds.resolve_storage_path(base, key)

    def test_display_is_normalized_and_unknown_values_are_rejected(self) -> None:
        display = backgrounds.normalize_display(
            {
                "opacity": 0.6,
                "position": {"x": 0.2, "y": 0.8},
                "scale": 1.25,
                "mask": {"left": 0.1, "shape": "gradient"},
            }
        )
        self.assertEqual(display["opacity"], 0.6)
        self.assertEqual(display["position"], {"x": 0.2, "y": 0.8})
        self.assertEqual(display["mask"], {"left": 0.1, "shape": "gradient"})

        for invalid in (
            {"opacity": 1.1},
            {"position": {"x": 0.5}},
            {"scale": 0.01},
            {"mask": {"shape": "circle"}},
            {"unexpected": True},
        ):
            with self.assertRaises(backgrounds.BackgroundValidationError, msg=invalid):
                backgrounds.normalize_display(invalid)

    def test_metadata_must_be_json_compatible(self) -> None:
        with self.assertRaises(backgrounds.BackgroundValidationError):
            backgrounds._metadata({"not_json": object()})  # noqa: SLF001 - validation unit
        with self.assertRaises(backgrounds.BackgroundValidationError):
            backgrounds._metadata({"not_json": math.nan})  # noqa: SLF001 - validation unit


if __name__ == "__main__":
    unittest.main()
