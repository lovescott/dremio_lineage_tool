"""
SQL parsing — extracts upstream table/view references from VIEW_DEFINITION SQL.
Uses sqlglot with a regex fallback.
"""

import re
import logging

import sqlglot
from sqlglot import exp

log = logging.getLogger(__name__)


def normalize_ref(ref: str) -> str:
    """Strip quotes and lowercase a table reference."""
    return ref.strip('"').strip("`").strip("'").lower()


def extract_references_sqlglot(view_sql: str) -> set[str]:
    """
    Parse a view SQL string with sqlglot and return all upstream
    table/view references as 'schema.name' strings.
    """
    refs = set()
    if not view_sql:
        return refs
    try:
        statements = sqlglot.parse(view_sql, dialect="dremio", error_level=sqlglot.ErrorLevel.WARN)
        for stmt in statements:
            if stmt is None:
                continue
            for table in stmt.find_all(exp.Table):
                parts = []
                if table.args.get("db"):
                    parts.append(normalize_ref(str(table.args["db"])))
                if table.args.get("this"):
                    parts.append(normalize_ref(str(table.args["this"])))
                if parts:
                    refs.add(".".join(parts))
    except Exception as e:
        log.debug(f"sqlglot parse warning: {e}")
        refs = extract_references_regex(view_sql)
    return refs


def extract_references_regex(view_sql: str) -> set[str]:
    """
    Fallback regex extraction for FROM / JOIN clauses.
    Handles quoted identifiers with dots.
    """
    refs = set()
    pattern = r'(?:FROM|JOIN)\s+((?:"[^"]+"|`[^`]+`|\w+)(?:\.(?:"[^"]+"|`[^`]+`|\w+))*)'
    for match in re.finditer(pattern, view_sql, re.IGNORECASE):
        raw = match.group(1)
        parts = [normalize_ref(p) for p in raw.split(".")]
        refs.add(".".join(parts))
    return refs
