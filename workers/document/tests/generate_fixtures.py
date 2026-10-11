"""Create small original MIT-licensed static fixtures; tests never regenerate them."""
import base64
import hashlib
import io
import json
from pathlib import Path

import pymupdf as fitz
from docx import Document
from docx.shared import Inches as DocxInches
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches
import xlwt

ROOT = Path(__file__).parent / 'fixtures'
ROOT.mkdir(exist_ok=True)
(ROOT / 'unicode.txt').write_text('季度收入😀\nQ1 100\n', encoding='utf-8')
image = Image.new('RGB', (160, 96), 'white')
draw = ImageDraw.Draw(image)
for x in range(160):
    draw.line((x, 0, x, 95), fill=(x, 120, 255-x))
draw.text((8, 30), 'MARLIN 100', fill='black')
image.save(ROOT / 'image.png')
svg = '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="96" height="96" fill="navy"/><text x="4" y="48" fill="white">Marlin</text><!--' + 'fixture ' * 80 + '--></svg>'
(ROOT / 'image.svg').write_text(svg, encoding='utf-8')
(ROOT / 'unicode.md').write_text('# 收入😀\n\nBefore\n\n![inline](data:image/png;base64,' + base64.b64encode((ROOT / 'image.png').read_bytes()).decode() + ')\n\nAfter\n\n![relative](missing.png)\n\n![blocked](http://127.0.0.1/image.png)\n', encoding='utf-8')
(ROOT / 'records.csv').write_text('姓名,收入\n😀,100\n', encoding='utf-8')
(ROOT / 'example.json').write_text('{"income":100,"name":"😀"}', encoding='utf-8')
(ROOT / 'example.html').write_text('<style>hidden</style><h1>收入😀</h1><p>100</p><script>hidden</script>', encoding='utf-8')
(ROOT / 'empty.txt').write_bytes(b'')
(ROOT / 'bad.pdf').write_bytes(b'not a PDF')
(ROOT / 'bad.png').write_bytes(b'not an image')
Image.new('RGB',(16,16),'white').save(ROOT/'small.png')
doc = Document()
doc.add_heading('季度收入😀', level=1)
p = doc.add_paragraph('Before')
p.add_run().add_picture(str(ROOT / 'image.png'), width=DocxInches(1))
p.add_run('After')
t = doc.add_table(rows=2, cols=2)
t.cell(0,0).text='Quarter'; t.cell(0,1).text='Income'; t.cell(1,0).text='Q1'; t.cell(1,1).text='100'
t.cell(1,1).paragraphs[0].add_run().add_picture(str(ROOT / 'image.png'), width=DocxInches(1))
doc.save(ROOT / 'table.docx')
xls=xlwt.Workbook(); xs=xls.add_sheet('Revenue'); xs.write(0,0,'Quarter'); xs.write(0,1,'Income'); xs.write(1,0,'Q1'); xs.write(1,1,100); xs.write_merge(2,2,0,1,'merged'); xls.save(str(ROOT/'records.xls'))
book=Workbook(); sheet=book.active; sheet.title='Revenue'
sheet.append(['Quarter','Income']); sheet.append(['Q1',100]); sheet.append(['Total','=SUM(B2:B2)']); sheet.merge_cells('A4:B4'); sheet['A4']='merged'; book.create_sheet('Empty'); book.save(ROOT / 'records.xlsx')
pres=Presentation(); s=pres.slides.add_slide(pres.slide_layouts[6]); box=s.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)); box.text='Slide 1 收入😀'
table=s.shapes.add_table(2,2,Inches(1),Inches(2),Inches(3),Inches(1)).table
table.cell(0,0).text='Quarter'; table.cell(0,1).text='Income'; table.cell(1,0).text='Q1'; table.cell(1,1).text='100'
s.shapes.add_picture(str(ROOT / 'image.png'), Inches(1), Inches(4), width=Inches(2))
s=pres.slides.add_slide(pres.slide_layouts[6]); group=s.shapes.add_group_shape(); group.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text='Slide 2 nested'; pres.save(ROOT / 'slides.pptx')
pdf=fitz.open(); p=pdf.new_page(); p.insert_text((72,72),'Quarterly income fixture with enough text for extraction'); p.insert_text((72,100),'Q1 revenue 100'); pdf.save(ROOT / 'text.pdf'); pdf.close()
scan=Image.new('RGB',(640,480),'white'); d=ImageDraw.Draw(scan); font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',28); d.text((40,40),'Quarterly income',font=font,fill='black'); d.text((40,100),'Q1    100',font=font,fill='black'); d.line((30,150,500,150),fill='black',width=2)
buf=io.BytesIO(); scan.save(buf,format='PNG'); pdf=fitz.open(); p=pdf.new_page(width=640,height=480); p.insert_image(p.rect,stream=buf.getvalue()); pdf.save(ROOT / 'scanned.pdf', deflate=True); pdf.close()
manifest = {
    'version':'parser-fixtures-v1',
    'source':'Original fixtures authored for this project; MIT (../../../../LICENSE). No real user data. legacy/ is Apache POI test data, Apache-2.0; see legacy/README.md and legacy/LICENSE.',
    'expectations':{
        'unicode.txt':(ROOT/'unicode.txt').read_text(encoding='utf-8'),
        'table.docx':'heading; Before/image/After; Quarter | Income table; table_cell image',
        'records.xlsx':'Revenue rows, formula fallback =SUM(B2:B2), merge A4:B4; Empty omitted',
        'records.xls':'Revenue rows, Q1 | 100.0, merge A3:B3; cached cells',
        'slides.pptx':'Slide 1, table, picture, Slide 2 nested group',
        'text.pdf':'Quarterly income fixture; Q1 revenue 100',
        'scanned.pdf':'image only, scanned_pdf, 150 dpi JPEG; no OCR text',
        'image.svg':'PNG artifact with original image/svg+xml',
        'legacy/sample.doc':'converter unavailable unless real LibreOffice installed; never mocked success',
        'legacy/sample.ppt':'converter unavailable unless real LibreOffice installed; never mocked success',
    },
    'sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and p.name != 'manifest.json'},
}
(ROOT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
