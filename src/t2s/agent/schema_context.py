"""Schema context builder: DDL -> descriptions -> joins -> enum values -> glossary."""
from __future__ import annotations
import re
import yaml
from ..utils.config import SCHEMA_YAML, GLOSSARY_YAML


_SAFE_ENUM = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")   # no spaces/punctuation: an enum value cannot carry a sentence


class SchemaContext:
    def __init__(self, con, schema_path=SCHEMA_YAML, glossary_path=GLOSSARY_YAML, max_distinct: int = 8,
                 meta: dict | None = None, glossary: dict | None = None):
        self.con = con
        self.meta = meta if meta is not None else yaml.safe_load(open(schema_path))
        self.glossary = glossary if glossary is not None else yaml.safe_load(open(glossary_path))
        self.max_distinct = max_distinct
        self._cols = self._load_columns()
        self._enums: dict[tuple[str, str], list] = {}

    @property
    def tables(self) -> list[str]:
        return list(self.meta.keys())

    def _load_columns(self):
        out: dict[str, list[tuple[str, str]]] = {}
        for t, c, d in self.con.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='main' ORDER BY table_name, ordinal_position").fetchall():
            out.setdefault(t, []).append((c, d))
        return out

    def _enum_values(self, t: str, col: str):
        key = (t, col)
        if key not in self._enums:
            if col in self.meta[t].get("_deny_samples", []):       # free text: injection channel, never sampled
                self._enums[key] = []
            else:
                n = self.con.execute(f'SELECT COUNT(DISTINCT "{col}") FROM "{t}"').fetchone()[0]
                vals = [] if n > self.max_distinct or n == 0 else sorted(
                    r[0] for r in self.con.execute(
                        f'SELECT DISTINCT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL').fetchall())
                # injection defense: if any value is not a plain token, show none rather than a poisoned list
                bad = any(isinstance(v, str) and not _SAFE_ENUM.match(v) for v in vals)
                self._enums[key] = [] if bad else vals
        return self._enums[key]

    def build(self, tables=None, descriptions=True, samples=True, glossary=True) -> str:
        tables = tables or self.tables
        blocks = []
        for t in tables:
            if not descriptions:                                        # step 1: raw DDL only
                cols = ", ".join(f"{c} {d}" for c, d in self._cols[t])
                blocks.append(f"CREATE TABLE {t} ({cols});")
                continue
            lines = [f"TABLE {t}  -- {self.meta[t].get('_desc', '')}"]
            for col, dtype in self._cols[t]:
                desc = self.meta[t]["columns"].get(col, "")
                extra = ""
                if samples:
                    vals = self._enum_values(t, col)
                    if vals:
                        extra = f" | values: {vals}"
                lines.append(f"  - {col} ({dtype}): {desc}{extra}")
            for j in self.meta[t].get("_joins", []):
                lines.append(f"  JOIN: {j}")
            blocks.append("\n".join(lines))
        out = "\n\n".join(blocks)
        if glossary and any(k != "dialect" for k in self.glossary):
            g = "\n".join(f"- {k}: {' '.join(str(v).split())}" for k, v in self.glossary.items() if k != "dialect")
            out += f"\n\nBUSINESS DEFINITIONS:\n{g}"
        return out
