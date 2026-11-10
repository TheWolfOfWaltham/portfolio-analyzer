# Portfolio Analyzer — AI Infrastructure

A quantitative portfolio analysis web app built with Python Flask. Enter any tickers and your capital, and get institutional-grade risk analytics computed from Massive end-of-day price data.

## Features

- **Market data** from Massive daily bars, cached once per trading day. Tickers without real history are excluded, never estimated
- **Mean-Variance Optimization** — Max Sharpe, Min Volatility, Risk Parity modes
- **Efficient Frontier** — scatter plot of the optimal risk/return tradeoff curve
- **Monte Carlo Simulation** — 200 paths, 3-year horizon, with 5th/25th/median/75th/95th percentile bands
- **Correlation Matrix** — color-coded heatmap of pairwise return correlations
- **Sector Diversification** — doughnut chart with automatic sector grouping
- **Risk Contribution** — per-position percentage of total portfolio variance
- **3-Year Scenario Analysis** — Bull/Base/Bear projections including biweekly DCA contribution compounding via annuity FV formula
- **Smart Suggestions** — AI analyses your sector concentration and recommends complementary AI-infrastructure plays and uncorrelated blue-chip diversifiers

## Setup

```bash
git clone https://github.com/yourusername/portfolio-analyzer
cd portfolio-analyzer
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` in your browser.

## Project Structure

```
portfolio_app/
├── app.py                  # Flask app factory
├── portfolio_engine.py     # All quant logic (MVO, Monte Carlo, scenarios, smart DB)
├── requirements.txt
├── routes/
│   ├── main.py             # Serves index.html
│   └── api.py              # /api/analyze and /api/smart endpoints
└── templates/
    └── index.html          # Full SPA — Chart.js, vanilla JS, no framework needed
```

## API Reference

### `POST /api/analyze`
```json
{
  "tickers": ["GLW", "SNDK", "NBIS"],
  "capital": 10000,
  "biweekly": 500,
  "mode": "sharpe"
}
```
Returns: positions, portfolio stats, frontier, Monte Carlo paths, correlation matrix, scenario projections.

### `POST /api/smart`
```json
{ "tickers": ["GLW", "SNDK"], "weights": [0.5, 0.5] }
```
Returns: complementary AI-infra picks, blue-chip diversifiers, concentration warnings.

## Customisation

All scenario return multipliers and the smart suggestions database live in `portfolio_engine.py`. Edit `SCENARIOS` and `SMART_DB` to update your forward views without touching any other file.

## Disclaimer

Not financial advice. For educational and analytical purposes only. Past performance does not guarantee future results.
