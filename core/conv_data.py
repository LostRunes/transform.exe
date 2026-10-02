"""Spreadsheet / tabular data conversions (pandas + openpyxl)."""
import json
from pathlib import Path

import pandas as pd

DATA_IN = {"csv", "tsv", "xlsx", "xlsm", "xls", "json", "xml", "ods", "txt_table"}
DATA_OUT = {"csv", "tsv", "xlsx", "json", "xml", "html", "md", "sql"}


def read_sheets(src: Path) -> dict[str, pd.DataFrame]:
    ext = src.suffix.lower().lstrip(".")
    if ext in ("xlsx", "xlsm", "xls", "ods"):
        engine = {"xls": "xlrd", "ods": "odf"}.get(ext)
        return pd.read_excel(src, sheet_name=None, engine=engine)
    if ext == "csv":
        return {src.stem: pd.read_csv(src, sep=None, engine="python", encoding_errors="replace")}
    if ext == "tsv":
        return {src.stem: pd.read_csv(src, sep="\t", encoding_errors="replace")}
    if ext == "json":
        raw = json.loads(src.read_text(encoding="utf-8", errors="replace"))
        if isinstance(raw, dict) and all(isinstance(v, list) for v in raw.values()):
            return {k: pd.json_normalize(v) for k, v in raw.items()}  # {"sheet": [rows]}
        return {src.stem: pd.json_normalize(raw if isinstance(raw, list) else [raw])}
    if ext == "xml":
        return {src.stem: pd.read_xml(src)}
    raise ValueError(f"Can't read .{ext} as a table")


def convert_table(src: Path, out: Path, params: dict):
    sheets = read_sheets(src)
    fmt = out.suffix.lower().lstrip(".")
    if fmt == "xlsx":
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            for name, df in sheets.items():
                df.to_excel(w, sheet_name=str(name)[:31] or "Sheet1", index=False)
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
        body = "".join(f"<h2>{name}</h2>" + df.to_html(index=False, na_rep="", border=1) for name, df in sheets.items())
        out.write_text(f"<!doctype html><meta charset='utf-8'><body>{body}</body>", encoding="utf-8")
        return [out]

    outs = []
    multi = len(sheets) > 1
    for name, df in sheets.items():
        target = out.with_name(f"{out.stem}_{name}{out.suffix}") if multi else out
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
    body = "".join(f"<h3>{name}</h3>" + df.to_html(index=False, na_rep="", border=1) for name, df in sheets.items())
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
    tmp = out.with_suffix(".tmp.csv")
    merged.to_csv(tmp, index=False)
    try:
        return convert_table(tmp, out, params) if out.suffix != ".csv" else [tmp.replace(out)]
    finally:
        tmp.unlink(missing_ok=True)


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
