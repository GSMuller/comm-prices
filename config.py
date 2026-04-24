# ──────────────────────────────────────────────────────────────
# config.py  –  Definições de ativos e constantes globais
# ──────────────────────────────────────────────────────────────

TROY_OUNCE_TO_GRAM = 31.1034768   # 1 oz troy = 31.10 g

# Ativos padrão carregados na primeira execução
DEFAULT_ASSETS = [
    {
        "id": "bitcoin",
        "name": "Bitcoin",
        "ticker": "BTC-USD",
        "type": "crypto",
        "icon": "₿",
        "base_currency": "USD",   # moeda nativa do ticker
        "gram_convert": False,
        "coingecko_id": "bitcoin",
    },
    {
        "id": "ethereum",
        "name": "Ethereum",
        "ticker": "ETH-USD",
        "type": "crypto",
        "icon": "Ξ",
        "base_currency": "USD",
        "gram_convert": False,
        "coingecko_id": "ethereum",
    },
    {
        "id": "gold",
        "name": "Ouro",
        "ticker": "GC=F",
        "type": "commodity",
        "icon": "Au",
        "base_currency": "USD",
        "gram_convert": True,     # preço original em oz, converte para grama
        "unit": "g",
        "coingecko_id": None,
    },
    {
        "id": "silver",
        "name": "Prata",
        "ticker": "SI=F",
        "type": "commodity",
        "icon": "Ag",
        "base_currency": "USD",
        "gram_convert": True,
        "unit": "g",
        "coingecko_id": None,
    },
    {
        "id": "ibovespa",
        "name": "Ibovespa",
        "ticker": "^BVSP",
        "type": "index",
        "icon": "IBV",
        "base_currency": "BRL",   # já cotado em BRL
        "gram_convert": False,
        "coingecko_id": None,
    },
    {
        "id": "apple",
        "name": "Apple",
        "ticker": "AAPL",
        "type": "stock",
        "icon": "AAPL",
        "base_currency": "USD",
        "gram_convert": False,
        "coingecko_id": None,
    },
]

# Períodos disponíveis para os gráficos
PERIODS = {
    "1D":  {"yf_period": "1d",  "yf_interval": "5m"},
    "5D":  {"yf_period": "5d",  "yf_interval": "30m"},
    "1M":  {"yf_period": "1mo", "yf_interval": "1d"},
    "3M":  {"yf_period": "3mo", "yf_interval": "1d"},
    "6M":  {"yf_period": "6mo", "yf_interval": "1d"},
    "1A":  {"yf_period": "1y",  "yf_interval": "1wk"},
    "5A":  {"yf_period": "5y",  "yf_interval": "1mo"},
    "Max": {"yf_period": "max", "yf_interval": "1mo"},
}

# Tipos de ativo disponíveis para cadastro manual
ASSET_TYPES = ["stock", "crypto", "commodity", "index", "etf", "fii", "outro"]

# Ticker de câmbio USD ↔ BRL
FX_TICKER = "BRL=X"

# Fallback se o câmbio não carregar
FX_FALLBACK = 5.0

# Intervalo de atualização em milissegundos (5 minutos)
REFRESH_INTERVAL_MS = 300_000
