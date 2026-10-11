"""Independent parsing extracted from personal_knowledge_base; MIT project license."""
import importlib

from .legacy_office import _soffice_executable
from .formats import IMAGE_TYPES, SUPPORTED_FORMATS

PARSER_VERSION = 'marlin-parser-v1'
def parse_document(name, data, engine="builtin"):
    # Optional native/image modules must not prevent capability or plain-text use.
    from .registry import parse_document as parse
    return parse(name, data, engine)



def parser_capabilities() -> dict:
    dependencies = {'PyMuPDF':'pymupdf','Pillow':'PIL.Image','python-docx':'docx','python-pptx':'pptx','CairoSVG':'cairosvg','openpyxl':'openpyxl','xlrd':'xlrd','msoffcrypto-tool':'msoffcrypto','requests':'requests'}
    status = {}
    for name,module in dependencies.items():
        try:
            importlib.import_module(module)
            status[name]=True
        except (ImportError, OSError):
            status[name]=False
    status['LibreOffice'] = _soffice_executable() is not None
    formats = {fmt:True for fmt in sorted(SUPPORTED_FORMATS)}
    for fmt in IMAGE_TYPES: formats[fmt] = status['Pillow'] and (fmt != 'svg' or status['CairoSVG'])
    formats['pdf'] = status['PyMuPDF'] and status['Pillow']
    formats['docx'] = status['python-docx'] and status['Pillow']
    formats['pptx'] = status['python-pptx'] and status['Pillow']
    formats['xlsx'] = status['openpyxl']; formats['xls'] = status['xlrd']
    formats['doc'] = formats['docx'] and status['LibreOffice'] and status['msoffcrypto-tool']
    formats['ppt'] = formats['pptx'] and status['LibreOffice'] and status['msoffcrypto-tool']
    return {'name':'builtin','parser_version':PARSER_VERSION,'available':True,'formats':sorted(SUPPORTED_FORMATS),'format_status':formats,'dependency_status':status,'capabilities':['text_extraction','embedded_images','tables','records','scanned_pdf_rendering','remote_image_localization'],'ocr_available':False,'caption_available':False,'remote_images':{'schemes':['http','https'],'public_addresses_only':True,'max_redirects':3,'timeout_seconds':10,'max_bytes':10485760}}
