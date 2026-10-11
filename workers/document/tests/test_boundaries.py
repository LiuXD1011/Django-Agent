import importlib.abc
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from parser.images import normalize_for_vlm
from parser.remote_images import UnsafeRemoteImageError, download_remote_image, validate_remote_url


class BoundaryTests(unittest.TestCase):
    def test_public_url_scheme_credentials_and_private_dns(self):
        for url in ('file:///tmp/image.png','http://user:password@example.com/image.png','http://127.0.0.1/image.png','http://[::1]/image.png'):
            with self.assertRaises(UnsafeRemoteImageError): validate_remote_url(url)
        with patch('parser.remote_images.socket.getaddrinfo',return_value=[(2,1,6,'',('10.0.0.1',80))]):
            with self.assertRaises(UnsafeRemoteImageError): validate_remote_url('https://public.example/img')

    def test_redirect_mime_and_byte_limits_with_controlled_download_responses(self):
        # These doubles test network restrictions only; they are not format/converter proof.
        class Response:
            is_redirect=False; is_permanent_redirect=False
            headers={'Content-Type':'image/png'}
            def raise_for_status(self): pass
            def iter_content(self,size): yield b'x'*(10*1024*1024+1)
            closed=False
            def close(self): self.closed=True
        class Session:
            def get(self,*args,**kwargs): self.kwargs=kwargs; self.response=Response(); return self.response
        client=Session()
        with patch('parser.remote_images.validate_remote_url',side_effect=lambda url:url):
            with self.assertRaises(UnsafeRemoteImageError): download_remote_image('https://public.example/image.png',client)
            self.assertEqual(client.kwargs['timeout'],10); self.assertFalse(client.kwargs['allow_redirects']); self.assertTrue(client.response.closed)
            with patch.object(Response,'headers',{'Content-Type':'text/html'}):
                with self.assertRaises(UnsafeRemoteImageError): download_remote_image('https://public.example/image.png',client)
            with patch.object(Response,'is_redirect',True),patch.object(Response,'headers',{'Location':'https://public.example/next.png'}):
                with self.assertRaises(UnsafeRemoteImageError): download_remote_image('https://public.example/image.png',client)

    def test_legacy_converter_uses_job_scratch_and_owned_profile(self):
        from parser.legacy_office import LegacyOfficeParseError, convert_legacy_office
        import inspect
        self.assertIn("scratch_dir",inspect.signature(convert_legacy_office).parameters)
        def timeout(command,**kwargs):
            source=Path(command[-1]); self.assertEqual(source.parent.parent,Path(job)); self.assertTrue(any(arg.startswith('-env:UserInstallation=') for arg in command))
            raise subprocess.TimeoutExpired(command,1)
        with tempfile.TemporaryDirectory() as job:
            with patch('parser.legacy_office._soffice_executable',return_value='/owned/soffice'),patch('parser.legacy_office.subprocess.run',side_effect=timeout):
                with self.assertRaises(LegacyOfficeParseError) as error:
                    convert_legacy_office('sample.doc',b'not-encrypted',scratch_dir=job)
                self.assertEqual(error.exception.code,'legacy_office_conversion_timeout'); self.assertEqual(list(Path(job).iterdir()),[])

    def test_normalized_svg_can_be_consumed_for_vlm(self):
        data,mime,width,height=normalize_for_vlm((ROOT/'tests/fixtures/image.svg').read_bytes(),'image/svg+xml')
        self.assertEqual(mime,'image/jpeg');self.assertEqual((width,height),(96,96));self.assertTrue(data.startswith(b'\xff\xd8'))

    def test_svg_external_resources_cannot_bypass_image_network_policy(self):
        from parser.images import InvalidImageError, rasterize_svg
        samples=[
            '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><image href="file:///tmp/business.sqlite3" width="96" height="96"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><image href="http://127.0.0.1/private.png" width="96" height="96"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><style>@import "http://127.0.0.1/style.css";</style></svg>',
        ]
        for source in samples:
            with self.assertRaises(InvalidImageError): rasterize_svg(source.encode())

    def test_real_image_first_frame_and_exif_normalization(self):
        from PIL import Image
        first=Image.new('RGB',(96,128),'red');second=Image.new('RGB',(96,128),'blue');output=io.BytesIO();first.save(output,format='GIF',save_all=True,append_images=[second],duration=10,loop=0)
        data,mime,width,height=normalize_for_vlm(output.getvalue(),'image/gif')
        with Image.open(io.BytesIO(data)) as im: self.assertGreater(im.getpixel((30,30))[0],200)
        output=io.BytesIO();exif=Image.Exif();exif[274]=6;first.save(output,format='JPEG',exif=exif)
        data,mime,width,height=normalize_for_vlm(output.getvalue(),'image/jpeg');self.assertEqual((width,height),(128,96))

    def test_all_formats_run_with_business_database_imports_and_access_forbidden(self):
        probe='''import importlib.abc,sys,tempfile,json,hashlib,os
from pathlib import Path
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'django','personal_knowledge_base','sqlite3'}: raise AssertionError('forbidden business import')
def audit(event,args):
 if event=='open' and isinstance(args[0],(str,bytes)) and str(args[0]).lower().endswith(('.db','.sqlite','.sqlite3')): raise AssertionError('forbidden database file')
sys.meta_path.insert(0,Block());sys.addaudithook(audit)
sys.path.insert(0,sys.argv[1])
from protocol import parse_request
from parser import parser_capabilities
assert parser_capabilities()['format_status']['txt']
root=Path(sys.argv[1])/'tests/fixtures'
for name in ['unicode.txt','unicode.md','records.csv','records.xlsx','records.xls','table.docx','slides.pptx','text.pdf','scanned.pdf','image.png','image.svg']:
 data=(root/name).read_bytes()
 with tempfile.TemporaryDirectory() as job:
  result=parse_request({'input':{'path':str(root/name),'name':name,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)},'artifact_dir':job})
  assert result['blocks']
assert not any(n.split('.')[0] in {'django','personal_knowledge_base','sqlite3'} for n in sys.modules)
print('11 formats isolated')
'''
        proc=subprocess.run([sys.executable,'-B','-c',probe,str(ROOT)],text=True,capture_output=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(proc.stdout.strip(),'11 formats isolated')

if __name__=='__main__': unittest.main()
