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

    def test_chunk_sizes_accept_exact_minimum_and_maximum_values(self):
        valid_configs = (
            {"chunk_size": 128, "chunk_overlap": 64},
            {"chunk_size": 4096},
            {"parent_chunk_size": 512, "child_chunk_size": 512},
            {"parent_chunk_size": 8192},
            {"child_chunk_size": 128, "child_chunk_overlap": 64},
            {"parent_chunk_size": 8192, "child_chunk_size": 2048},
        )

        for raw in valid_configs:
            with self.subTest(raw=raw):
                ChunkingConfig.from_mapping(raw)

    def test_chunk_sizes_reject_values_just_outside_their_ranges(self):
        invalid_configs = (
            ({"chunk_size": 127}, "chunk_size must be between 128 and 4096"),
            ({"chunk_size": 4097}, "chunk_size must be between 128 and 4096"),
            ({"parent_chunk_size": 511}, "parent_chunk_size must be between 512 and 8192"),
            ({"parent_chunk_size": 8193}, "parent_chunk_size must be between 512 and 8192"),
            ({"child_chunk_size": 127}, "child_chunk_size must be between 128 and 2048"),
            (
                {"parent_chunk_size": 8192, "child_chunk_size": 2049},
                "child_chunk_size must be between 128 and 2048",
            ),
        )

        for raw, message in invalid_configs:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, message):
                    ChunkingConfig.from_mapping(raw)

    def test_layout_strategy_is_accepted(self):
        config = ChunkingConfig.from_mapping({"strategy": "layout"})

        self.assertEqual(config.strategy, "layout")

    def test_non_boolean_enable_parent_child_is_rejected(self):
        for value in ("false", 0, 1, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "enable_parent_child must be a boolean"):
                    ChunkingConfig.from_mapping({"enable_parent_child": value})

    def test_invalid_configurations_are_rejected(self):
        invalid_configs = (
            {"strategy": "unrecognized"},
            {"chunk_size": 0},
            {"chunk_size": 256, "chunk_overlap": 129},
            {"parent_chunk_size": 512, "child_chunk_size": 513},
            {"child_chunk_size": 256, "child_chunk_overlap": 129},
            {"token_limit": -1},
            {"semantic_window_size": 0},
            {"semantic_breakpoint_percentile": 101},
        )

        for raw in invalid_configs:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    ChunkingConfig.from_mapping(raw)
