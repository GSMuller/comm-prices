# ──────────────────────────────────────────────────────────────
# db.py  –  Persistência de ativos no PostgreSQL
# ──────────────────────────────────────────────────────────────
from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor

# ─── Configuração de conexão ──────────────────────────────────
_DB_CONFIG = {
    "host":     "192.168.0.39",
    "port":     5432,
    "dbname":   "postgres",
    "user":     "gs_muller",
    "password": "911723",
    "connect_timeout": 5,
}

_SCHEMA = "comm_prices"
_TABLE  = f"{_SCHEMA}.assets"


def _conn():
    """Abre e retorna uma nova conexão com o banco."""
    return psycopg2.connect(**_DB_CONFIG)


# ─── Inicialização ────────────────────────────────────────────

def init_db() -> None:
    """
    Cria o schema e a tabela se ainda não existirem.
    Se a tabela estiver vazia, popula com DEFAULT_ASSETS.
    """
    from config import DEFAULT_ASSETS

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    id            TEXT PRIMARY KEY,
                    name          TEXT        NOT NULL,
                    ticker        TEXT        NOT NULL,
                    type          TEXT        NOT NULL DEFAULT 'stock',
                    icon          TEXT,
                    base_currency TEXT        NOT NULL DEFAULT 'USD',
                    gram_convert  BOOLEAN     NOT NULL DEFAULT FALSE,
                    unit          TEXT,
                    coingecko_id  TEXT,
                    sort_order    INTEGER     NOT NULL DEFAULT 0,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Seed com defaults se tabela vazia
            cur.execute(f"SELECT COUNT(*) FROM {_TABLE}")
            if cur.fetchone()[0] == 0:
                for i, asset in enumerate(DEFAULT_ASSETS):
                    _upsert_cur(cur, asset, i)

        conn.commit()


# ─── CRUD ─────────────────────────────────────────────────────

def _upsert_cur(cur, asset: dict, sort_order: int = 0) -> None:
    """INSERT … ON CONFLICT DO UPDATE (upsert) usando cursor existente."""
    cur.execute(
        f"""
        INSERT INTO {_TABLE}
            (id, name, ticker, type, icon, base_currency,
             gram_convert, unit, coingecko_id, sort_order, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
        ON CONFLICT (id) DO UPDATE SET
            name          = EXCLUDED.name,
            ticker        = EXCLUDED.ticker,
            type          = EXCLUDED.type,
            icon          = EXCLUDED.icon,
            base_currency = EXCLUDED.base_currency,
            gram_convert  = EXCLUDED.gram_convert,
            unit          = EXCLUDED.unit,
            coingecko_id  = EXCLUDED.coingecko_id,
            sort_order    = EXCLUDED.sort_order,
            updated_at    = NOW()
        """,
        (
            asset["id"],
            asset["name"],
            asset["ticker"],
            asset.get("type", "stock"),
            asset.get("icon", ""),
            asset.get("base_currency", "USD"),
            bool(asset.get("gram_convert", False)),
            asset.get("unit"),
            asset.get("coingecko_id"),
            sort_order,
        ),
    )


def load_assets() -> list[dict]:
    """Retorna todos os ativos ordenados por sort_order, created_at."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, name, ticker, type, icon, base_currency,
                       gram_convert, unit, coingecko_id
                FROM   {_TABLE}
                ORDER  BY sort_order, created_at
                """
            )
            return [dict(r) for r in cur.fetchall()]


def upsert_asset(asset: dict, sort_order: int = 0) -> None:
    """Insere ou atualiza um ativo."""
    with _conn() as conn:
        with conn.cursor() as cur:
            _upsert_cur(cur, asset, sort_order)
        conn.commit()


def delete_asset(asset_id: str) -> None:
    """Remove um ativo pelo id."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_TABLE} WHERE id = %s", (asset_id,))
        conn.commit()


def replace_all_assets(assets: list[dict]) -> None:
    """Substitui todos os ativos (usado no 'Restaurar padrão')."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_TABLE}")
            for i, asset in enumerate(assets):
                _upsert_cur(cur, asset, i)
        conn.commit()
