import os
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import create_client

load_dotenv()

def _secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value).strip().strip('"')
    except Exception:
        pass
    return (os.getenv(name, default) or default).strip().strip('"')

SUPABASE_URL = _secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _secret("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Configure SUPABASE_URL e SUPABASE_SERVICE_KEY no arquivo .env")

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


def _dedupe_rows_by_conflict(rows: list[dict[str, Any]], conflict_cols: list[str]) -> list[dict[str, Any]]:
    """
    Evita erro PostgreSQL 21000:
    ON CONFLICT DO UPDATE command cannot affect row a second time.

    Esse erro acontece quando o mesmo upsert envia duas linhas com a mesma chave
    dentro do mesmo lote, por exemplo a mesma SM ou o mesmo documento repetido no
    retorno da Raster. Mantemos o último registro, que normalmente é o mais recente.
    """
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}

    for row in rows:
        key = tuple(row.get(col) for col in conflict_cols)
        if any(value in (None, "") for value in key):
            continue
        deduped[key] = row

    return list(deduped.values())


def upsert_rows(table: str, rows: list[dict[str, Any]], on_conflict: str, batch_size: int = 200) -> int:
    if not rows:
        return 0

    rows = [clean_row(r) for r in rows]
    conflict_cols = [c.strip() for c in on_conflict.split(",") if c.strip()]

    # Primeiro remove linhas sem chave válida.
    valid_rows = []
    for row in rows:
        if all(row.get(c) not in (None, "") for c in conflict_cols):
            valid_rows.append(row)

    if not valid_rows:
        return 0

    # Depois remove duplicidade dentro do mesmo payload antes do upsert.
    # Isso corrige o erro: ON CONFLICT DO UPDATE command cannot affect row a second time.
    valid_rows = _dedupe_rows_by_conflict(valid_rows, conflict_cols)

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
            print("Quantidade lote:", len(batch))
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
    query = sb.table(table).select(columns).limit(limit)
    if order_by:
        query = query.order(order_by, desc=desc)
    result = query.execute()
    return result.data or []


def select_distinct_values(table: str, column: str, limit: int = 20000) -> list[str]:
    data = select_rows(table, column, limit=limit)
    values: list[str] = []
    for item in data:
        value = item.get(column)
        if value and value not in values:
            values.append(value)
    return values
