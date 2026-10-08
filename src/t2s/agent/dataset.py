"""User-uploaded data -> an isolated, read-only, locked DuckDB file with a sanitised, auto-documented schema.

Security notes: ingestion runs on a throwaway writer connection BEFORE the query connection is opened; the query
connection has external access disabled and its config locked, so SQL (even if it slipped past the validator)
cannot read other files or modify the data. Table/column names are sanitised to [a-z0-9_] (they appear in the
prompt, so they must not carry sentences), and enum sample values go through the same token-only filter as Olist."""
from __future__ import annotations
import os, re, shutil, time, uuid
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from ..guardrails.executor import make_connection
from ..utils.config import ROOT
from .schema_context import SchemaContext

UPLOAD_ROOT = Path(os.environ.get("T2S_UPLOAD_DIR", ROOT / ".cache/uploads"))
MAX_FILES = 8
MAX_FILE_BYTES = int(os.environ.get("T2S_MAX_UPLOAD_MB", "50")) * 1024 * 1024
MAX_ROWS = 5_000_000
EXTS = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".parquet", ".json", ".jsonl", ".ndjson"}
RESERVED = {"select", "from", "where", "group", "order", "by", "table", "index", "limit", "union", "join", "on", "as",
            "and", "or", "not", "null", "case", "when", "then", "else", "end", "having", "distinct", "all", "user",
            "desc", "asc", "in", "is", "like", "between", "exists", "create", "drop", "insert", "update", "delete"}


class UploadError(ValueError):
    pass


def slug(s: str, fallback: str = "col", suffix: str = "_col") -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")[:40] or fallback
    if s[0].isdigit():
        s = f"{fallback}_{s}"
    return s + suffix if s in RESERVED else s


def _unique(name: str, taken: set[str]) -> str:
    base, i = name, 2
    while name in taken:
        name, i = f"{base}_{i}", i + 1
    taken.add(name)
    return name


@dataclass
class Dataset:
    id: str
    name: str
    path: Path
    con: object
    ctx: SchemaContext
    tables: dict = field(default_factory=dict)      # name -> {"rows": int, "columns": [(name, type)], "source": str}
    created: float = field(default_factory=time.time)

    @property
    def description(self) -> str:
        return ("user-uploaded tables: " + ", ".join(f"{t} ({v['source']})" for t, v in self.tables.items()))

    def info(self) -> dict:
        return {"id": self.id, "name": self.name,
                "tables": [{"name": t, "rows": v["rows"], "source": v["source"],
                            "columns": [{"name": c, "type": d} for c, d in v["columns"]]} for t, v in self.tables.items()]}

    def preview(self, table: str, n: int = 10):
        if table not in self.tables:
            raise KeyError(table)
        return self.con.cursor().execute(f'SELECT * FROM "{table}" LIMIT {int(n)}').fetch_df()

    def close(self):
        try:
            self.con.close()
        finally:
            shutil.rmtree(self.path.parent, ignore_errors=True)


