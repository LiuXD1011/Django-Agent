# Task 2 Report: Spreadsheet And Legacy Office Parsers

## Status

`DONE_WITH_CONCERNS`

Commit: `c8fe281a6c956582da9e69165325d441b4bc064a`

## Delivered

- Added `parse_xlsx(data)` and `parse_xls(data)` in `personal_knowledge_base/document_parsing/spreadsheet.py`.
  - Every non-empty spreadsheet row becomes a `TextBlock(block_type="record")` with sheet/header/row/column metadata and source row bounds.
  - XLSX formulas retain `formula_source="formula"`; other values are labelled `cached`.
- Added isolated legacy conversion through `convert_legacy_office(name, data, timeout=30)` in `personal_knowledge_base/document_parsing/legacy_office.py`.
  - `.doc` converts to `.docx`; `.ppt` converts to `.pptx` in an isolated temporary directory.
  - Calls `soffice`/LibreOffice with `--headless`, `--convert-to`, `--outdir`, `check=True`, `timeout`, and `capture_output=True`.
  - Stable `LegacyOfficeParseError.code` values cover unavailable converter, timeout, encrypted input, conversion failure, missing output, and unparsable output.
- Routed `.xls`, `.xlsx`, `.doc`, and `.ppt` through the new parsers and exported their interfaces.
- Extended `TextBlock` with `block_type`, `source_start`, and `source_end` while retaining positional compatibility.
- Corrected DOCX extraction to use public `python-docx` `Paragraph` and `Table` APIs, preventing duplicate XML text in converted documents.
- Added `openpyxl>=3.1.5` and `xlrd>=2.0.1` requirements, plus README documentation that LibreOffice/`soffice` is required at runtime for `.doc` and `.ppt`.
- Added XLS, DOC, and PPT fixtures. XLSX/DOCX/PPTX test documents are generated in memory; legacy conversion is mocked with generated output.

## TDD Evidence

Initial contract-test run:

```text
python manage.py test personal_knowledge_base.test_document_parsing -v 2
FAILED (9 errors)
```

The expected RED failures showed missing legacy converter routing/module and XLS/XLSX falling through to text parsing.

A subsequent DOC conversion test exposed duplicate text from `child.itertext()`. Replacing that internal XML traversal with the public `python-docx` wrappers made the isolated regression test pass.

## Final Verification

```text
python - <<'PY'
import xlrd
print(xlrd.__version__)
PY
# 2.0.2

python manage.py test personal_knowledge_base.test_document_parsing -v 2
Ran 17 tests in 0.473s
OK

python -m compileall -q personal_knowledge_base/document_parsing personal_knowledge_base/test_document_parsing.py
# PASS

git diff --check
# PASS

git diff --cached --check
# PASS before commit
```

## Commit Scope

The commit contains only Task 2 files:

- `README.md`
- `requirements.txt`
- `personal_knowledge_base/document_parsing/{__init__,legacy_office,registry,spreadsheet,types}.py`
- `personal_knowledge_base/test_document_parsing.py`
- `personal_knowledge_base/testdata/legacy/sample.{doc,ppt,xls}`

The pre-existing untracked `docs/superpowers/plans/2026-07-23-adaptive-parent-child-chunking.md` was preserved and excluded.

## Concern

The local environment intentionally has no LibreOffice/`soffice`, so real legacy conversion was not executed here. The conversion command and output paths are covered through subprocess/output mocks, and production behavior returns `legacy_office_converter_unavailable` deterministically until the documented runtime prerequisite is installed.

---

## Review Remediation Update (2026-07-23)

### Status

`BLOCKED`

The user stopped implementation after the current focused parser cycle. Edits were preserved and were not committed because the focused test module is not green.

Current HEAD: `c8fe281a6c956582da9e69165325d441b4bc064a`

### Implemented In The Preserved Worktree

- XLSX now combines formula and `data_only` workbook views, uses cached displayed values when present, falls back to formula text, and emits per-cell provenance.
- XLSX and XLS parsing code emits `merged_ranges`; XLSX merge coverage passes.
- DOCX emits heading/paragraph/table block types, heading levels, row/cell table metadata, and inline text/image/text ordering. Converted DOC inherits this behavior through the DOCX parser.
- PPTX emits one-based `slide_number`, text-box/table blocks, row/cell table metadata, and pictures in shape order. Converted PPT inherits this behavior through the PPTX parser.
- Contract tests were strengthened for formulas, merges, headings, tables, slide numbers, block order, pictures, and encryption classification.

### Focused Test Result

Command:

```text
python manage.py test personal_knowledge_base.test_document_parsing -v 2
```

Result:

```text
Ran 19 tests in 0.557s
FAILED (failures=3)
```

Passing: 16. Failing: 3.

Exact failures:

1. `test_encrypted_legacy_input_is_detected_before_converter_lookup`
   - Expected `legacy_office_encrypted`.
   - Received `legacy_office_converter_unavailable`.
   - The deterministic preflight implementation and declared dependency remain unimplemented.
2. `test_protected_success_without_output_is_classified_as_encrypted`
   - Expected `legacy_office_encrypted`.
   - Received `legacy_office_conversion_output_missing`.
   - Successful conversion with protected/password output and no file is not yet reclassified.
3. `test_xls_emits_merged_cell_ranges_and_cell_provenance`
   - Expected `merged_ranges == ["A3:B3"]`.
   - Received `[]` because the committed `sample.xls` fixture has no merged cells.
   - The parser implementation reads XLS merge metadata, but the fixture regeneration was interrupted.

### Environment Boundary

LibreOffice is unavailable and was not invoked. Legacy conversion execution remains mocked, and the existing unavailable-runtime test passes. No requirement needs to wait on LibreOffice, but encryption preflight and the XLS merge fixture still require local implementation work before Task 2 can be committed as complete.

---

## Review Remediation Completion (2026-07-23)

### Status

`COMPLETE`

Remediation commit: `c8cfb00f6f00be75af33adcfd78e30d9952794d3`

### Delivered

- Added the declared runtime dependency `msoffcrypto-tool>=5.4.2`.
- Preflighted legacy `.doc` and `.ppt` payloads with `msoffcrypto.OfficeFile(...).is_encrypted()` before converter lookup. Detector/import/parse failures are treated as non-encrypted so normal converter handling remains available.
- Retained `subprocess.CompletedProcess` and reclassified successful conversions that emit password/encryption output but create no converted file as `legacy_office_encrypted`.
- Regenerated `personal_knowledge_base/testdata/legacy/sample.xls` with `xlwt` as a real XLS workbook: `Revenue`, `Quarter`/`Amount`, `Q1`/`100`, and merged `A3:B3`.
- Preserved the pre-existing XLSX/DOCX/PPTX fidelity changes and reviewed them against the expanded parser contract suite.

### Exact Verification Evidence

```text
python manage.py test personal_knowledge_base.test_document_parsing -v 2
Ran 19 tests in 0.561s
OK

python detector-error boundary check
legacy_office_converter_unavailable

python -m compileall -q personal_knowledge_base/document_parsing personal_knowledge_base/test_document_parsing.py
# exit 0

git diff --check
# exit 0

git diff --cached --check
# exit 0

sha256sum personal_knowledge_base/testdata/legacy/sample.xls
3f8cde41d289b9af1debd9b1bcd8c63e93fd82d7d08eddeb2684d16bd9912ae2  personal_knowledge_base/testdata/legacy/sample.xls
```

The unrelated untracked plan `docs/superpowers/plans/2026-07-23-adaptive-parent-child-chunking.md` remains preserved and excluded from both remediation commits.
