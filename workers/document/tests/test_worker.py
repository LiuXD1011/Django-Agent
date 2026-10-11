import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures'


class WorkerTests(unittest.TestCase):
    def test_static_fixture_manifest_hashes_and_expected_unicode(self):
        manifest=json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8'))
        for name,digest in manifest['sha256'].items():
            self.assertEqual(hashlib.sha256((FIXTURES/name).read_bytes()).hexdigest(),digest,name)
        self.assertEqual(manifest['expectations']['unicode.txt'],'季度收入😀\nQ1 100\n')

    def request(self, name=None, **overrides):
        with tempfile.TemporaryDirectory() as temp:
            request = {'protocol': 1, 'id': 'test', 'operation': 'capabilities'}
            if name is not None:
                path=FIXTURES / name; data=path.read_bytes()
                request.update(operation='parse', input={'path':str(path),'name':name,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}, artifact_dir=temp)
            request.update(overrides)
            env = {k:v for k,v in os.environ.items() if k != 'DJANGO_SETTINGS_MODULE'}
            proc=subprocess.run([sys.executable,'-B',str(ROOT/'worker.py')],input=json.dumps(request)+'\n',text=True,capture_output=True,env=env,timeout=20)
            self.assertEqual(proc.returncode,0,proc.stderr)
            messages=[json.loads(line) for line in proc.stdout.splitlines()]
            self.assertTrue(messages)
            self.assertTrue(all(m['protocol']==1 and m['id']=='test' for m in messages))
            final=messages[-1]
            if final['type']=='result' and name is not None:
                result=final['result']; text=result['document']['canonical_text']; self.assertEqual(result['document']['canonical_sha256'],hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(result['document']['offset_unit'],'unicode_code_point')
                for b in result['blocks']:
                    if b['kind']=='text':
                        r=b['canonical_range']; self.assertEqual(text[r['start']:r['end']],b['text'])
                    else:
                        p=Path(temp)/b['artifact_path']; content=p.read_bytes()
                        self.assertEqual(b['sha256'],hashlib.sha256(content).hexdigest()); self.assertFalse(Path(b['artifact_path']).is_absolute())
                        from PIL import Image
                        import io
                        with Image.open(io.BytesIO(content)) as im:
                            self.assertEqual(Image.MIME[im.format],b['mime_type']); self.assertEqual(im.size,(b['width'],b['height']))
            return final

    def parse(self,name,**overrides):
        final=self.request(name,**overrides); self.assertEqual(final['type'],'result',final); return final['result']

    def test_capabilities_have_format_availability_and_no_ocr_claim(self):
        result=self.request()['result']; self.assertTrue(result['format_status']['txt']); self.assertFalse(result['ocr_available'])

    def test_unicode_canonical_ranges(self):
        r=self.parse('unicode.txt'); self.assertEqual(r['document']['canonical_text'],'季度收入😀\nQ1 100\n'); self.assertEqual(r['blocks'][0]['canonical_range']['end'],13)

    def test_markdown_order_and_failure_warnings(self):
        r=self.parse('unicode.md'); self.assertEqual([b['kind'] for b in r['blocks']][:3],['text','image','text']); self.assertEqual({w['code'] for w in r['warnings']},{'relative_image_unavailable','image_fetch_failed'})
        self.assertIn('missing.png',[source['source_ref'] for source in r['diagnostics'].get('warning_sources',[])])

    def test_docx_embedded_images_and_table(self):
        r=self.parse('table.docx'); self.assertEqual([b['kind'] for b in r['blocks']][:4],['text','text','image','text']); table=next(b for b in r['blocks'] if b.get('block_type')=='table'); self.assertEqual(table['metadata']['rows'][1],['Q1','100']); self.assertTrue(any('table_cell' in b['provenance'] for b in r['blocks'] if b['kind']=='image'))

    def test_csv_xlsx_pptx_pdf_actual_files(self):
        self.assertIn('😀 | 100',self.parse('records.csv')['document']['canonical_text'])
        r=self.parse('records.xlsx'); self.assertTrue(all(b['block_type']=='record' for b in r['blocks'])); self.assertEqual(r['blocks'][2]['provenance']['cell_provenance'][1]['source'],'formula'); self.assertEqual(r['blocks'][0]['provenance']['merged_ranges'],['A4:B4'])
        r=self.parse('slides.pptx'); self.assertIn('Slide 2 nested',r['document']['canonical_text']); self.assertEqual(r['blocks'][-1]['provenance']['shape_path'],[0,0])
        r=self.parse('text.pdf'); self.assertIn('Q1 revenue 100',r['document']['canonical_text']); self.assertEqual(r['blocks'][0]['provenance']['unit'],'pdf_point')

    def test_scanned_pdf_is_actual_page_image(self):
        r=self.parse('scanned.pdf'); self.assertEqual(r['document']['canonical_text'],''); self.assertEqual(r['blocks'][0]['provenance']['source_type'],'scanned_pdf'); self.assertEqual(r['blocks'][0]['mime_type'],'image/jpeg')

    def test_svg_actual_png_bytes_and_original_mime(self):
        r=self.parse('image.svg'); self.assertEqual(r['blocks'][0]['mime_type'],'image/png'); self.assertEqual(r['blocks'][0]['original_mime_type'],'image/svg+xml')
        self.parse('image.png')

    def test_bad_empty_and_unsupported(self):
        self.assertEqual(self.parse('empty.txt')['blocks'],[])
        bad_image=self.request('bad.png')
        self.assertEqual(bad_image['type'],'error',bad_image)
        self.assertEqual(bad_image['error'],{'code':'parse_failed','message':'The document could not be parsed','retryable':False})
        self.assertEqual(self.request('bad.pdf')['type'],'error')
        path=FIXTURES/'unicode.txt'; data=path.read_bytes(); r=self.request('unicode.txt',input={'path':str(path),'name':'sample.docm','sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}); self.assertEqual(r['error']['code'],'unsupported_file_type')

    def test_invalid_standalone_svg_returns_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'malformed.svg'; data=b'<svg xmlns="http://www.w3.org/2000/svg"><unclosed'
            path.write_bytes(data)
            final=self.request('unicode.txt',input={'path':str(path),'name':path.name,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)})
            self.assertEqual(final['type'],'error',final)
            self.assertEqual(final['error']['code'],'parse_failed')
            self.assertFalse(final['error']['retryable'])

    def test_valid_blank_images_preserve_blocks_or_small_image_warnings(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            for extension in ('bmp','png'):
                with self.subTest(extension=extension):
                    path=Path(temp)/f'blank.{extension}'
                    Image.new('RGB',(96,96),'white').save(path)
                    data=path.read_bytes()
                    final=self.request('unicode.txt',input={'path':str(path),'name':path.name,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)})
                    self.assertEqual(final['type'],'result',final)
                    result=final['result']; self.assertEqual(result['document']['canonical_text'],'')
                    if extension=='bmp':
                        self.assertGreaterEqual(len(data),512)
                        self.assertEqual(len(result['blocks']),1)
                        self.assertEqual(result['blocks'][0]['kind'],'image')
                        self.assertEqual(result['blocks'][0]['mime_type'],'image/bmp')
                        self.assertEqual(result['warnings'],[])
                    else:
                        self.assertLess(len(data),512)
                        self.assertEqual(result['blocks'],[])
                        self.assertEqual(result['warnings'][0]['code'],'invalid_or_small_image')
                    self.assertFalse(result['diagnostics']['ocr_performed'])

    def test_corrupt_embedded_markdown_image_keeps_text_and_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'embedded.md'
            data=b'Before\n\n![broken](data:image/png;base64,bm90IGFuIGltYWdl)\n\nAfter'
            path.write_bytes(data)
            final=self.request('unicode.txt',input={'path':str(path),'name':path.name,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)})
            self.assertEqual(final['type'],'result',final)
            result=final['result']
            self.assertEqual(result['document']['canonical_text'],data.decode())
            self.assertEqual([block['kind'] for block in result['blocks']],['text','text','text'])
            self.assertEqual(result['warnings'][0]['code'],'image_fetch_failed')
            self.assertEqual(result['diagnostics']['warning_sources'][0]['source_ref'],'data:image/png;base64,bm90IGFuIGltYWdl')

    def test_identity_and_limits(self):
        self.assertEqual(self.request('unicode.txt',limits={'max_input_bytes':1})['error']['code'],'input_limit_exceeded')
        self.assertEqual(self.request('image.png',limits={'max_artifact_bytes':1})['error']['code'],'artifact_limit_exceeded')
        self.assertEqual(self.request('slides.pptx',limits={'max_pages':1})['error']['code'],'page_limit_exceeded')
        self.assertEqual(self.request('table.docx',limits={'max_images':1})['error']['code'],'image_limit_exceeded')
        data=(FIXTURES/'unicode.txt').read_bytes(); self.assertEqual(self.request('unicode.txt',input={'path':str(FIXTURES/'unicode.txt'),'name':'unicode.txt','sha256':'0'*64,'size_bytes':len(data)})['error']['code'],'input_hash_mismatch')

    def test_xls_actual_static_file(self):
        r=self.parse('records.xls'); self.assertEqual(r['blocks'][0]['provenance']['sheet_name'],'Revenue'); self.assertEqual(r['blocks'][0]['provenance']['merged_ranges'],['A3:B3']); self.assertIn('Q1 | 100',r['document']['canonical_text'])

    def test_real_legacy_files_have_explicit_converter_result(self):
        caps=self.request()['result']
        for name in ('legacy/sample.doc','legacy/sample.ppt'):
            path=FIXTURES/name; data=path.read_bytes()
            final=self.request('unicode.txt',input={'path':str(path),'name':path.name,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)})
            if caps['dependency_status']['LibreOffice']:
                self.assertEqual(final['type'],'result',final); self.assertTrue(final['result']['blocks'])
            else:
                self.assertEqual(final['error']['code'],'legacy_office_converter_unavailable')
                self.assertFalse(caps['format_status'][path.suffix[1:]])

    def test_capabilities_survive_missing_optional_native_modules(self):
        probe = """import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'PIL','cairosvg','fitz','pymupdf','docx','pptx','requests','openpyxl','xlrd','msoffcrypto'}: raise ImportError('optional missing')
sys.meta_path.insert(0,Block())
sys.path.insert(0,sys.argv[1])
from parser import parser_capabilities
cap=parser_capabilities()
assert cap['format_status']['txt'] and not cap['format_status']['svg']
from parser import parse_document
assert parse_document('test.txt',b'hello').text_blocks[0].text=='hello'
print('available text')
"""
        proc=subprocess.run([sys.executable,'-B','-c',probe,str(ROOT)],text=True,capture_output=True); self.assertEqual(proc.returncode,0,proc.stderr)

    def test_wire_validation_and_small_image(self):
        self.assertEqual(self.request(protocol=2)['error']['code'],'protocol_version_unsupported')
        self.assertEqual(self.request(operation='ocr')['error']['code'],'operation_unsupported')
        self.assertEqual(self.parse('small.png')['warnings'][0]['code'],'invalid_or_small_image')
        self.assertIn('收入😀',self.parse('example.html')['document']['canonical_text'])
        self.assertIn('"income": 100',self.parse('example.json')['document']['canonical_text'])

    def test_no_django_import_or_business_db_access(self):
        probe = '''import importlib.abc,sys,json
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'django','personal_knowledge_base','sqlite3'}: raise AssertionError('forbidden import '+fullname)
sys.meta_path.insert(0,Block())
sys.path.insert(0,sys.argv[1])
from parser import parser_capabilities,parse_document
assert parser_capabilities()['format_status']['txt']
assert parse_document('sample.txt',b'hello').text_blocks[0].text=='hello'
assert not any(n.startswith('django') for n in sys.modules)
print('isolated')
'''
        proc=subprocess.run([sys.executable,'-B','-c',probe,str(ROOT)],text=True,capture_output=True); self.assertEqual(proc.returncode,0,proc.stderr); self.assertEqual(proc.stdout.strip(),'isolated')

if __name__=='__main__': unittest.main()
