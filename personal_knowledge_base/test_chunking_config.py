from dataclasses import FrozenInstanceError

from django.test import SimpleTestCase

from .chunking.config import ChunkingConfig, SUPPORTED_FILE_TYPES, UNSUPPORTED_FILE_TYPES, validate_upload_extension
from .document_processing import is_unsupported_media_file


class ChunkingConfigTests(SimpleTestCase):
    def test_explicit_zero_overlap_is_preserved(self):
        config = ChunkingConfig.from_mapping({"chunk_overlap": 0, "token_limit": 0})

        self.assertEqual(config.chunk_overlap, 0)
        self.assertEqual(config.token_limit, 0)

    def test_office_extensions_are_supported(self):
        for name in ("old.doc", "sheet.xls", "sheet.xlsx", "slides.ppt"):
            with self.subTest(name=name):
                self.assertEqual(validate_upload_extension(name), name.rsplit(".", 1)[1])

    def test_supported_and_explicitly_unsupported_types_are_disjoint(self):
        self.assertIn("pdf", SUPPORTED_FILE_TYPES)
        self.assertIn("epub", UNSUPPORTED_FILE_TYPES)
        self.assertFalse(SUPPORTED_FILE_TYPES & UNSUPPORTED_FILE_TYPES)

    def test_unknown_extension_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_upload_extension("archive.epub")

    def test_legacy_media_guard_excludes_non_media_disallowed_formats(self):
        self.assertTrue(is_unsupported_media_file("record.mp3"))
        self.assertFalse(is_unsupported_media_file("archive.epub"))

    def test_config_is_immutable(self):
        config = ChunkingConfig.from_mapping({})

        with self.assertRaises(FrozenInstanceError):
            config.chunk_size = 256

    def test_invalid_configurations_are_rejected(self):
        invalid_configs = (
            {"strategy": "unrecognized"},
            {"chunk_size": 0},
            {"chunk_size": 256, "chunk_overlap": 129},
            {"parent_chunk_size": 256, "child_chunk_size": 384},
            {"child_chunk_size": 256, "child_chunk_overlap": 129},
            {"token_limit": -1},
            {"semantic_window_size": 0},
            {"semantic_breakpoint_percentile": 101},
        )

        for raw in invalid_configs:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    ChunkingConfig.from_mapping(raw)
