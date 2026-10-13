"""PDF 块内排版行合并（_join_pdf_block_lines）的规则测试。

背景：PyMuPDF 按版面把段落拆成视觉行，直接 "\n".join 会把行换行与断词连字符
永久写入切片正文。规则依据 vmm 库真实数据的抽样统计设计。
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from personal_knowledge_base.document_parsing.registry import _join_pdf_block_lines  # noqa: E402


class JoinPdfBlockLinesTests(SimpleTestCase):
    def test_latin_lines_join_with_single_space(self):
        joined = _join_pdf_block_lines([
            "This survey is both a chronologically and",
            "categorically structured account of the",
            "technical components of motion magnification.",
        ])
        self.assertEqual(
            joined,
            "This survey is both a chronologically and categorically structured account of the technical components of motion magnification.",
        )
        self.assertNotIn("\n", joined)

    def test_syllable_hyphen_break_removes_hyphen(self):
        # vmm 库高频形态：排版音节断行
        self.assertEqual(_join_pdf_block_lines(["This is an opi-", "cal flow method."]), "This is an opical flow method.")
        self.assertEqual(_join_pdf_block_lines(["The informa-", "tion is amplified."]), "The information is amplified.")
        self.assertEqual(_join_pdf_block_lines(["Un-", "fortunately it fails."]), "Unfortunately it fails.")

    def test_compound_prefix_hyphen_keeps_hyphen(self):
        # 真实复合词在连字符处断行：保留连字符
        self.assertEqual(_join_pdf_block_lines(["It is a non-", "static method."]), "It is a non-static method.")
        self.assertEqual(_join_pdf_block_lines(["The band-", "pass filter amplifies."]), "The band-pass filter amplifies.")
        self.assertEqual(_join_pdf_block_lines(["These phase-", "based methods work."]), "These phase-based methods work.")
        self.assertEqual(_join_pdf_block_lines(["Human-", "centered computing."]), "Human-centered computing.")

    def test_multi_hyphen_token_keeps_hyphen(self):
        # state-of- 断行：词干含多个连字符，保守保留
        self.assertEqual(_join_pdf_block_lines(["a state-of-", "the-art method."]), "a state-of-the-art method.")

    def test_cjk_lines_join_without_space(self):
        self.assertEqual(_join_pdf_block_lines(["运动放大是一种", "放大视频中微小运动的技术。"]), "运动放大是一种放大视频中微小运动的技术。")

    def test_mixed_cjk_latin(self):
        joined = _join_pdf_block_lines(["运动放大 Motion Magnification 是", "一种视频处理技术。"])
        self.assertEqual(joined, "运动放大 Motion Magnification 是一种视频处理技术。")

    def test_blank_lines_dropped(self):
        self.assertEqual(_join_pdf_block_lines(["first", "", "  ", "second"]), "first second")

    def test_empty_input(self):
        self.assertEqual(_join_pdf_block_lines([]), "")
        self.assertEqual(_join_pdf_block_lines(["", "  "]), "")


if __name__ == "__main__":
    import unittest

    unittest.main()
