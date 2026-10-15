"""Spreadsheet / tabular data conversions (pandas + openpyxl)."""
import csv
import html as htmllib
import io
import json
import re
from pathlib import Path

import pandas as pd

from .conv_doc import read_text

DATA_IN = {"csv", "tsv", "xlsx", "xlsm", "xls", "json", "xml", "ods", "txt_table"}
DATA_OUT = {"csv", "tsv", "xlsx", "json", "xml", "html", "md", "sql"}


def read_sheets(src: Path) -> dict[str, pd.DataFrame]:
    ext = src.suffix.lower().lstrip(".")
    if src.stat().st_size == 0:
        raise ValueError("This file is empty")
    if ext in ("xlsx", "xlsm", "xls", "ods"):
        engine = {"xls": "xlrd", "ods": "odf"}.get(ext)
        sheets = pd.read_excel(src, sheet_name=None, engine=engine)
    elif ext in ("csv", "tsv"):
        text = read_text(src)  # Excel's "CSV" is often ANSI or UTF-16, not UTF-8
        if not text.strip():
            raise ValueError("This file is empty")
        sheets = {src.stem: pd.read_csv(io.StringIO(text), sep="\t" if ext == "tsv" else _sniff(text))}
    elif ext == "json":
        try:
            raw = json.loads(read_text(src))
        except json.JSONDecodeError as e:
            raise ValueError(f"This isn't valid JSON ({e.msg} at line {e.lineno})") from None
        if isinstance(raw, dict) and raw and all(isinstance(v, list) for v in raw.values()):
            sheets = {k: _json_frame(v) for k, v in raw.items()}  # {"sheet": [rows]}
        else:
            sheets = {src.stem: _json_frame(raw if isinstance(raw, list) else [raw])}
    elif ext == "xml":
        try:
            sheets = {src.stem: pd.read_xml(src)}
        except Exception as e:
            raise ValueError(f"Couldn't find a table of repeating rows in this XML ({e})") from None
    else:
        raise ValueError(f"Can't read .{ext} as a table")
    full = {k: v for k, v in sheets.items() if len(v.columns)}  # blank sheets would become empty files
    if not full:
        raise ValueError("No data found in this file")
    return full


def _sniff(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
    except csv.Error:
        return ","  # e.g. a single column: nothing to detect


def _json_frame(rows) -> pd.DataFrame:
    rows = [r if isinstance(r, dict) else {"value": r} for r in rows]  # [1, 2, 3] is a one-column table
    df = pd.json_normalize(rows)
    # nested lists can't go in a cell (and break the md/sql/xml writers): keep them as JSON text
    return df.map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)


def _file_safe(name) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .") or "sheet"


def _sheet_titles(names) -> list[str]:
    """Excel sheet names: max 31 chars, no []:*?/\\ and unique (case-insensitively)."""
    out = []
    for name in names:
        base = re.sub(r"[\[\]:*?/\\]", "_", str(name)).strip("'")[:31] or "Sheet1"
        title, n = base, 2
        while title.lower() in (t.lower() for t in out):
            title = f"{base[:31 - len(str(n)) - 1]}_{n}"
            n += 1
        out.append(title)
    return out


def convert_table(src: Path, out: Path, params: dict, sheets=None):
    sheets = read_sheets(src) if sheets is None else sheets
    fmt = out.suffix.lower().lstrip(".")
    if fmt == "xlsx":
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            for title, df in zip(_sheet_titles(sheets), sheets.values()):
                df.to_excel(w, sheet_name=title, index=False)
            for ws in w.book.worksheets:  # auto column widths
                for col in ws.columns:
                    width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
                    ws.column_dimensions[col[0].column_letter].width = min(60, width + 2)
        return [out]
    if fmt == "json" and len(sheets) > 1:
        out.write_text(json.dumps({k: json.loads(v.to_json(orient="records", date_format="iso"))
                                   for k, v in sheets.items()}, indent=2, ensure_ascii=False), encoding="utf-8")
        return [out]
    if fmt == "html":
        body = "".join(f"<h2>{htmllib.escape(str(name))}</h2>" + df.to_html(index=False, na_rep="", border=1) for name, df in sheets.items())
        out.write_text(f"<!doctype html><meta charset='utf-8'><body>{body}</body>", encoding="utf-8")
        return [out]

    outs = []
    multi = len(sheets) > 1
    for name, df in sheets.items():
        target = out.with_name(f"{out.stem}_{_file_safe(name)}{out.suffix}") if multi else out
        if fmt == "csv":
            df.to_csv(target, index=False, encoding="utf-8-sig")
        elif fmt == "tsv":
            df.to_csv(target, index=False, sep="\t", encoding="utf-8")
        elif fmt == "json":
            target.write_text(df.to_json(orient="records", indent=2, date_format="iso", force_ascii=False),
                              encoding="utf-8")
        elif fmt == "xml":
            df.columns = [_xml_safe(c) for c in df.columns]
            df.to_xml(target, index=False)
        elif fmt == "md":
            target.write_text(_to_markdown(df), encoding="utf-8")
        elif fmt == "sql":
            target.write_text(_to_sql(df, _xml_safe(name)), encoding="utf-8")
        outs.append(target)
    return outs


def table_to_pdf(src: Path, out: Path, params: dict):
    from .conv_pdf import html_to_pdf
    sheets = read_sheets(src)
    body = "".join(f"<h3>{htmllib.escape(str(name))}</h3>" + df.to_html(index=False, na_rep="", border=1) for name, df in sheets.items())
    wide = max(len(df.columns) for df in sheets.values()) > 6
    return html_to_pdf(src, out, {**params, "orientation": "landscape" if wide else "portrait"},
                       html=f"<body>{body}</body>")


def tool_merge_tables(srcs: list[Path], out: Path, params: dict):
    frames = []
    for s in srcs:
        for name, df in read_sheets(s).items():
            if params.get("add_source", True):
                df.insert(0, "source", f"{s.name}" + (f":{name}" if name != s.stem else ""))
            frames.append(df)
    merged = pd.concat(frames, ignore_index=True, sort=False)
    # written straight from the merged table: no CSV round trip (which lost types and named the sheet "x.tmp")
    return convert_table(out, out, params, sheets={"Merged": merged})


def _xml_safe(name) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(name)) or "col"
    return s if not s[0].isdigit() else "_" + s


def _to_markdown(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    esc = lambda v: "" if pd.isna(v) else str(v).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(esc(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines) + "\n"


def _to_sql(df: pd.DataFrame, table: str) -> str:
    cols = [_xml_safe(c) for c in df.columns]
    def lit(v):
        if pd.isna(v):
            return "NULL"
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"
    lines = [f"CREATE TABLE {table} (" + ", ".join(f"{c} TEXT" for c in cols) + ");"]
    for row in df.itertuples(index=False):
        lines.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(lit(v) for v in row)});")
    return "\n".join(lines) + "\n"
