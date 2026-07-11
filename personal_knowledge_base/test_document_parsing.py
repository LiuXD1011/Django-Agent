import base64
import io
import random

from django.test import SimpleTestCase
from PIL import Image

from personal_knowledge_base.document_parsing import parse_document
from personal_knowledge_base.document_parsing.remote_images import UnsafeRemoteImageError, validate_remote_url


def image_bytes(fmt="PNG", size=(96, 96)):
    image = Image.frombytes("RGB", size, random.Random(42).randbytes(size[0] * size[1] * 3))
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


class DocumentParsingTests(SimpleTestCase):
    def test_plain_alias_uses_builtin_text_parser(self):
        parsed = parse_document("notes.txt", "第一段\n\n第二段".encode(), engine="plain")
        self.assertEqual([block.text for block in parsed.text_blocks], ["第一段\n\n第二段"])
        self.assertEqual(parsed.images, [])

    def test_standalone_image_becomes_an_image_block(self):
        parsed = parse_document("diagram.png", image_bytes())
        self.assertEqual(len(parsed.images), 1)
        self.assertEqual(parsed.images[0].source_type, "standalone")
        self.assertEqual((parsed.images[0].width, parsed.images[0].height), (96, 96))
        self.assertEqual(parsed.images[0].block_index, 0)

    def test_markdown_data_uri_preserves_order_and_extracts_image(self):
        encoded = base64.b64encode(image_bytes()).decode()
        markdown = f"前文\n\n![结构图](data:image/png;base64,{encoded})\n\n后文"
        parsed = parse_document("readme.md", markdown.encode())
        self.assertEqual(len(parsed.images), 1)
        self.assertEqual(parsed.images[0].source_type, "markdown_data")
        self.assertLess(parsed.text_blocks[0].block_index, parsed.images[0].block_index)
        self.assertLess(parsed.images[0].block_index, parsed.text_blocks[-1].block_index)

    def test_private_remote_markdown_image_is_rejected(self):
        with self.assertRaises(UnsafeRemoteImageError):
            validate_remote_url("http://127.0.0.1/private.png")

    def test_docx_inline_image_is_extracted_between_text(self):
        import docx
        document = docx.Document()
        document.add_paragraph("图片之前")
        document.add_paragraph().add_run().add_picture(io.BytesIO(image_bytes()))
        document.add_paragraph("图片之后")
        stream = io.BytesIO()
        document.save(stream)
        parsed = parse_document("manual.docx", stream.getvalue())
        self.assertEqual(len(parsed.images), 1)
        self.assertEqual(parsed.images[0].source_type, "docx")
        self.assertLess(parsed.text_blocks[0].block_index, parsed.images[0].block_index)
        self.assertLess(parsed.images[0].block_index, parsed.text_blocks[-1].block_index)

    def test_docx_table_image_is_extracted_with_table_content(self):
        import docx

        document = docx.Document()
        table = document.add_table(rows=1, cols=1)
        cell = table.cell(0, 0)
        cell.text = "表格说明"
        cell.paragraphs[0].add_run().add_picture(io.BytesIO(image_bytes()))
        stream = io.BytesIO()
        document.save(stream)

        parsed = parse_document("table.docx", stream.getvalue())

        self.assertIn("表格说明", "\n".join(block.text for block in parsed.text_blocks))
        self.assertEqual(len(parsed.images), 1)
        self.assertEqual(parsed.images[0].source_type, "docx")

    def test_pptx_extracts_text_and_picture(self):
        from pptx import Presentation
        from pptx.util import Inches
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        textbox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
        textbox.text = "季度趋势"
        slide.shapes.add_picture(io.BytesIO(image_bytes()), Inches(1), Inches(2))
        stream = io.BytesIO()
        presentation.save(stream)
        parsed = parse_document("report.pptx", stream.getvalue())
        self.assertIn("季度趋势", "\n".join(block.text for block in parsed.text_blocks))
        self.assertEqual(len(parsed.images), 1)
        self.assertEqual(parsed.images[0].source_type, "pptx")
        self.assertEqual(parsed.images[0].page_index, 0)

    def test_scanned_pdf_page_is_rendered_as_image(self):
        import fitz
        pdf = fitz.open()
        page = pdf.new_page(width=300, height=300)
        page.insert_image(fitz.Rect(0, 0, 300, 300), stream=image_bytes(size=(128, 128)))
        data = pdf.tobytes()
        pdf.close()
        parsed = parse_document("scan.pdf", data)
        self.assertEqual(len(parsed.images), 1)
        self.assertEqual(parsed.images[0].source_type, "scanned_pdf")
        self.assertEqual(parsed.images[0].page_index, 0)
