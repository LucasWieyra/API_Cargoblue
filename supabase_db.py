from __future__ import annotations
import os
from typing import Any

from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import create_client

load_dotenv()


def _get_secret(name: str, default: str = "") -> str:
    """Lê variável de st.secrets (Streamlit Cloud) ou os.getenv (local/.env)."""
    try:
        import streamlit as st
        val = st.secrets.get(name, None)
        if val:
            return str(val).strip().strip('"')
    except Exception:
        pass
    return (os.getenv(name, default) or default).strip().strip('"')


SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _get_secret("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Configure SUPABASE_URL e SUPABASE_SERVICE_KEY no arquivo .env ou em Secrets no Streamlit Cloud")

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def clean_value(value: Any) -> Any:
    if value in ("", "None", "none", "null", "NULL", None):
        return None
    return value


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: clean_value(v) for k, v in row.items()}


def test_connection() -> bool:
    sb.table("integracao_execucoes").select("id").limit(1).execute()
    return True


def upsert_rows(table: str, rows: list[dict[str, Any]], on_conflict: str, batch_size: int = 300) -> int:
    if not rows:
        return 0
    rows = [clean_row(r) for r in rows]
    conflict_cols = [c.strip() for c in on_conflict.split(",")]
    valid_rows = []
    for row in rows:
        if all(row.get(c) not in (None, "") for c in conflict_cols):
            valid_rows.append(row)
    if not valid_rows:
        return 0

    total = 0
    for i in range(0, len(valid_rows), batch_size):
        batch = valid_rows[i:i + batch_size]
        try:
            sb.table(table).upsert(batch, on_conflict=on_conflict).execute()
            total += len(batch)
        except APIError as exc:
            print("\n========== ERRO SUPABASE UPSERT ==========")
            print("Tabela:", table)
            print("Chave:", on_conflict)
            print("Primeiro registro:", batch[0] if batch else None)
            print("Erro completo:", exc)
            print("==========================================\n")
            raise
    return total


def insert_rows(table: str, rows: list[dict[str, Any]], batch_size: int = 300) -> int:
    if not rows:
        return 0
    rows = [clean_row(r) for r in rows]
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        try:
            sb.table(table).insert(batch).execute()
            total += len(batch)
        except APIError as exc:
            print("\n========== ERRO SUPABASE INSERT ==========")
            print("Tabela:", table)
            print("Primeiro registro:", batch[0] if batch else None)
            print("Erro completo:", exc)
            print("==========================================\n")
            raise
    return total


def select_rows(table: str, columns: str = "*", limit: int = 1000, order_by: str | None = None, desc: bool = True) -> list[dict[str, Any]]:
    try:
        query = sb.table(table).select(columns).limit(limit)
        if order_by:
            query = query.order(order_by, desc=desc)
        result = query.execute()
        return result.data or []
    except APIError as exc:
        print(f"\n========== ERRO SUPABASE SELECT ==========")
        print(f"Tabela: {table}")
        print(f"Colunas: {columns}")
        print(f"Erro: {exc}")
        print("==========================================\n")
        return []
    except Exception as exc:
        print(f"[select_rows] Erro inesperado em '{table}': {exc}")
        return []


def select_distinct_values(table: str, column: str, limit: int = 20000) -> list[str]:
    data = select_rows(table, column, limit=limit)
    values: list[str] = []
    for item in data:
        value = item.get(column)
        if value and value not in values:
            values.append(value)
    return values
