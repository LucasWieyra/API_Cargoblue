import os
import json
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client
from postgrest.exceptions import APIError

load_dotenv()


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Lê primeiro do Streamlit Secrets e depois do .env/local.
    Funciona no Streamlit Cloud e também localmente.
    """
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass

    value = os.getenv(name)
    if value is not None:
        return value

    return default


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError(
        "SUPABASE_URL ou SUPABASE_SERVICE_KEY não configurados. "
        "Configure em Settings > Secrets no Streamlit Cloud."
    )

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def clean_value(value: Any) -> Any:
    if value in ["", "None", "null", "NULL"]:
        return None

    if isinstance(value, float):
        try:
            if value != value:
                return None
        except Exception:
            pass

    return value


def clean_row(row: Dict[str, Any]) -> Dict[str, Any]:
    clean = {}

    for key, value in row.items():
        value = clean_value(value)

        if isinstance(value, (dict, list)):
            clean[key] = value
        else:
            clean[key] = value

    return clean


def chunk_list(rows: List[Dict[str, Any]], size: int = 100) -> List[List[Dict[str, Any]]]:
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def upsert_rows(
    table: str,
    rows: List[Dict[str, Any]],
    on_conflict: Optional[str] = None,
    batch_size: int = 100,
) -> int:
    if not rows:
        return 0

    rows = [clean_row(row) for row in rows]

    if on_conflict:
        rows = [
            row for row in rows
            if row.get(on_conflict) not in [None, ""]
        ]

    if not rows:
        return 0

    total = 0

    for batch in chunk_list(rows, batch_size):
        try:
            query = sb.table(table).upsert(batch)

            if on_conflict:
                query = sb.table(table).upsert(batch, on_conflict=on_conflict)

            query.execute()
            total += len(batch)

        except APIError as e:
            print("ERRO SUPABASE UPSERT")
            print("Tabela:", table)
            print("on_conflict:", on_conflict)
            print("Primeiro registro:", batch[0] if batch else None)
            print("Erro:", e)
            raise

    return total


def insert_rows(
    table: str,
    rows: List[Dict[str, Any]],
    batch_size: int = 100,
) -> int:
    if not rows:
        return 0

    rows = [clean_row(row) for row in rows]
    total = 0

    for batch in chunk_list(rows, batch_size):
        try:
            sb.table(table).insert(batch).execute()
            total += len(batch)
        except APIError as e:
            print("ERRO SUPABASE INSERT")
            print("Tabela:", table)
            print("Primeiro registro:", batch[0] if batch else None)
            print("Erro:", e)
            raise

    return total


def select_rows(
    table: str,
    columns: str = "*",
    limit: int = 1000,
    order_by: Optional[str] = None,
    desc: bool = True,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    query = sb.table(table).select(columns).limit(limit)

    if filters:
        for key, value in filters.items():
            query = query.eq(key, value)

    if order_by:
        query = query.order(order_by, desc=desc)

    response = query.execute()
    return response.data or []


def select_all(
    table: str,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    response = sb.table(table).select("*").limit(limit).execute()
    return response.data or []


def select_distinct_values(
    table: str,
    column: str,
    limit: int = 10000,
) -> List[Any]:
    response = sb.table(table).select(column).limit(limit).execute()

    values = []
    seen = set()

    for item in response.data or []:
        value = item.get(column)

        if value in [None, ""]:
            continue

        key = str(value)

        if key not in seen:
            seen.add(key)
            values.append(value)

    return values


def test_connection() -> bool:
    sb.table("integracao_execucoes").select("*").limit(1).execute()
    return True
