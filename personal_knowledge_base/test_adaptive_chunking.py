from django.test import SimpleTestCase

from personal_knowledge_base.chunking import ChunkingConfig
from personal_knowledge_base.chunking.service import split_document
from personal_knowledge_base.document_parsing.types import ImageBlock, ParsedDocument, TextBlock


def markdown_document():
    return ParsedDocument(
        text_blocks=[
            TextBlock("# Install", 0, block_type="heading", metadata={"heading_level": 1}),
            TextBlock("Choose a supported package manager before continuing.", 1, block_type="paragraph"),
            TextBlock("## Linux", 2, block_type="heading", metadata={"heading_level": 2}),
            TextBlock("Run the installer, then verify the service is active.", 3, block_type="paragraph"),
        ]
    )


def workbook_document():
    return ParsedDocument(
        text_blocks=[
            TextBlock(
                "Quarter | Amount",
                0,
                block_type="record",
                source_start=1,
                source_end=1,
                metadata={"sheet_name": "Revenue", "headers": ["Quarter", "Amount"], "row_start": 1},
            ),
            TextBlock(
                "Q1 | 100",
                1,
                block_type="record",
                source_start=2,
                source_end=2,
                metadata={"sheet_name": "Revenue", "headers": ["Quarter", "Amount"], "row_start": 2},
            ),
            TextBlock(
                "Q2 | 120",
                2,
                block_type="record",
                source_start=3,
                source_end=3,
                metadata={"sheet_name": "Revenue", "headers": ["Quarter", "Amount"], "row_start": 3},
            ),
        ]
    )


def tiny_heading_document():
    return ParsedDocument(
        text_blocks=[
            TextBlock(
                f"# {letter}",
                index,
                block_type="heading",
                metadata={"heading_level": 1},
            )
            for index, letter in enumerate("ABCDE")
        ]
    )


