# comm-prices

Dashboard pra acompanhar preços de ativos em tempo real. Roda local, abre no browser.

![Index](Images/Index.png)

![Index](Images/Menu.png)

## O que tem

- Preços ao vivo: BTC, ETH, Ouro (g), Prata (g), Ibovespa, Apple
- Atualiza sozinho a cada 10 segundos
- Toggle USD / BRL — converte tudo incluindo os metais
- Adiciona e remove ativos na hora (qualquer ticker do Yahoo Finance)
- Gráficos com Plotly: linha ou candlestick, 8 períodos de 1D até Max
- Bandas de Bollinger e RSI ativáveis por switch
- Botão pra restaurar os ativos padrão caso apague sem querer

## Como rodar

```bash
git clone <repo>
cd comm-prices

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Abre em `http://localhost:8050`.

## Adicionando um ativo

Clica em **+ Ativo** e preenche:

- **Ticker**: o código do Yahoo Finance (ex: `MSFT`, `SOL-USD`, `^GSPC`, `GLD`)
- **Nome**: como vai aparecer no card
- **Moeda base**: USD ou BRL
- **CoinGecko ID**: só pra crypto, se quiser variação 24h mais precisa (ex: `solana`)
- O switch de oz troy é pra metais como ouro e prata — converte automaticamente pra grama

## Estrutura

```
app.py       — layout e callbacks do Dash
data.py      — busca de preços, histórico, Bollinger, RSI
config.py    — ativos padrão, períodos, constantes
assets/
  custom.css — estilo dark
```

## Fontes de dados

- **Crypto**: CoinGecko (gratuito, sem key) com fallback pro Yahoo Finance
- **Tudo mais**: Yahoo Finance via yfinance
- **Câmbio USD/BRL**: Yahoo Finance (`BRL=X`)

Os preços dependem da disponibilidade das APIs — fora do horário de mercado alguns ativos ficam estáticos.

## Dependências principais

```
dash, dash-bootstrap-components, plotly
yfinance, pandas, numpy, requests
```

## Próximas ideias

- Alertas de preço
- Seção de portfólio com valor total
- Exportar histórico em CSV
- Deploy no Railway/Render