def _load_one(w, fname: str, raw: Path, taken: set[str]) -> list[tuple[str, str]]:
    """Create one or more tables in writer connection `w`; returns [(table, source_label)]."""
    ext = raw.suffix.lower()
    stem = slug(Path(fname).stem, "table", "_data")
    created = []

    def finish(tmp: str, name: str, label: str):
        cols = [r[0] for r in w.execute(f'DESCRIBE "{tmp}"').fetchall()]
        seen: set[str] = set()
        sel = ", ".join(f'"{c}" AS "{_unique(slug(c), seen)}"' for c in cols)
        tname = _unique(name, taken)
        w.execute(f'CREATE TABLE "{tname}" AS SELECT {sel} FROM "{tmp}"')
        w.execute(f'DROP TABLE "{tmp}"')
        n = w.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
        if n == 0:
            raise UploadError(f"{fname}: no rows found")
        if n > MAX_ROWS:
            raise UploadError(f"{fname}: {n:,} rows exceeds the {MAX_ROWS:,} row limit")
        created.append((tname, label))

    p = str(raw).replace("'", "''")
    try:
        if ext in (".csv", ".tsv", ".txt"):
            try:
                w.execute(f"CREATE TABLE _tmp AS SELECT * FROM read_csv_auto('{p}', header=true, sample_size=20000)")
            except duckdb.Error:      # messy file: fall back to all-text columns
                w.execute("DROP TABLE IF EXISTS _tmp")
                w.execute(f"CREATE TABLE _tmp AS SELECT * FROM read_csv_auto('{p}', header=true, all_varchar=true, ignore_errors=true)")
            finish("_tmp", stem, fname)
        elif ext == ".parquet":
            w.execute(f"CREATE TABLE _tmp AS SELECT * FROM read_parquet('{p}')"); finish("_tmp", stem, fname)
        elif ext in (".json", ".jsonl", ".ndjson"):
            w.execute(f"CREATE TABLE _tmp AS SELECT * FROM read_json_auto('{p}')"); finish("_tmp", stem, fname)
        elif ext in (".xlsx", ".xls"):
            import pandas as pd
            sheets = pd.read_excel(raw, sheet_name=None)
            for sheet, df in sheets.items():
                if df.empty:
                    continue
                w.register("_df", df)
                w.execute("CREATE TABLE _tmp AS SELECT * FROM _df"); w.unregister("_df")
                finish("_tmp", stem if len(sheets) == 1 else f"{stem}_{slug(sheet, 'sheet', '_sheet')}", f"{fname}:{sheet}")
    except UploadError:
        raise
    except Exception as e:  # noqa: BLE001 - surface a readable message to the user
        raise UploadError(f"Could not read {fname}: {str(e).splitlines()[0][:160]}")
    if not created:
        raise UploadError(f"{fname}: no data found")
    return created


def create_dataset(files: list[tuple[str, bytes]], name: str | None = None) -> Dataset:
    """files = [(filename, bytes)]. Returns a ready-to-query Dataset."""
    if not files:
        raise UploadError("No files provided")
    if len(files) > MAX_FILES:
        raise UploadError(f"At most {MAX_FILES} files per dataset")
    ds_id = uuid.uuid4().hex[:12]
    work = UPLOAD_ROOT / ds_id
    (work / "raw").mkdir(parents=True)
    db_path = work / "data.duckdb"
    try:
        w = duckdb.connect(str(db_path))
        taken: set[str] = set()
        tables: dict = {}
        for i, (fname, data) in enumerate(files):
            ext = Path(fname).suffix.lower()
            if ext not in EXTS:
                raise UploadError(f"Unsupported file type '{ext}' ({fname}). Use: {', '.join(sorted(EXTS))}")
            if len(data) > MAX_FILE_BYTES:
                raise UploadError(f"{fname} is larger than {MAX_FILE_BYTES // 2**20} MB")
            raw = work / "raw" / f"f{i}{ext}"          # never trust client file names on disk
            raw.write_bytes(data)
            for tname, label in _load_one(w, Path(fname).name, raw, taken):
                tables[tname] = {"source": label}
        w.close()
        shutil.rmtree(work / "raw", ignore_errors=True)
        con = make_connection(db_path)                  # read-only, no external access, config locked
        meta, info = {}, {}
        cols_by_table = {}
        for t in tables:
            cols_by_table[t] = con.execute("SELECT column_name, data_type FROM information_schema.columns "
                                           "WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position", [t]).fetchall()
        for t, cols in cols_by_table.items():
            joins = []
            for u, ucols in cols_by_table.items():
                if u != t:
                    for c, d in cols:
                        if any(c == c2 and d == d2 for c2, d2 in ucols) and (c.endswith("id") or c.endswith("key") or c.endswith("code")):
                            joins.append(f"{t}.{c} = {u}.{c}   (same column name and type; likely join key)")
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            meta[t] = {"_desc": f"Uploaded from {tables[t]['source']} ({n:,} rows)", "_joins": joins, "columns": {c: "" for c, _ in cols}}
            info[t] = {"rows": n, "columns": cols, "source": tables[t]["source"]}
        ctx = SchemaContext(con, meta=meta, glossary={})
        return Dataset(ds_id, name or ", ".join(Path(f).stem for f, _ in files)[:60], db_path, con, ctx, info)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def cleanup_old(max_age_s: float = 24 * 3600) -> None:
    if UPLOAD_ROOT.exists():
        for d in UPLOAD_ROOT.iterdir():
            if d.is_dir() and time.time() - d.stat().st_mtime > max_age_s:
                shutil.rmtree(d, ignore_errors=True)
