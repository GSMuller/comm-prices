# ──────────────────────────────────────────────────────────────
# data.py  –  Busca de preços e cálculo de indicadores técnicos
# ──────────────────────────────────────────────────────────────
from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

from config import FX_FALLBACK, FX_TICKER, TROY_OUNCE_TO_GRAM

# ─── Câmbio ───────────────────────────────────────────────────

def get_usd_brl() -> float:
    """Retorna a taxa de câmbio USD/BRL atual."""
    try:
        info = yf.Ticker(FX_TICKER).fast_info
        price = float(info.last_price or 0)
        if price > 0:
            return price
    except Exception:
        pass
    return FX_FALLBACK


# ─── Preço atual (cards) ──────────────────────────────────────

def _yf_spot(ticker: str) -> tuple[float | None, float | None]:
    """Devolve (last_price, prev_close) via yfinance."""
    try:
        obj = yf.Ticker(ticker)
        # fast_info é muito mais rápido que history()
        info = obj.fast_info
        last = float(info.last_price or info.previous_close or 0)
        prev = float(info.previous_close or last)
        if last and last > 0:
            return last, prev
        # fallback para history se fast_info falhar
        df = obj.history(period="5d", interval="1d", timeout=8)
        if df.empty:
            return None, None
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else last
        return last, prev
    except Exception:
        return None, None


def _coingecko_spot(coingecko_id: str) -> tuple[float | None, float | None, float | None]:
    """
    Retorna (price_usd, change_24h_pct, change_24h_abs) via CoinGecko (gratuito).
    """
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={coingecko_id}&vs_currencies=usd"
        "&include_24hr_change=true&include_24hr_vol=true"
    )
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        data = resp.json().get(coingecko_id, {})
        price = data.get("usd")
        pct   = data.get("usd_24h_change")
        abs_  = price * pct / 100 if price and pct else 0.0
        return price, pct, abs_
    except Exception:
        return None, None, None


def get_current_price(asset: dict[str, Any]) -> dict[str, Any]:
    """
    Busca o preço atual de um ativo.

    Retorna um dicionário com:
      price, prev_close, change, change_pct, base_currency, timestamp
    """
    ticker       = asset["ticker"]
    gram_convert = asset.get("gram_convert", False)
    base_currency = asset.get("base_currency", "USD")
    cg_id        = asset.get("coingecko_id")

    result: dict[str, Any] = {
        "price":         None,
        "prev_close":    None,
        "change":        0.0,
        "change_pct":    0.0,
        "base_currency": base_currency,
        "timestamp":     datetime.now().strftime("%H:%M:%S"),
        "error":         None,
    }

    try:
        if cg_id:
            price, pct, abs_ = _coingecko_spot(cg_id)
            if price is None:                        # fallback para yfinance
                price, prev = _yf_spot(ticker)
                if price and prev:
                    abs_  = price - prev
                    pct   = abs_ / prev * 100

            result["price"]      = price
            result["change"]     = abs_ or 0.0
            result["change_pct"] = pct  or 0.0
        else:
            price, prev = _yf_spot(ticker)
            if price is None:
                result["error"] = "sem dados"
                return result

            if gram_convert:
                price = price / TROY_OUNCE_TO_GRAM
                if prev:
                    prev = prev / TROY_OUNCE_TO_GRAM

            change     = price - (prev or price)
            change_pct = change / (prev or price) * 100

            result.update(
                price=price,
                prev_close=prev,
                change=change,
                change_pct=change_pct,
            )
    except Exception as exc:
        result["error"] = str(exc)

    return result


# ─── Dados históricos (gráficos) ──────────────────────────────

def get_history(
    asset: dict[str, Any],
    yf_period: str = "1mo",
    yf_interval: str = "1d",
) -> pd.DataFrame:
    """
    Retorna DataFrame OHLCV para o ativo no período solicitado.
    Converte para grama quando necessário e normaliza o índice de tempo.
    """
    ticker       = asset["ticker"]
    gram_convert = asset.get("gram_convert", False)

    try:
        df = yf.Ticker(ticker).history(period=yf_period, interval=yf_interval, timeout=15)
        if df.empty:
            return pd.DataFrame()

        # Remover timezone para facilitar serialização
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)

        if gram_convert:
            for col in ("Open", "High", "Low", "Close"):
                if col in df.columns:
                    df[col] = df[col] / TROY_OUNCE_TO_GRAM

        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df

    except Exception:
        return pd.DataFrame()


# ─── Indicadores técnicos ─────────────────────────────────────

def add_bollinger_bands(
    df: pd.DataFrame, window: int = 20, std_mult: float = 2.0
) -> pd.DataFrame:
    """
    Adiciona colunas BB_Upper, BB_Mid, BB_Lower ao DataFrame.
    Usa implementação nativa para evitar problemas de versão do pandas-ta.
    """
    if df.empty or len(df) < window:
        return df

    close = df["Close"]
    mid   = close.rolling(window).mean()
    std   = close.rolling(window).std()

    df = df.copy()
    df["BB_Mid"]   = mid
    df["BB_Upper"] = mid + std_mult * std
    df["BB_Lower"] = mid - std_mult * std
    return df


def add_rsi(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """
    Adiciona coluna RSI ao DataFrame (Wilder's smoothing).
    """
    if df.empty or len(df) < window + 1:
        return df

    df   = df.copy()
    close = df["Close"]
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    df["RSI"] = rsi
    return df


# ─── Formatação de preço ──────────────────────────────────────

def fmt_price(
    price: float | None,
    base_currency: str,
    display_brl: bool,
    fx_rate: float,
    gram_convert: bool = False,
) -> str:
    """
    Formata um preço para exibição.

    - Se display_brl e base_currency == 'USD': converte usando fx_rate
    - Se base_currency == 'BRL': exibe em BRL independente do toggle
    """
    if price is None:
        return "—"

    show_brl = display_brl or base_currency == "BRL"
    value    = price * fx_rate if (display_brl and base_currency == "USD") else price

    if base_currency == "BRL" or show_brl:
        symbol = "R$"
    else:
        symbol = "US$"

    if value >= 1_000_000:
        return f"{symbol} {value/1_000_000:.2f}M"
    if value >= 1_000:
        return f"{symbol} {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if value >= 1:
        return f"{symbol} {value:.4f}".rstrip("0").rstrip(".")
    return f"{symbol} {value:.6f}".rstrip("0").rstrip(".")
