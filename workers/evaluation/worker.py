#!/usr/bin/env python3
# Copyright (c) 2026 LiuXD1011. MIT; Ragas dependency is Apache-2.0.
"""Ragas-only JSON-lines helper. Model operations go to the owning core by RPC."""
import asyncio
import contextlib
import importlib.abc
import json
import math
import os
import sys
import uuid

os.environ['RAGAS_DO_NOT_TRACK'] = 'true'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['DO_NOT_TRACK'] = '1'

class NoDjango(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'django' or fullname.startswith('django.'):
            raise ImportError('Django is not available in this worker')
sys.meta_path.insert(0, NoDjango())

# Trusted bootstrap precedes any input, dependency import or installed audit hook.
# Windows ProactorEventLoop needs a TCP socketpair for its internal self-pipe.
# Reuse this one owned loop; never whitelist loopback destinations for scoring.
_CORE_LOOP = asyncio.new_event_loop()

def run_async(coroutine):
    if hasattr(asyncio, 'Runner'):
        with asyncio.Runner(loop_factory=lambda: _CORE_LOOP) as runner:
            return runner.run(coroutine)
    # Boundary probes also run on the system Python 3.8; the Ragas payload uses 3.13.
    try:
        asyncio.set_event_loop(_CORE_LOOP)
        return _CORE_LOOP.run_until_complete(coroutine)
    finally:
        _CORE_LOOP.run_until_complete(_CORE_LOOP.shutdown_asyncgens())
        asyncio.set_event_loop(None)
        _CORE_LOOP.close()

def restrictions(event, args):
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        name = os.fsdecode(args[0]).lower()
        if name.endswith(('.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.sqlite-wal', '.sqlite-shm', '.sqlite3-wal', '.sqlite3-shm')):
            raise PermissionError('Database files are not available in this worker')
    if event in ('sqlite3.connect', 'socket.connect', 'socket.connect_ex', 'subprocess.Popen'):
        raise PermissionError('This worker only uses the core RPC transport')
sys.addaudithook(restrictions)

MAX_LINE = 2 * 1024 * 1024

def read():
    line = sys.stdin.buffer.readline(MAX_LINE + 1)
    if not line or len(line) > MAX_LINE:
        raise ValueError('Invalid protocol input')
    result = json.loads(line)
    if not isinstance(result, dict):
        raise ValueError('Invalid protocol input')
    return result

def send(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > MAX_LINE:
        raise ValueError('Protocol output is too large')
    sys.stdout.write(encoded + '\n')
    sys.stdout.flush()

class Transport:
    def __init__(self, request_id):
        self.request_id = request_id
        self.calls = 0
        self.example_id = ''
        self.call_index = 0
    def rpc(self, operation, **parameters):
        self.calls += 1
        self.call_index += 1
        if self.calls > 4096:
            raise ValueError('Model call limit exceeded')
        call_id = str(uuid.uuid4())
        send(dict(protocol=1, id=self.request_id, type='model_call', call_id=call_id, example_id=self.example_id, call_index=self.call_index, operation=operation, **parameters))
        result = read()
        if result.get('protocol') != 1 or result.get('id') != self.request_id or result.get('type') != 'model_result' or result.get('call_id') != call_id or result.get('error'):
            raise ValueError('Model RPC failed')
        if not isinstance(result.get('result'), dict):
            raise ValueError('Invalid model RPC response')
        return result['result']

def components(transport):
    from ragas.llms.base import InstructorBaseRagasLLM
    from ragas.embeddings.base import BaseRagasEmbedding
    class CoreLLM(InstructorBaseRagasLLM):
        def generate(self, prompt, response_model):
            result = transport.rpc('chat', prompt=prompt, schema=response_model.model_json_schema())
            return response_model.model_validate_json(result['content'])
        async def agenerate(self, prompt, response_model):
            return self.generate(prompt, response_model)
    class CoreEmbedding(BaseRagasEmbedding):
        def embed_text(self, text, **kwargs):
            return self.embed_texts([text])[0]
        async def aembed_text(self, text, **kwargs):
            return self.embed_text(text)
        def embed_texts(self, texts, **kwargs):
            vectors = transport.rpc('embed', texts=texts)['vectors']
            if len(vectors) != len(texts) or not vectors or any(not v or any(not isinstance(n, (int, float)) or isinstance(n, bool) or not math.isfinite(n) for n in v) for v in vectors) or any(len(v) != len(vectors[0]) for v in vectors):
                raise ValueError('Invalid embedding vectors')
            return vectors
        async def aembed_texts(self, texts, **kwargs):
            return self.embed_texts(texts)
    return CoreLLM(), CoreEmbedding()

async def score(request):
    from ragas.metrics.collections import Faithfulness, AnswerRelevancy, ContextPrecisionWithReference
    rows = request.get('rows')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError('Invalid rows')
    identifiers = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('example_id'), str) or not row['example_id'] or row['example_id'] in identifiers:
            raise ValueError('Invalid row identity')
        identifiers.add(row['example_id'])
        if any(not isinstance(row.get(key), str) or not row[key].strip() or len(row[key]) > 16384 for key in ('question', 'answer', 'reference')):
            raise ValueError('Invalid row content')
        if not isinstance(row.get('contexts'), list) or not 1 <= len(row['contexts']) <= 20 or any(not isinstance(value, str) or not value.strip() or len(value) > 16384 for value in row['contexts']):
            raise ValueError('Invalid contexts')
    transport = Transport(request['id'])
    llm, embeddings = components(transport)
    metrics = {'faithfulness': Faithfulness(llm=llm), 'answer_relevancy': AnswerRelevancy(llm=llm, embeddings=embeddings, strictness=3), 'context_precision': ContextPrecisionWithReference(llm=llm)}
    output = []
    for row in rows:
        transport.example_id = row['example_id']
        transport.call_index = 0
        values = {'example_id': row['example_id']}
        for name, metric in metrics.items():
            if name == 'answer_relevancy':
                result = await metric.ascore(user_input=row['question'], response=row['answer'])
            elif name == 'context_precision':
                result = await metric.ascore(user_input=row['question'], reference=row['reference'], retrieved_contexts=row['contexts'])
            else:
                result = await metric.ascore(user_input=row['question'], response=row['answer'], retrieved_contexts=row['contexts'])
            value = float(result.value)
            if not math.isfinite(value) or not -1 <= value <= 1:
                raise ValueError('Invalid metric result')
            values[name] = value
        output.append(values)
        send(dict(protocol=1, id=request['id'], type='progress', example_id=row['example_id'], completed=len(output), total=len(rows)))
    return {'rows': output, 'ragas_version': '0.4.3', 'metrics': list(metrics)}

def main():
    request_id = ''
    try:
        request = read()
        request_id = request.get('id', '')
        if request.get('protocol') != 1 or not isinstance(request_id, str) or not request_id or len(request_id) > 128 or request.get('operation') not in ('capabilities', 'evaluate'):
            raise ValueError('Invalid request')
        with contextlib.redirect_stdout(sys.stderr):
            import ragas
        if ragas.__version__ != '0.4.3':
            raise ValueError('Unsupported Ragas version')
        if request['operation'] == 'capabilities':
            # Load the real metric API before claiming capability.
            with contextlib.redirect_stdout(sys.stderr):
                from ragas.metrics.collections import Faithfulness, AnswerRelevancy, ContextPrecisionWithReference
            result = {'ragas_version': ragas.__version__, 'django_imported': any(key == 'django' or key.startswith('django.') for key in sys.modules), 'metrics': ['faithfulness', 'answer_relevancy', 'context_precision'], 'model_transport': 'core_rpc'}
        else:
            result = run_async(score(request))
        send(dict(protocol=1, id=request_id, type='result', operation=request['operation'], result=result))
    except BaseException:
        # Dependency/metric errors may contain raw prompts, URLs and private paths.
        send(dict(protocol=1, id=request_id, type='error', code='ragas_scoring_failed'))
    finally:
        if not _CORE_LOOP.is_closed():
            _CORE_LOOP.close()

if __name__ == '__main__':
    main()
