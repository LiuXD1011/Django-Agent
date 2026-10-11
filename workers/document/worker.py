"""One request per isolated process. stdout is UTF-8 protocol v1 NDJSON only."""
import contextlib
import json
import sys

from parser import parser_capabilities
from parser.legacy_office import LegacyOfficeParseError
from parser.spreadsheet import SpreadsheetParseError
from protocol import ProtocolError, parse_request, validate_request

MAX_REQUEST_BYTES = 64 * 1024


def main():
    request={}; response={'protocol':1,'id':''}
    try:
        raw=sys.stdin.buffer.readline(MAX_REQUEST_BYTES+1)
        if len(raw)>MAX_REQUEST_BYTES: raise ProtocolError('request_limit_exceeded','Parser request exceeds the byte limit')
        request=json.loads(raw)
        if isinstance(request,dict) and isinstance(request.get('id'),str): response['id']=request['id'][:128]
        validate_request(request)
        with contextlib.redirect_stdout(sys.stderr):
            result=parser_capabilities() if request['operation']=='capabilities' else parse_request(request)
        response.update(type='result',operation=request['operation'],result=result)
    except (ProtocolError,LegacyOfficeParseError,SpreadsheetParseError) as exc:
        response.update(type='error',error={'code':exc.code,'message':str(exc),'retryable':False})
    except Exception:
        # Native parser errors may include paths, URLs or XML content; keep them private.
        response.update(type='error',error={'code':'parse_failed','message':'The document could not be parsed','retryable':False})
    sys.stdout.write(json.dumps(response,ensure_ascii=False,allow_nan=False)+'\n'); sys.stdout.flush()


if __name__=='__main__':
    if hasattr(sys.stdin,'reconfigure'): sys.stdin.reconfigure(encoding='utf-8')
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    main()
