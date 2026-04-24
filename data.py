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

        # Remover timezone para facilitar serialização (converter para horário de Brasília)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("America/Sao_Paulo").tz_localize(None)

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


# ─── Simulação de Dividendos ──────────────────────────────────

# Tipos que NÃO suportam dividendos
DIVIDEND_EXCLUDED_TYPES = {"crypto", "commodity", "index"}


def get_dividend_simulation(
    asset: dict[str, Any],
    amount: float,
    display_brl: bool,
    fx_rate: float,
) -> dict[str, Any]:
    """
    Simula um investimento em um ativo pagador de dividendos.

    Retorna:
      supported, price, units, actual_cost, remainder,
      dividends_hist (list[{date, value}]), projected_annual,
      dividend_yield, freq_label, error
    """
    result: dict[str, Any] = {
        "supported":        False,
        "price":            None,
        "units":            0,
        "actual_cost":      0.0,
        "remainder":        amount,
        "dividends_hist":   [],
        "projected_annual": 0.0,
        "dividend_yield":   0.0,
        "freq_label":       "",
        "error":            None,
    }

    if asset.get("type", "stock") in DIVIDEND_EXCLUDED_TYPES:
        return result

    result["supported"] = True
    ticker        = asset["ticker"]
    base_currency = asset.get("base_currency", "USD")
    gram_convert  = asset.get("gram_convert", False)

    try:
        yf_obj = yf.Ticker(ticker)

        # ── Preço atual ──────────────────────────────────────
        info  = yf_obj.fast_info
        price = float(info.last_price or info.previous_close or 0)
        if gram_convert and price > 0:
            price /= TROY_OUNCE_TO_GRAM

        if price <= 0:
            result["error"] = "Preço indisponível"
            return result

        price_display = price * fx_rate if (display_brl and base_currency == "USD") else price

        units       = int(amount // price_display)
        actual_cost = units * price_display
        remainder   = amount - actual_cost

        result.update(price=price_display, units=units,
                      actual_cost=actual_cost, remainder=remainder)

        if units == 0:
            result["error"] = "Valor insuficiente para comprar 1 cota"
            return result

        # ── Dividendos históricos (últimos 12 meses) ─────────
        divs = yf_obj.dividends
        # yfinance pode retornar DataFrame ou Series dependendo da versão
        if isinstance(divs, pd.DataFrame):
            if "Dividends" in divs.columns:
                divs = divs["Dividends"]
            elif divs.columns.size > 0:
                divs = divs.iloc[:, 0]
            else:
                divs = pd.Series(dtype=float)
        if divs.empty:
            result["error"] = "Sem histórico de dividendos"
            return result

        if divs.index.tz is not None:
            divs.index = divs.index.tz_convert("America/Sao_Paulo").tz_localize(None)

        cutoff   = pd.Timestamp.now() - pd.DateOffset(months=12)
        divs_12m = divs[divs.index >= cutoff]

        if divs_12m.empty:
            result["error"] = "Sem dividendos nos últimos 12 meses"
            return result

        div_fx           = fx_rate if (display_brl and base_currency == "USD") else 1.0
        divs_12m_display = divs_12m * div_fx

        result["dividends_hist"] = [
            {"date": str(d.date()), "value": float(v)}
            for d, v in divs_12m_display.items()
        ]

        n_payments = len(divs_12m)
        result["freq_label"] = (
            "Mensal"     if n_payments >= 10 else
            "Trimestral" if n_payments >= 4  else
            "Semestral"  if n_payments >= 2  else
            "Anual"
        )

        avg_div          = float(divs_12m_display.mean())
        projected_annual = avg_div * n_payments * units

        result["projected_annual"] = projected_annual
        result["dividend_yield"]   = (
            avg_div * n_payments / price_display * 100
            if price_display > 0 else 0.0
        )

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ─── Google News RSS ──────────────────────────────────────────

def _fetch_google_news(query: str, max_items: int = 6) -> list[dict]:
    """Busca notícias no Google News RSS pelo nome do ativo."""
    import urllib.parse
    import xml.etree.ElementTree as ET
    import re as _re

    q   = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt"
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root  = ET.fromstring(resp.content)
        items = root.findall("./channel/item")
        parsed = []
        for item in items[:max_items]:
            title  = (item.findtext("title") or "").strip()
            link   = (item.findtext("link")  or "").strip()
            pub    = (item.findtext("pubDate") or "")[:16]
            source = (item.findtext("source") or "").strip()
            desc   = _re.sub(r"<[^>]+>", "", item.findtext("description") or "")[:220].strip()
            if title:
                parsed.append({
                    "title":   title,
                    "summary": desc,
                    "pubDate": pub,
                    "url":     link,
                    "source":  source,
                })
        return parsed
    except Exception:
        return []


# ─── Comm Lens – informações detalhadas do ativo ─────────────

def get_asset_lens(asset: dict[str, Any]) -> dict[str, Any]:
    """
    Busca informações detalhadas e notícias recentes de um ativo via yfinance.
    Retorna dict com 'info' (métricas) e 'news' (lista de notícias).
    """
    import re as _re

    ticker = asset["ticker"]
    result: dict[str, Any] = {"info": {}, "news": [], "error": None}

    try:
        obj  = yf.Ticker(ticker)
        info = obj.info or {}

        keep = [
            "longName", "sector", "industry", "marketCap",
            "trailingPE", "forwardPE", "priceToBook",
            "dividendYield", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
            "beta", "volume", "averageVolume",
            "longBusinessSummary", "currency", "exchange",
        ]
        result["info"] = {k: info[k] for k in keep if k in info and info[k] is not None}

        # ── Google News RSS (fonte principal) ────────────────
        parsed = _fetch_google_news(asset.get("name", ticker))

        # ── Fallback: Yahoo Finance ───────────────────────────
        if not parsed:
            for n in (obj.news or [])[:5]:
                c = n.get("content", {}) if isinstance(n, dict) else {}
                title   = c.get("title", "")
                summary = _re.sub(r"<[^>]+>", "", c.get("summary") or c.get("description") or "")[:220]
                pub     = (c.get("pubDate") or "")[:10]
                url     = (
                    (c.get("canonicalUrl")    or {}).get("url") or
                    (c.get("clickThroughUrl") or {}).get("url") or ""
                )
                if title:
                    parsed.append({"title": title, "summary": summary, "pubDate": pub, "url": url})

        result["news"] = parsed

    except Exception as exc:
        result["error"] = str(exc)

    return result
