import io
from datetime import date, datetime, time

from .types import ParsedDocument, TextBlock


class SpreadsheetParseError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


def _column_name(column_number: int) -> str:
    value = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _cell_range(row_start: int, row_end: int, column_start: int, column_end: int) -> str:
    start = f"{_column_name(column_start)}{row_start}"
    end = f"{_column_name(column_end)}{row_end}"
    return start if start == end else f"{start}:{end}"


def _append_sheet_rows(document: ParsedDocument, sheet_name: str, rows, merged_ranges: list[str]):
    header_cells = None
    block_index = len(document.text_blocks)
    for row_number, values, cell_provenance, formula_source in rows:
        nonempty_columns = [index for index, value in enumerate(values) if value.strip()]
        if not nonempty_columns:
            continue
        if header_cells is None:
            header_cells = values[:]
        first_column = nonempty_columns[0]
        last_column = nonempty_columns[-1]
        metadata = {
            "sheet_name": sheet_name,
            "headers": header_cells,
            "row_start": row_number,
            "row_end": row_number,
            "column_start": first_column + 1,
            "column_end": last_column + 1,
            "formula_source": formula_source,
            "cell_provenance": cell_provenance,
            "merged_ranges": merged_ranges,
        }
        document.text_blocks.append(
            TextBlock(
                " | ".join(values),
                block_index,
                metadata=metadata,
                block_type="record",
                source_start=row_number,
                source_end=row_number,
            )
        )
        block_index += 1


def parse_xlsx(data: bytes) -> ParsedDocument:
    formula_workbook = None
    cached_workbook = None
    try:
        from openpyxl import load_workbook

        formula_workbook = load_workbook(io.BytesIO(data), read_only=False, data_only=False)
        cached_workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        if formula_workbook is not None:
            formula_workbook.close()
        raise SpreadsheetParseError("xlsx_parse_failed", "unable to read XLSX workbook") from exc

    document = ParsedDocument()
    try:
        for formula_sheet in formula_workbook.worksheets:
            cached_sheet = cached_workbook[formula_sheet.title]
            merged_ranges = sorted(str(cell_range) for cell_range in formula_sheet.merged_cells.ranges)

            def rows():
                paired_rows = zip(formula_sheet.iter_rows(), cached_sheet.iter_rows())
                for row_number, (formula_cells, cached_cells) in enumerate(paired_rows, start=1):
                    values = []
                    provenance = []
                    has_cached_formula = False
                    has_formula_fallback = False
                    for column_number, (formula_cell, cached_cell) in enumerate(
                        zip(formula_cells, cached_cells),
                        start=1,
                    ):
                        formula = formula_cell.value if formula_cell.data_type == "f" else None
                        if formula is not None and cached_cell.value is not None:
                            display_value = cached_cell.value
                            source = "cached"
                            has_cached_formula = True
                        elif formula is not None:
                            display_value = formula
                            source = "formula"
                            has_formula_fallback = True
                        else:
                            display_value = formula_cell.value
                            source = "literal"

                        text = _cell_text(display_value)
                        values.append(text)
                        cell_metadata = {
                            "coordinate": formula_cell.coordinate,
                            "column": column_number,
                            "value": text,
                            "source": source,
                        }
                        if formula is not None:
                            cell_metadata["formula"] = _cell_text(formula)
                        provenance.append(cell_metadata)

                    formula_source = "formula" if has_formula_fallback else "cached"
                    if not has_formula_fallback and not has_cached_formula:
                        formula_source = "cached"
                    yield row_number, values, provenance, formula_source

            _append_sheet_rows(document, formula_sheet.title, rows(), merged_ranges)
    finally:
        formula_workbook.close()
        cached_workbook.close()
    return document


def parse_xls(data: bytes) -> ParsedDocument:
    try:
        import xlrd
    except ImportError as exc:
        raise SpreadsheetParseError("xls_parser_unavailable", "xlrd is required to parse XLS files") from exc

    try:
        workbook = xlrd.open_workbook(file_contents=data, on_demand=True, formatting_info=True)
    except Exception as exc:
        raise SpreadsheetParseError("xls_parse_failed", "unable to read XLS workbook") from exc

    document = ParsedDocument()
    try:
        for sheet in workbook.sheets():
            merged_ranges = sorted(
                _cell_range(row_start + 1, row_end, column_start + 1, column_end)
                for row_start, row_end, column_start, column_end in sheet.merged_cells
            )

            def rows():
                for row_number in range(1, sheet.nrows + 1):
                    values = [_cell_text(value) for value in sheet.row_values(row_number - 1)]
                    provenance = [
                        {
                            "coordinate": f"{_column_name(column_number)}{row_number}",
                            "column": column_number,
                            "value": value,
                            "source": "cached",
                        }
                        for column_number, value in enumerate(values, start=1)
                    ]
                    yield row_number, values, provenance, "cached"

            _append_sheet_rows(document, sheet.name, rows(), merged_ranges)
    finally:
        workbook.release_resources()
    return document
