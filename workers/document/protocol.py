"""Protocol v1 adapter. No business persistence, chunking or model calls."""
import hashlib
import io
import re
from pathlib import Path
from zipfile import ZipFile

from parser import PARSER_VERSION, SUPPORTED_FORMATS, parse_document
from parser.types import TextBlock
from parser.legacy_office import convert_legacy_office, LegacyOfficeParseError

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_PAGES = 1000
MAX_IMAGES = 2000
PROVENANCE_KEYS = {'bbox','page_number','paragraph_index','inline_position','table_index','table_cell','slide_number','shape_index','shape_path','shape_name','sheet_name','row_start','row_end','column_start','column_end','cell_provenance','merged_ranges','formula_source'}
MIME_EXTENSIONS = {'image/png':'png','image/jpeg':'jpg','image/gif':'gif','image/bmp':'bmp','image/tiff':'tiff','image/webp':'webp'}


class ProtocolError(ValueError):
    def __init__(self, code, message):
        self.code=code
        super().__init__(message)


def positive_limit(raw, key, ceiling):
    value=raw.get(key,ceiling)
    if isinstance(value,bool) or not isinstance(value,int) or value < 1 or value > ceiling:
        raise ProtocolError('request_invalid',f'{key} must be a positive integer within worker limits')
    return value


def validate_request(request):
    if not isinstance(request,dict) or request.get('protocol') != 1 or isinstance(request.get('protocol'),bool):
        raise ProtocolError('protocol_version_unsupported','Parser protocol 1 is required')
    if not isinstance(request.get('id'),str) or not request['id'] or len(request['id']) > 128:
        raise ProtocolError('request_invalid','A bounded nonempty request id is required')
    if request.get('operation') not in {'parse','capabilities'}:
        raise ProtocolError('operation_unsupported','Only parse and capabilities are supported')


def preflight(data,suffix,limits):
    if suffix == 'pdf':
        import pymupdf as fitz
        with fitz.open(stream=data,filetype='pdf') as pdf:
            if pdf.is_encrypted: raise ProtocolError('pdf_encrypted','Encrypted PDF is unsupported')
            if pdf.page_count > limits['max_pages']: raise ProtocolError('page_limit_exceeded','PDF exceeds the page limit')
    if suffix in {'docx','pptx','xlsx'}:
        with ZipFile(io.BytesIO(data)) as archive:
            infos=archive.infolist()
            if len(infos)>100000 or sum(i.file_size for i in infos)>MAX_ARTIFACT_BYTES:
                raise ProtocolError('archive_limit_exceeded','Office archive exceeds expansion limits')
            if suffix=='pptx' and sum(bool(re.fullmatch(r'ppt/slides/slide\d+\.xml',i.filename)) for i in infos)>limits['max_pages']:
                raise ProtocolError('page_limit_exceeded','Presentation exceeds the slide limit')


def provenance(block,suffix):
    result={key:value for key,value in block.metadata.items() if key in PROVENANCE_KEYS}
    if block.page_index is not None: result['page_index']=block.page_index
    if suffix=='pdf': result['unit']='pdf_point'
    elif suffix=='docx' or suffix=='doc': result['unit']='body_element'
    elif suffix=='pptx' or suffix=='ppt': result['unit']='slide'
    elif suffix=='xlsx' or suffix=='xls': result['unit']='sheet_row'
    else: result['unit']='document'
    if isinstance(block,TextBlock):
        if block.source_start is not None: result['source_start']=block.source_start
        if block.source_end is not None: result['source_end']=block.source_end
        if suffix=='pdf' and block.source_start is not None: result['source_offset_unit']='unicode_code_point'
    else:
        result.update(source_type=block.source_type,source_ref=block.source_ref)
    return result


