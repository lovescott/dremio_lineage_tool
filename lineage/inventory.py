"""
Inventory pull — fetches tables, views, and column metadata from INFORMATION_SCHEMA.
"""

import logging
from typing import Optional

import pandas as pd

from .client import DremioConfig

log = logging.getLogger(__name__)


def fetch_inventory(cfg: DremioConfig, space_filter: Optional[str] = None) -> pd.DataFrame:
    """Pull all tables and views from INFORMATION_SCHEMA."""
    log.info("Fetching inventory from INFORMATION_SCHEMA ...")

    where = f"WHERE TABLE_SCHEMA LIKE '{space_filter}%'" if space_filter else ""

    query = f"""
        SELECT
            t.TABLE_SCHEMA,
            t.TABLE_NAME,
            t.TABLE_TYPE,
            v.VIEW_DEFINITION
        FROM INFORMATION_SCHEMA."TABLES" t
        LEFT JOIN INFORMATION_SCHEMA."VIEWS" v
            ON t.TABLE_SCHEMA = v.TABLE_SCHEMA
           AND t.TABLE_NAME   = v.TABLE_NAME
        {where}
        ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME
    """
    rows = cfg.sql(query)
    df = pd.DataFrame(rows)
    log.info(f"  Found {len(df)} objects.")
    return df


def fetch_columns(cfg: DremioConfig, space_filter: Optional[str] = None) -> pd.DataFrame:
    """Pull column metadata for DDL reconstruction."""
    log.info("Fetching column metadata ...")

    where = f"WHERE TABLE_SCHEMA LIKE '{space_filter}%'" if space_filter else ""

    query = f"""
        SELECT
            TABLE_SCHEMA,
            TABLE_NAME,
            COLUMN_NAME,
            ORDINAL_POSITION,
            DATA_TYPE,
            IS_NULLABLE,
            NUMERIC_PRECISION,
            NUMERIC_SCALE,
            CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        {where}
        ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
    """
    rows = cfg.sql(query)
    df = pd.DataFrame(rows)
    log.info(f"  Found {len(df)} columns.")
    return df
