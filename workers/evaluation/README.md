# Independent evaluation worker

This helper runs the installed Ragas 0.4.3 **collections** API: `Faithfulness`,
`AnswerRelevancy(strictness=3)` and `ContextPrecisionWithReference`. It does not
import Django, open SQLite/database files, create subprocesses or connect to
model/network services. Python audit hooks enforce these boundaries. Core owns
all retrieval, model credentials, paid requests, usage audit, jobs and business
writes. The helper receives evaluation text and returns actual finite scores.

`requirements.txt` pins the versions whose installed APIs were inspected and
executed. The actual tested interpreter is
`/home/liuxuedeng/anaconda3/bin/python`; this environment also contains Django,
but the worker explicitly blocks its import. A fresh Linux dependency installation remains unverified. The official Windows
Python 3.13.16 embeddable bundle has been verified independently: Ragas 0.4.3
collections load, Django is absent, poisoned Python home/path variables remain
isolated, and all seven evaluation boundary tests pass. Relocation to a directory
with spaces also loads actual Ragas capabilities. The compiled Windows bridge
has additionally scored two mathematical/Chinese rows with 16 controlled HTTP
model RPCs and passed cancellation, timeout and exited-worker/descendant cleanup;
this is fixture scoring, not real vendor acceptance. The standard-library
boundary tests also run with `/usr/bin/python3` and need no Ragas installation.
No provider credentials are required for the controlled local protocol tests.

## Protocol and lifecycle

UTF-8 JSON lines, protocol **numeric 1**, request UUID `id`, `operation` equal to
`capabilities` or `evaluate`. Evaluate rows have `example_id`, `question`,
`answer`, `reference` and nonempty `contexts`. The process handles one request.

Python emits `model_call` with UUID `call_id`, row `example_id`, sequential
`call_index`, and `operation:chat` (`prompt`,`schema`) or `operation:embed`
(`texts`). Core responds with matching `model_result` and `result.content` or
`result.vectors`. No credential, configuration object or business database path
crosses this protocol. A malformed paid response is never automatically retried.
Python emits validated per-row progress and the final real metric rows; failures
have a fixed code and no raw prompt, exception, URL or private path.

Core bridge limits input/lines to 2 MiB and total captured output to 32 MiB. It
uses the core owned supervisor: a live POSIX group owner or Windows unnamed Job
Object retains process identity through descendant cleanup. No process discovery
by port/name or post-exit PID kill occurs. Cancellation, timeout, crash and
inherited stdout/stderr pipes are covered on Linux and the actual compiled Windows
bridge. All owned processes were dead at settlement and an unrelated child remained
alive. Core close awaits provider audit/finally work and worker exit. The bridge sets
`PYTHONUTF8=1` explicitly, in addition to `PYTHONIOENCODING=utf-8`; the Windows
embeddable runtime ignores the latter under its isolated `_pth` configuration.
A real child-environment assertion was observed red before this correction and
green afterward. The bridge now consumes the shared `pythonWorkerEnv`: trusted
Python-directory plus OS-tool PATH, permitted OS/temp/locale/cache variables,
with no developer PATH, provider keys, Python home/path or Django overrides.
The Windows PATH includes System32 for actual native dependency loading. Windows bundled capability/boundary evidence is in
[`verification`](../../docs/evidence/20261010-windows-python-verification.json),
[`boundaries`](../../docs/evidence/20261010-windows-python-boundaries.json) and
[`relocation`](../../docs/evidence/20261010-windows-python-relocation.json).
Actual Windows scoring/lifecycle evidence is in
[`compiled bridges`](../../docs/evidence/20261010-windows-ts-python-bridge.json)
and [`seven boundaries`](../../docs/evidence/20261010-windows-ts-python-bridge-boundaries.json).
The worker initializes its one trusted event loop before reading any request,
importing Ragas or installing the audit hook. Windows needs an internal TCP
socketpair for that bootstrap. Scoring reuses the owned loop and closes it;
the audit hook still blocks every subsequent socket connection, including localhost.

## Verification

From the repository root:

```sh
TMPDIR=/dev/shm /usr/bin/python3 -m unittest discover -s workers/evaluation -p 'test_*.py' -v
```

From `packages/core`:

```sh
TMPDIR=/dev/shm node --import tsx --test test/evaluation.test.ts
npm run typecheck
npm run build
```

Seven actual Python boundary tests pass: Django import, SQLite connect before file
creation, database-file open, direct socket connection, subprocess creation and
oversized protocol input, and Windows-style TCP self-pipe bootstrap followed by
a rejected ordinary localhost connection. The added bootstrap regression first
failed with the actual audit PermissionError; after correction Linux boundaries
passed 7/7 in 1.073s and installed Ragas five-row RPC passed in 57.334s.
Windows independent seven boundaries passed in 1.516s and the actual compiled
bridge suite passed 25/25, including two real Ragas rows (16 local HTTP RPCs).
TypeScript covers an installed Ragas five-row RPC run,
actual HTTP answer/judge/embedding adapters, usage, immutable publication, scoped
reports, cancellation/manual recovery, independent production chunk indexes,
pinned public cache hashes/tree/blob identities and worker protocol/lifecycle
faults. The protocol fault fixtures deliberately do **not** count as installed
Ragas or real vendor acceptance.

Controlled five-question tenant and public chains each issued 45 actual local
HTTP requests and recorded 45 usage rows, then computed five real Ragas rows.
The public fixture used two corpus documents, including a distractor, and kept
business documents/chunks untouched. The cancellation/resume chain issued 46
requests: the unknown request remained audited and known results were reused.
Final combined TypeScript evaluation verification passed **16/16** in
**218.926s**. The queued public preparation/full-chain checks passed **2/2** in
**48.680s**; historical Python selection, legacy strategy normalization and
public default size regressions passed **3/3** in **46.458s**, after three
observed failures. The explicit UTF-8 environment plus owned-descendant protocol
regression passed **1/1** in **5.968s**, after an observed worker failure.
After shared environment integration, the actual installed Ragas five-row RPC
and owned-process protocol/PATH regressions passed **2/2** in **66.037s**; the
PATH assertion first failed against the former developer PATH. Final Python
boundaries passed **6/6** in **1.091s**. Core typecheck/build both
passed (exit 0). Frontend evaluation/API behavior passed **15/15**; full frontend
unit verification passed **162/162** in **3.610s** and Vite build passed in
**45.58s** (existing large-chunk warning). Frontend tests use injected HTTP
boundaries and actual Vue compilation/rendering; they are not a real configured
page or vendor acceptance run.

Actual fixed-revision Hugging Face tree metadata was read: 1000 JSON files; Git
SHA-1 recomputation matched `a6c1c6a4f074f907fefcd57dd5990bda5724c5d4`. This is
metadata verification, **not** full corpus download or a 180/3045-question run.
No real vendor credentials/payment were used. Real vendor five-question
acceptance and full benchmark runs require configured models and deliberate
paid execution; they are not reported as passed.

The environment's ext4 journal blocked temporary SQLite tests. `TMPDIR=/dev/shm`
uses independent tmpfs fixtures only; production storage is unchanged. These
results do not establish original-disk durability or disk performance.

Project source retains the repository MIT license in `LICENSE`. Ragas is an
external Apache-2.0 dependency; its license remains with its installed package.
Public benchmark artifacts retain their pinned source/license metadata
(CC-BY-NC-4.0); they are not vendored by this change.