def parse_request(request):
    raw_limits=request.get('limits',{})
    if not isinstance(raw_limits,dict): raise ProtocolError('request_invalid','limits must be an object')
    defaults={'max_input_bytes':MAX_INPUT_BYTES,'max_artifact_bytes':MAX_ARTIFACT_BYTES,'max_pages':MAX_PAGES,'max_images':MAX_IMAGES}
    if set(raw_limits)-set(defaults): raise ProtocolError('request_invalid','Unknown parser limit')
    limits={key:positive_limit(raw_limits,key,value) for key,value in defaults.items()}
    source=request.get('input')
    if not isinstance(source,dict) or not isinstance(source.get('path'),str) or not isinstance(source.get('name'),str): raise ProtocolError('request_invalid','parse requires input path and name')
    name=source['name']
    if not name or Path(name).name != name or '\\' in name or len(name)>255: raise ProtocolError('request_invalid','Input name must be a filename')
    suffix=Path(name).suffix.lower().lstrip('.')
    if suffix not in SUPPORTED_FORMATS: raise ProtocolError('unsupported_file_type','Input format is unsupported')
    input_path=Path(source['path'])
    if not input_path.is_absolute() or input_path.is_symlink() or not input_path.is_file(): raise ProtocolError('input_invalid','Input must be an absolute regular file')
    size=input_path.stat().st_size
    if size>limits['max_input_bytes']: raise ProtocolError('input_limit_exceeded','Input exceeds the byte limit')
    if type(source.get('size_bytes')) is not int or source['size_bytes']!=size: raise ProtocolError('input_size_mismatch','Input size does not match request')
    with input_path.open("rb") as source_file:
        data=source_file.read(limits["max_input_bytes"]+1)
    if len(data)>limits["max_input_bytes"]: raise ProtocolError("input_limit_exceeded","Input exceeds the byte limit")
    if len(data)!=size: raise ProtocolError('input_size_mismatch','Input size changed during read')
    digest=hashlib.sha256(data).hexdigest()
    if source.get('sha256')!=digest: raise ProtocolError('input_hash_mismatch','Input hash does not match request')
    artifact_raw=request.get('artifact_dir')
    if not isinstance(artifact_raw,str): raise ProtocolError('request_invalid','parse requires an artifact directory')
    artifact=Path(artifact_raw)
    if not artifact.is_absolute() or artifact.is_symlink() or not artifact.is_dir(): raise ProtocolError('artifact_directory_invalid','Artifact directory must be an existing absolute directory')
    if any(artifact.iterdir()): raise ProtocolError('artifact_directory_invalid','Use a new empty job artifact directory')
    options=request.get('options',{})
    if not isinstance(options,dict) or set(options)-{'engine'}: raise ProtocolError('request_invalid','Only the engine parser option is supported')
    engine=options.get('engine','builtin')
    if engine not in {'','builtin','plain'}: raise ProtocolError('request_invalid','Parser engine is unsupported')
    if suffix in {'doc','ppt'}:
        converted_name,converted_data=convert_legacy_office(name,data,scratch_dir=str(artifact))
        try:
            preflight(converted_data,Path(converted_name).suffix.lstrip('.'),limits)
            parsed=parse_document(converted_name,converted_data,engine)
        except ProtocolError:
            raise
        except Exception as exc:
            raise LegacyOfficeParseError('legacy_office_converted_output_invalid','legacy Office conversion output could not be parsed') from exc
    else:
        preflight(data,suffix,limits)
        parsed=parse_document(name,data,engine)
    if len(parsed.images)>limits['max_images']: raise ProtocolError('image_limit_exceeded','Document exceeds the image limit')
    artifact_bytes=sum(len(image.data) for image in parsed.images)
    if artifact_bytes>limits['max_artifact_bytes']: raise ProtocolError('artifact_limit_exceeded','Images exceed the artifact byte limit')
    blocks=[]; texts=[]; offset=0
    written=[]
    try:
        for b in parsed.ordered_blocks:
            meta={key:value for key,value in b.metadata.items() if key not in PROVENANCE_KEYS}
            common={'id':f'b{b.block_index}','block_index':b.block_index,'provenance':provenance(b,suffix),'metadata':meta}
            if isinstance(b,TextBlock):
                if not b.text: continue
                if texts: offset+=2
                start=offset; offset+=len(b.text); texts.append(b.text)
                blocks.append({**common,'kind':'text','block_type':b.block_type,'text':b.text,'canonical_range':{'start':start,'end':offset}})
            else:
                ext=MIME_EXTENSIONS.get(b.mime_type)
                if not ext: raise ProtocolError('image_mime_unsupported','Image output MIME is unsupported')
                relative=f'image-{b.block_index}.{ext}'; path=artifact/relative
                with path.open('xb') as output: output.write(b.data)
                written.append(path)
                blocks.append({**common,'kind':'image','artifact_path':relative,'sha256':hashlib.sha256(b.data).hexdigest(),'original_mime_type':b.original_mime_type or b.mime_type,'mime_type':b.mime_type,'width':b.width,'height':b.height})
    except Exception:
        for path in written: path.unlink(missing_ok=True)
        raise
    canonical='\n\n'.join(texts)
    warnings=[]
    for w in parsed.warnings:
        item={'code':w.code,'message':w.message}
        if w.block_index is not None: item['block_index']=w.block_index
        warnings.append(item)
    warning_sources=[{'warning_index':index,'source_ref':warning.source_ref} for index,warning in enumerate(parsed.warnings) if warning.source_ref]
    return {'document':{'name':name,'input_sha256':digest,'parser_version':PARSER_VERSION,'canonicalization_version':'blocks-double-newline-v1','offset_unit':'unicode_code_point','canonical_text':canonical,'canonical_sha256':hashlib.sha256(canonical.encode()).hexdigest()},'blocks':blocks,'warnings':warnings,'diagnostics':{'engine':engine or 'builtin','artifact_bytes':artifact_bytes,'image_count':len(parsed.images),'limits':limits,'ocr_performed':False,'warning_sources':warning_sources}}
