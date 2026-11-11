# Portfolio Analyzer

A Flask app that sizes a stock portfolio with mean-variance optimization, using real end-of-day prices only.

## Data

Daily closes come from [Massive](https://massive.com) (`/v2/aggs`), about two years (725 calendar days) per ticker.
Bars are cached on disk and refetched at most once per trading day, and a rate limiter keeps the app inside the
Stocks Basic limit of 5 calls a minute. The risk-free rate is the latest 3-month Treasury yield from Massive.
A ticker without real history is excluded and named in the response, never estimated.

## Model

- Anchor: `rf + beta_adj x 5.5%`, where `beta_adj = 0.67 x OLS beta vs SPY + 0.33` (Blume). Listings with under 180 days of overlap use a sector prior beta.
- Momentum alpha: `0.05 x residual vol x z`, with z the 12-1 month return z-scored (clipped to +/-3) across every cached watchlist ticker. It switches off below 10 names, and the 0.05 is halved when SPY's own 12-1 return is negative.
- Optional price targets you enter add `0.25 x ((target / price - 1 - 15%) - anchor)`.
- Covariance is Ledoit-Wolf (2004) shrinkage toward constant correlation. Weights are long-only, between 0.5% and `max(40%, 1.5 / n)`.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in MASSIVE_API_KEY
python app.py             # http://localhost:8080 (PORT overrides)
```

Environment variables:

| Name | Meaning |
| --- | --- |
| `MASSIVE_API_KEY` | Required. Massive key, Stocks Basic or higher. |
| `MASSIVE_CALLS_PER_MIN` | Default 5. Set 0 on Starter or above to turn the rate limiter off. |
| `CACHE_DIR` | Where price bars are cached. Point it at a Railway volume so the cache survives deploys. |
| `ANTHROPIC_API_KEY` | Optional. Lets Claude propose smart-suggestion candidates, which are then scored on real prices. |

## Endpoints

- `POST /api/analyze` with `{tickers, capital, biweekly, mode, targets?}`. `mode` is `sharpe`, `minvol` or `riskparity`, and `targets` is an optional `{TICKER: price}`. Returns positions with the return breakdown, portfolio and equal-weight stats, frontier, Monte Carlo paths, scenarios and the covariance matrix. Answers 503 with `retry_after` while price history is still loading.
- `POST /api/recalculate` reruns the optimizer and scenarios with your own return estimates, reusing the covariance matrix and betas from `/api/analyze`.
- `POST /api/smart` with `{tickers, weights, user_prompt?}` suggests additions and scores each one on real data.
- `GET /api/market-data` gives last close and daily change for the banner.
- `GET /api/debug` shows the key status, rate limiter usage, momentum universe size and what is in the cache.

Not financial advice.