class AdaptiveChunkingTests(SimpleTestCase):
    def test_markdown_auto_uses_heading_and_breadcrumbs(self):
        result = split_document(markdown_document(), ChunkingConfig(), title="Guide")

        self.assertEqual(result.diagnostics.selected_strategy, "heading")
        self.assertIn("Guide > Install > Linux", result.children[-1].context_header)

    def test_record_split_repeats_sheet_and_headers(self):
        result = split_document(
            workbook_document(),
            ChunkingConfig(child_chunk_size=128),
            title="Sales",
        )

        self.assertEqual(result.diagnostics.selected_strategy, "record")
        self.assertTrue(all("Revenue" in chunk.context_header for chunk in result.children))
        self.assertTrue(all("Quarter" in chunk.context_header for chunk in result.children))

    def test_invalid_heading_output_falls_back_to_recursive(self):
        result = split_document(tiny_heading_document(), ChunkingConfig(), title="Notes")

        self.assertEqual(result.diagnostics.fallback_chain[0]["strategy"], "heading")
        self.assertEqual(result.diagnostics.selected_strategy, "recursive")
        self.assertIn("excessive_tiny_chunks", result.diagnostics.fallback_chain[0]["reason"])

    def test_page_blocks_auto_use_layout_context(self):
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock("First page introduction.", 0, page_index=0, block_type="paragraph"),
                TextBlock("Second page conclusion.", 1, page_index=1, block_type="paragraph"),
            ]
        )

        result = split_document(parsed, ChunkingConfig(), title="Report")

        self.assertEqual(result.diagnostics.selected_strategy, "layout")
        self.assertIn("Report > Page 1", result.children[0].context_header)
        self.assertIn("Report > Page 2", result.children[-1].context_header)

    def test_layout_image_is_a_hard_boundary_with_child_specific_coverage(self):
        before = "Before image detail. " * 16
        after = "After image detail. " * 16
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock(before, 0, page_index=0, block_type="paragraph"),
                TextBlock(after, 2, page_index=0, block_type="paragraph"),
            ],
            images=[ImageBlock(b"image", "image/png", 100, 100, "pdf_embedded", "page:1", 1, 0)],
        )

        result = split_document(
            parsed,
            ChunkingConfig(parent_chunk_size=512, child_chunk_size=128, child_chunk_overlap=0),
            title="Report",
        )

        canonical = before + "\n\n" + after
        self.assertEqual(result.diagnostics.selected_strategy, "layout")
        self.assertTrue(all(draft.content == canonical[draft.start_at:draft.end_at] for draft in result.parents))
        self.assertEqual(result.parents[0].start_at, 0)
        self.assertEqual(result.parents[-1].end_at, len(canonical))
        self.assertFalse(any(parent.metadata["block_indices"] == [0, 2] for parent in result.parents))
        before_children = [child for child in result.children if child.end_at <= len(before)]
        after_children = [child for child in result.children if child.start_at >= len(before) + 2]
        self.assertGreater(len(before_children), 1)
        self.assertGreater(len(after_children), 1)
        self.assertTrue(all(child.metadata["block_indices"] == [0] for child in before_children))
        self.assertTrue(all(child.metadata["block_indices"] == [2] for child in after_children))
        self.assertTrue(
            all({ref["block_index"] for ref in child.metadata["source_refs"]} == {0} for child in before_children)
        )
        self.assertTrue(
            all({ref["block_index"] for ref in child.metadata["source_refs"]} == {2} for child in after_children)
        )

    def test_plain_text_auto_uses_recursive_with_deterministic_ranges(self):
        text = "Alpha paragraph has useful details.\n\n" + "Beta sentence. " * 30
        parsed = ParsedDocument(text_blocks=[TextBlock(text, 0)])
        config = ChunkingConfig(enable_parent_child=False, chunk_size=128, chunk_overlap=16)

        first = split_document(parsed, config, title="Plain")
        second = split_document(parsed, config, title="Plain")

        self.assertEqual(first.diagnostics.selected_strategy, "recursive")
        self.assertEqual(
            [(chunk.content, chunk.start_at, chunk.end_at) for chunk in first.children],
            [(chunk.content, chunk.start_at, chunk.end_at) for chunk in second.children],
        )
        self.assertEqual(first.children[0].start_at, 0)
        self.assertEqual(first.children[-1].end_at, len(text))
        self.assertTrue(all(chunk.content == text[chunk.start_at:chunk.end_at] for chunk in first.children))

    def test_canonical_source_preserves_block_whitespace_and_join_ranges(self):
        first_block = "  Alpha details.\n"
        second_block = "\nBeta details.  "
        canonical = first_block + "\n\n" + second_block
        result = split_document(
            ParsedDocument(
                text_blocks=[
                    TextBlock(first_block, 0),
                    TextBlock(second_block, 1),
                ]
            ),
            ChunkingConfig(enable_parent_child=False, chunk_size=128, chunk_overlap=0),
            title="Whitespace",
        )

        self.assertEqual(result.children[0].content, canonical)
        self.assertEqual(result.children[0].start_at, 0)
        self.assertEqual(result.children[0].end_at, len(canonical))
        self.assertEqual(
            result.children[0].end_at - result.children[0].start_at,
            len(result.children[0].content),
        )

    def test_empty_terminal_block_does_not_extend_canonical_source(self):
        result = split_document(
            ParsedDocument(text_blocks=[TextBlock("Alpha details.", 0), TextBlock("", 1)]),
            ChunkingConfig(enable_parent_child=False, chunk_size=128, chunk_overlap=0),
            title="Whitespace",
        )

        self.assertEqual(result.children[-1].content, "Alpha details.")
        self.assertEqual(result.children[-1].end_at, len("Alpha details."))

    def test_empty_blocks_do_not_add_content_or_separators(self):
        first_block = "  Alpha details.\n"
        second_block = "\nBeta details.  "
        canonical = first_block + "\n\n" + second_block
        result = split_document(
            ParsedDocument(
                text_blocks=[
                    TextBlock("", 0),
                    TextBlock(first_block, 1),
                    TextBlock("", 2),
                    TextBlock(second_block, 3),
                    TextBlock("", 4),
                ]
            ),
            ChunkingConfig(enable_parent_child=False, chunk_size=128, chunk_overlap=0),
            title="Whitespace",
        )

        self.assertEqual(result.children[0].content, canonical)
        self.assertEqual(result.children[0].start_at, 0)
        self.assertEqual(result.children[0].end_at, len(canonical))

    def test_parent_child_drafts_are_ordered_and_linked_by_index(self):
        text = "  " + " ".join(f"sentence-{index}" for index in range(260)) + "\n"
        parsed = ParsedDocument(text_blocks=[TextBlock(text, 0)])
        config = ChunkingConfig(parent_chunk_size=512, child_chunk_size=128, child_chunk_overlap=16)

        result = split_document(parsed, config, title="Long")

        self.assertGreater(len(result.parents), 1)
        self.assertTrue(all(parent.chunk_type == "parent_text" for parent in result.parents))
        self.assertTrue(all(child.chunk_type == "text" for child in result.children))
        self.assertTrue(all(child.context_parent_index is not None for child in result.children))
        for child in result.children:
            parent = result.parents[child.context_parent_index]
            self.assertLessEqual(parent.start_at, child.start_at)
            self.assertGreaterEqual(parent.end_at, child.end_at)
        for draft in [*result.parents, *result.children]:
            self.assertEqual(draft.content, text[draft.start_at:draft.end_at])
            self.assertEqual(draft.end_at - draft.start_at, len(draft.content))
        self.assertEqual(result.parents[-1].end_at, len(text))
        self.assertEqual(result.children[-1].end_at, len(text))

    def test_tables_and_inline_structures_are_not_cut(self):
        table = "Column A | Column B\n" + "protected value | 100\n" * 8
        fenced = "```python\n" + "print('protected')\n" * 8 + "```"
        inline = "See [the complete installation guide](https://example.com/a/very/long/path) and ![diagram](images/flow.png)."
        formula = "The invariant is $$" + "x_1 + x_2 + x_3 = y " * 6 + "$$ for every record."
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock(table, 0, block_type="table"),
                TextBlock(fenced, 1, block_type="paragraph"),
                TextBlock(inline, 2, block_type="paragraph"),
                TextBlock(formula, 3, block_type="paragraph"),
            ]
        )
        config = ChunkingConfig(enable_parent_child=False, chunk_size=128, chunk_overlap=0)

        result = split_document(parsed, config, title="Protected")

        self.assertTrue(any(table in chunk.content for chunk in result.children))
        self.assertTrue(any(fenced in chunk.content for chunk in result.children))
        self.assertTrue(any("[the complete installation guide](https://example.com/a/very/long/path)" in chunk.content for chunk in result.children))
        self.assertTrue(any("![diagram](images/flow.png)" in chunk.content for chunk in result.children))
        self.assertTrue(any("$$" + "x_1 + x_2 + x_3 = y " * 6 + "$$" in chunk.content for chunk in result.children))

    def test_parent_child_preserves_long_structural_blocks_in_children(self):
        protected_blocks = [
            ("table", "table-cell " * 36),
            ("code", "code-statement " * 30),
            ("formula", "formula-term " * 30),
            ("link", "link-target " * 36),
            ("image_reference", "image-target " * 30),
        ]
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock(content, index, block_type=block_type)
                for index, (block_type, content) in enumerate(protected_blocks)
            ]
        )

        result = split_document(
            parsed,
            ChunkingConfig(
                parent_chunk_size=512,
                child_chunk_size=128,
                child_chunk_overlap=0,
            ),
            title="Protected",
        )

        self.assertTrue(result.parents)
        for _block_type, content in protected_blocks:
            self.assertTrue(
                any(content in child.content for child in result.children),
                msg=f"protected block was split: {content[:20]}",
            )

    def test_token_limit_keeps_protected_closing_boundaries_intact(self):
        protected_objects = {
            "table": "| heading |\n" + "| table-value |\n" * 18,
            "code": "```python\n" + "print('code-value')\n" * 18 + "```",
            "formula": "$$ " + "formula-value " * 18 + "$$",
            "link": "[" + "link-label " * 18 + "](https://example.com/protected)",
            "image_reference": "![" + "image-label " * 18 + "](images/protected.png)",
        }

        for block_type, protected in protected_objects.items():
            with self.subTest(block_type=block_type):
                source = "prefix\n\n" + protected
                result = split_document(
                    ParsedDocument(
                        text_blocks=[
                            TextBlock("prefix", 0),
                            TextBlock(protected, 1, block_type=block_type),
                        ]
                    ),
                    ChunkingConfig(
                        strategy="recursive",
                        enable_parent_child=False,
                        chunk_size=len(source),
                        chunk_overlap=0,
                        token_limit=len(protected.split()),
                    ),
                    title="Protected",
                    token_counter=lambda value: len(value.split()),
                )

                self.assertTrue(any(protected in child.content for child in result.children))
                self.assertTrue(
                    all(len(child.content.split()) <= len(protected.split()) for child in result.children)
                )

    def test_custom_token_counter_enforces_hard_limit_and_is_reported(self):
        text = " ".join(f"word{index}" for index in range(45))

        result = split_document(
            ParsedDocument(text_blocks=[TextBlock(text, 0)]),
            ChunkingConfig(enable_parent_child=False, chunk_size=128, chunk_overlap=0, token_limit=7),
            title="Tokens",
            token_counter=lambda value: len(value.split()),
        )

        self.assertEqual(result.diagnostics.token_counter_source, "custom")
        self.assertTrue(all(len(chunk.content.split()) <= 7 for chunk in result.children))
        self.assertLessEqual(result.diagnostics.size_statistics["children"]["max_tokens"], 7)

    def test_markdown_heading_syntax_is_recognized_inside_text_blocks(self):
        text = "# Install\nPackage setup.\n\n## Linux\nUse the service manager."

        result = split_document(
            ParsedDocument(text_blocks=[TextBlock(text, 0)]),
            ChunkingConfig(),
            title="Guide",
        )

        self.assertEqual(result.diagnostics.selected_strategy, "heading")
        self.assertIn("Guide > Install > Linux", result.children[-1].context_header)

    def test_diagnostics_include_request_fallback_sizes_and_duration(self):
        result = split_document(
            ParsedDocument(text_blocks=[TextBlock("A complete short note.", 0)]),
            ChunkingConfig(),
            title="Note",
        )

        self.assertEqual(result.diagnostics.requested_strategy, "auto")
        self.assertEqual(result.diagnostics.fallback_chain, [])
        self.assertEqual(result.diagnostics.size_statistics["parents"]["count"], 1)
        self.assertEqual(result.diagnostics.size_statistics["children"]["count"], 1)
        self.assertGreaterEqual(result.diagnostics.duration, 0)
        self.assertEqual(result.diagnostics.token_counter_source, "character_estimate")
