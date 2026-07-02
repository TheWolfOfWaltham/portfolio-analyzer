"""
portfolio_engine.py
Quant logic: MVO, Monte Carlo, frontier, scenarios, smart suggestions.
Data: yfinance (primary) → Alpaca (secondary) → TICKER_PRIORS (last resort).
Returns use CAPM (Rf + β × ERP) for optimizer validity.
Volatility is always computed from live price bars when available.
"""
import os, requests, datetime
import numpy as np
from scipy.optimize import minimize
from dotenv import load_dotenv

load_dotenv()

ALPACA_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE   = "https://data.alpaca.markets"

FMP_KEY      = os.environ.get("FMP_API_KEY", "")
FMP_BASE     = "https://financialmodelingprep.com/api/v4"
FINNHUB_KEY  = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_BASE = "https://finnhub.io/api/v1"

RF  = 0.045   # risk-free rate (approx Fed funds)
ERP = 0.055   # equity risk premium (historical avg)
CAPM_WEIGHT     = 0.30  # CAPM — stability anchor
MOMENTUM_WEIGHT = 0.40  # dampened trailing momentum (academic: Jegadeesh-Titman)
ANALYST_WEIGHT  = 0.30  # Finnhub analyst consensus

# Fallback priors — vol and price used when live data unavailable
TICKER_PRIORS = {
    "GLW":  (0.55, 0.70, 206),  "SNDK": (0.80, 1.80, 2150),
    "NBIS": (0.60, 0.85, 250),  "GEV":  (0.45, 0.42, 620),
    "MRVL": (0.65, 0.65, 310),  "COHR": (0.55, 0.75, 390),
    "ANET": (0.38, 0.45, 162),  "VST":  (0.25, 0.38, 163),
    "NOW":  (-0.05,0.40, 93),   "CEG":  (0.20, 0.35, 270),
    "MU":   (0.50, 0.70, 140),  "AVGO": (0.40, 0.45, 185),
    "WMT":  (0.08, 0.18, 97),   "JPM":  (0.12, 0.22, 260),
    "JNJ":  (0.06, 0.16, 155),  "PG":   (0.07, 0.14, 172),
    "SOFI": (0.10, 0.55, 17),   "CRWD": (0.30, 0.50, 380),
    "NEE":  (0.10, 0.20, 68),   "LITE": (0.48, 0.72, 95),
    "ETR":  (0.12, 0.22, 82),   "AMD":  (0.55, 0.65, 180),
}
DEFAULT_PRIOR = (0.15, 0.45, 100)


def _fetch_analyst_targets(tickers: list) -> dict:
    """
    Fetch analyst consensus price targets from Finnhub (free tier, 60 calls/min).
    Returns {ticker: mean_target_price}.
    Falls back to FMP if Finnhub key not set (legacy accounts only).
    """
    from concurrent.futures import ThreadPoolExecutor

    finnhub_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    fmp_key     = os.environ.get("FMP_API_KEY", "").strip()

    if not finnhub_key and not fmp_key:
        print("[analyst] No FINNHUB_API_KEY or FMP_API_KEY — skipping targets")
        return {}

    def fetch_finnhub(t):
        try:
            r = requests.get(
                f"{FINNHUB_BASE}/stock/price-target",
                params={"symbol": t, "token": finnhub_key},
                timeout=8,
            )
            if r.status_code == 200:
                d = r.json()
                target = d.get("targetMean") or d.get("targetMedian")
                if target and float(target) > 0:
                    print(f"[Finnhub] {t}: mean=${float(target):.2f} "
                          f"(hi=${d.get('targetHigh',0):.0f} "
                          f"lo=${d.get('targetLow',0):.0f})")
                    return t, float(target)
            else:
                print(f"[Finnhub] {t}: HTTP {r.status_code}")
        except Exception as ex:
            print(f"[Finnhub] {t} error: {ex}")
        return t, None

    result = {}
    use_key = finnhub_key  # prefer Finnhub
    fetch_fn = fetch_finnhub

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(fetch_fn, t) for t in tickers]
        for f in futures:
            ticker, target = f.result()
            if target:
                result[ticker] = target

    print(f"[analyst] Got targets for {len(result)}/{len(tickers)} tickers")
    return result


def _simulated_returns(ticker: str, n: int = 252) -> np.ndarray:
    """Simulated returns from prior vol — last-resort fallback only."""
    _, ann_vol, _ = TICKER_PRIORS.get(ticker.upper(), DEFAULT_PRIOR)
    daily_sig = ann_vol / np.sqrt(252)
    np.random.seed(abs(hash(ticker)) % (2**31))
    return np.random.normal(0, daily_sig, n)


def _compute_beta(stock_ret: np.ndarray, spy_ret: np.ndarray) -> float:
    """OLS beta: Cov(stock, spy) / Var(spy). Falls back to 1.0."""
    n = min(len(stock_ret), len(spy_ret))
    if n < 30:
        return 1.0
    x, y = spy_ret[:n], stock_ret[:n]
    var_x = float(np.var(x))
    return float(np.cov(y, x)[0, 1] / var_x) if var_x > 1e-12 else 1.0


# ── Data fetchers ─────────────────────────────────────────────────────────────

def _fetch_yfinance(tickers: list, period_days: int = 365) -> dict:
    """Primary: yfinance. Returns {ticker: {'closes': [...], 'source': str}}."""
    try:
        import yfinance as yf
        period = f"{period_days}d"
        all_t  = list(dict.fromkeys(tickers))  # deduplicate, preserve order
        raw = (yf.download(all_t[0], period=period, auto_adjust=True, progress=False)[["Close"]]
               .rename(columns={"Close": all_t[0]})
               if len(all_t) == 1
               else yf.download(" ".join(all_t), period=period, auto_adjust=True,
                                 progress=False, threads=True)["Close"])
        result = {}
        for t in all_t:
            col = t if t in raw.columns else None
            if col is None:
                continue
            series = raw[col].dropna()
            if len(series) < 30:
                continue
            result[t] = {"closes": series.values.tolist(), "source": "yfinance"}
            print(f"[yf] {t}: {len(series)} bars, last=${series.iloc[-1]:.2f}")
        return result
    except ImportError:
        print("[yf] not installed")
        return {}
    except Exception as e:
        print(f"[yf] failed: {e}")
        return {}


def _fetch_alpaca(tickers: list, days: int = 365) -> tuple:
    """
    Secondary: Alpaca. Tries adjustment=raw then no adjustment.
    Returns (bars_dict, status_str).
    """
    if not ALPACA_KEY or not ALPACA_SECRET:
        return {}, "NO_KEYS"
    end   = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    headers = {
        "APCA-API-KEY-ID":     ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
        "Accept":              "application/json",
    }
    base_params = {
        "symbols":   ",".join(tickers),
        "timeframe": "1Day",
        "start":     start.isoformat(),
        "end":       end.isoformat(),
        "limit":     10000,
        "sort":      "asc",
    }
    last_err = "UNKNOWN"
    for adj in ["raw", None]:
        params = {**base_params}
        if adj:
            params["adjustment"] = adj
        try:
            r = requests.get(f"{ALPACA_BASE}/v2/stocks/bars",
                             headers=headers, params=params, timeout=20)
            status = f"HTTP_{r.status_code}_adj={adj or 'none'}"
            if r.status_code == 200:
                raw_bars = r.json().get("bars", {})
                result   = {}
                for raw_t, bars in raw_bars.items():
                    matched = next((t for t in tickers
                                    if t.replace("/","") == raw_t.replace("/","")), None)
                    if matched and bars and len(bars) >= 30:
                        result[matched] = {
                            "closes": [b["c"] for b in bars],
                            "source": f"alpaca (adj={adj or 'none'})"
                        }
                        print(f"[alpaca] {matched}: {len(bars)} bars loaded")
                if result:
                    return result, f"OK_{status}"
                last_err = f"OK_{status}_but_empty"
            else:
                last_err = f"FAIL_{status}:{r.text[:150]}"
                print(f"[alpaca] {last_err}")
        except Exception as ex:
            last_err = f"EXCEPTION:{ex}"
    return {}, last_err


# ── Main data pipeline ────────────────────────────────────────────────────────

def fetch_returns(tickers: list, period_days: int = 365) -> tuple:
    """
    Fetch live data and compute CAPM-based expected returns + realized vol.

    Returns:
      data_dict: {ticker: {returns, ann_ret (CAPM), ann_vol (realized),
                            beta, trailing_ret, price, sharpe, data_source}}
      is_live:   True if at least one ticker sourced from live API
    """
    print(f"\n[fetch_returns] tickers={tickers}")
    result  = {}
    is_live = False

    # Always include SPY for beta regression
    all_needed = list(dict.fromkeys(tickers + ["SPY"]))

    # Step 1: yfinance for everything incl. SPY
    yf_data = _fetch_yfinance(all_needed, period_days)

    # Step 2: Alpaca for anything yfinance missed
    missing = [t for t in all_needed if t not in yf_data]
    alpaca_data, alpaca_status = _fetch_alpaca(missing, days=period_days) if missing else ({}, "skipped")
    print(f"[alpaca] status={alpaca_status}")

    # Step 3: FMP analyst price targets (parallel, non-blocking)
    fmp_targets = _fetch_analyst_targets(tickers)

    # Merge SPY returns for beta
    spy_entry = yf_data.get("SPY") or alpaca_data.get("SPY")
    spy_ret   = np.array([])
    if spy_entry and len(spy_entry["closes"]) >= 30:
        sc      = np.array(spy_entry["closes"], dtype=float)
        spy_ret = np.diff(sc) / sc[:-1]
        print(f"[fetch_returns] SPY: {len(spy_ret)} return days for beta")
    else:
        print("[fetch_returns] ⚠️ SPY unavailable — beta defaults to 1.0")

    for t in tickers:
        entry = yf_data.get(t) or alpaca_data.get(t)
        if entry and len(entry["closes"]) >= 30:
            closes    = np.array(entry["closes"], dtype=float)
            daily_ret = np.diff(closes) / closes[:-1]
            ann_vol   = float(daily_ret.std() * np.sqrt(252))
            trail_ret = float((1 + daily_ret.mean()) ** 252 - 1)
            price     = float(closes[-1])
            source    = entry["source"]
            is_live   = True
        else:
            # Last-resort: prior vol, simulated returns
            _, ann_vol, price = TICKER_PRIORS.get(t.upper(), DEFAULT_PRIOR)
            daily_ret = _simulated_returns(t)
            trail_ret = 0.0
            source    = "⚠️ HARDCODED PRIOR — live data unavailable"
            print(f"[fetch_returns] ⚠️ {t}: using prior vol={ann_vol:.0%}")

        # CAPM expected return (drives optimizer, Sharpe, risk math)
        n_bars = len(daily_ret)
        if n_bars >= MIN_BARS_FOR_BETA and len(spy_ret) >= 30:
            # Enough history — compute OLS beta
            beta = _compute_beta(daily_ret, spy_ret)
        else:
            # Short history (spinoff / new listing) — use sector proxy
            beta = TICKER_BETA_PRIORS.get(t.upper(), 1.2)
            print(f"[fetch_returns] {t}: only {n_bars} bars — "
                  f"using sector proxy β={beta} (OLS unreliable on short history)")
        capm_ret = RF + beta * ERP

        # ── Three-way blended return ──────────────────────────────────────────
        # 30% CAPM + 40% dampened momentum + 30% analyst consensus
        # Academic basis: Black-Litterman (1990), Jegadeesh-Titman momentum (1993)

        # Dampened trailing momentum — sqrt(|r|) compresses extreme values
        # GLW +42% → 65%, CRWD +72% → 85%, SNDK +3800% → capped at 100%
        # Cap at 100% so even extreme momentum stocks don't dominate
        if abs(trail_ret) > 0.001:
            damped_mom = float(np.sign(trail_ret) * np.sqrt(abs(trail_ret)))
            damped_mom = float(np.clip(damped_mom, -1.0, 1.0))
        else:
            damped_mom = trail_ret

        analyst_target  = fmp_targets.get(t)
        if analyst_target and price > 0:
            analyst_implied = (analyst_target / price) - 1
            blended_ret     = (CAPM_WEIGHT * capm_ret
                               + MOMENTUM_WEIGHT * damped_mom
                               + ANALYST_WEIGHT * analyst_implied)
            return_source   = "30% CAPM / 40% momentum / 30% analyst"
        else:
            analyst_implied = None
            # Without analyst: 43% CAPM + 57% dampened momentum (renormalized)
            w_capm = CAPM_WEIGHT / (CAPM_WEIGHT + MOMENTUM_WEIGHT)
            w_mom  = MOMENTUM_WEIGHT / (CAPM_WEIGHT + MOMENTUM_WEIGHT)
            blended_ret     = w_capm * capm_ret + w_mom * damped_mom
            return_source   = "43% CAPM / 57% momentum (no analyst data)"

        result[t] = {
            "returns":          daily_ret.tolist(),
            "ann_ret":          round(blended_ret, 4),     # blended — drives optimizer
            "ann_vol":          round(ann_vol, 4),
            "beta":             round(beta, 3),
            "capm_return":      round(capm_ret * 100, 2),
            "analyst_target":   round(analyst_target, 2) if analyst_target else None,
            "analyst_implied":  round(analyst_implied * 100, 1) if analyst_implied is not None else None,
            "blended_return":   round(blended_ret * 100, 2),
            "trailing_ret":     round(trail_ret * 100, 1),
            "return_source":    return_source,
            "price":            round(price, 2),
            "sharpe":           round((blended_ret - RF) / ann_vol, 3) if ann_vol > 0 else 0,
            "data_source":      source,
            "n_days":           len(daily_ret),
        }
        print(f"[fetch_returns] {t}: β={beta:.2f} capm={capm_ret*100:.1f}% "
              f"analyst={f'{analyst_implied*100:.0f}%' if analyst_implied else 'N/A'} "
              f"blended={blended_ret*100:.1f}% vol={ann_vol*100:.1f}%")

    live_count = sum(1 for v in result.values() if "PRIOR" not in v.get("data_source",""))
    print(f"[fetch_returns] {live_count}/{len(tickers)} tickers live\n")
    return result, is_live


# ── Portfolio math ────────────────────────────────────────────────────────────

def build_cov(tickers: list, data: dict) -> np.ndarray:
    min_len = min(len(data[t]["returns"]) for t in tickers)
    M = np.array([np.array(data[t]["returns"])[:min_len] for t in tickers])
    return np.cov(M) * 252


def portfolio_stats(weights, mu, cov, rf: float = RF):
    w        = np.array(weights)
    port_ret = float(w @ mu)
    port_vol = float(np.sqrt(w @ cov @ w))
    sharpe   = (port_ret - rf) / port_vol if port_vol > 0 else 0.0
    return port_ret, port_vol, sharpe


def optimize(mu, cov, mode: str = "sharpe", rf: float = RF) -> list:
    mu  = np.array(mu)
    n   = len(mu)
    w0  = np.ones(n) / n
    bnd = [(0.005, 1.0)] * n
    eq  = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    if mode == "sharpe":
        def obj(w):
            r, v, _ = portfolio_stats(w, mu, cov, rf)
            return -(r - rf) / v if v > 0 else 1e6
    elif mode == "minvol":
        def obj(w): return float(np.sqrt(w @ cov @ w))
    else:
        def obj(w):
            v   = float(np.sqrt(w @ cov @ w))
            mrc = (cov @ w) / v
            rc  = w * mrc
            return float(np.sum((rc - v / n) ** 2))
    res = minimize(obj, w0, method="SLSQP", bounds=bnd, constraints=eq,
                   options={"ftol": 1e-10, "maxiter": 2000})
    w = res.x / res.x.sum()
    return w.tolist()


def efficient_frontier(mu, cov, n_points: int = 40) -> list:
    mu  = np.array(mu)
    n   = len(mu)
    bnd = [(0.005, 1.0)] * n
    pts = []
    for target in np.linspace(mu.min(), mu.max(), n_points):
        c = [{"type": "eq", "fun": lambda w: np.sum(w) - 1},
             {"type": "eq", "fun": lambda w, t=target: float(w @ mu) - t}]
        try:
            res = minimize(lambda w: float(np.sqrt(w @ cov @ w)),
                           np.ones(n)/n, method="SLSQP", bounds=bnd, constraints=c,
                           options={"ftol": 1e-9, "maxiter": 500})
            if res.success:
                pts.append({"vol": round(float(np.sqrt(res.x @ cov @ res.x))*100, 2),
                             "ret": round(float(res.x @ mu)*100, 2)})
        except Exception:
            pass
    return pts


def monte_carlo(port_ret: float, port_vol: float, capital: float,
                n_paths: int = 200, years: int = 3) -> list:
    dt    = 1 / 252
    mu_g  = port_ret - 0.5 * port_vol ** 2
    sig   = port_vol * np.sqrt(dt)
    steps = int(252 * years)
    np.random.seed(42)
    Z     = np.random.standard_normal((n_paths, steps))
    monthly = []
    for i in range(n_paths):
        v, path = capital, [capital]
        for j in range(steps):
            v *= np.exp(mu_g * dt + sig * Z[i, j])
            path.append(round(v, 2))
        monthly.append([path[min(k * 21, steps)] for k in range(37)])
    return monthly


def risk_contributions(weights, cov) -> list:
    w   = np.array(weights)
    vol = float(np.sqrt(w @ cov @ w))
    mrc = (cov @ w) / vol
    rc  = w * mrc
    return (rc / rc.sum()).tolist()


# ── Beta-driven scenario projections (Option B) ───────────────────────────────

def _fv_annuity(pmt: float, r_ann: float, n_per_yr: int, years: int) -> float:
    if abs(r_ann) < 1e-6:
        return pmt * n_per_yr * years
    r = r_ann / n_per_yr
    n = n_per_yr * years
    return pmt * ((1 + r) ** n - 1) / r


def scenario_projections(tickers, weights, initial_capital, biweekly_contrib, data) -> dict:
    """
    Beta-driven scenario analysis (Option B).
    Each stock's annual return = RF + beta × (market_return - RF).
    Market scenarios: Bull SPY+22%, Base SPY+9%, Bear SPY-15%.
    """
    results = {}
    for key, scen in MARKET_SCENARIOS.items():
        spy_ret = scen["spy"]
        rows, tots = [], {k: 0.0 for k in
            ["yr1","yr2","yr3","yr1_init","yr2_init","yr3_init",
             "yr1_contrib","yr2_contrib","yr3_contrib"]}

        for t, w in zip(tickers, weights):
            beta  = data[t].get("beta", 1.0)
            ann_r = RF + beta * (spy_ret - RF)   # CAPM stock return under this scenario
            alloc = w * initial_capital
            pmt   = biweekly_contrib * w

            vi  = [alloc * (1 + ann_r) ** yr for yr in [1, 2, 3]]
            fv  = [_fv_annuity(pmt, ann_r, 26, yr) for yr in [1, 2, 3]]
            yr3_val = vi[2] + fv[2]

            total_biweekly_3yr = pmt * 26 * 3
            total_invested     = alloc + total_biweekly_3yr
            contrib_adj_pct    = round((yr3_val - total_invested) / total_invested * 100, 1) \
                                 if total_invested > 0 else 0
            initial_only_pct   = round((yr3_val - alloc) / alloc * 100, 1) if alloc > 0 else 0

            rows.append({
                "ticker": t, "weight": round(w*100,1), "init": round(alloc,0),
                "biweekly": round(pmt,2), "beta": round(beta,2),
                "ann_r": round(ann_r*100,1),
                "yr1": round(vi[0]+fv[0],0), "yr2": round(vi[1]+fv[1],0),
                "yr3": round(yr3_val,0),
                "contrib_adj_pct": contrib_adj_pct,
                "initial_only_pct": initial_only_pct,
                "total_return_pct": contrib_adj_pct,
            })
            for i, yr in enumerate(["yr1","yr2","yr3"]):
                tots[yr]             += vi[i]+fv[i]
                tots[f"{yr}_init"]   += vi[i]
                tots[f"{yr}_contrib"]+= fv[i]

        for k in tots:
            tots[k] = round(tots[k], 0)
        total_invested_port = initial_capital + biweekly_contrib * 26 * 3
        results[key] = {
            "label": scen["label"], "color": scen["color"], "bg": scen["bg"],
            "spy_scenario": f"S&P 500 {'+' if spy_ret>=0 else ''}{spy_ret*100:.0f}%/yr",
            "rows": rows, "totals": tots,
            "total_return_pct": round((tots["yr3"]-initial_capital)/initial_capital*100,1),
            "contrib_adj_pct": round((tots["yr3"]-total_invested_port)/total_invested_port*100,1),
        }
    return results


# ── Smart suggestions ─────────────────────────────────────────────────────────

def marginal_impact(existing_tickers, existing_weights, existing_data,
                    candidate_ticker, candidate_data, add_pct=0.05, rf=RF):
    try:
        w_curr   = np.array(existing_weights)
        mu_curr  = np.array([existing_data[t]['ann_ret'] for t in existing_tickers])
        cov_curr = build_cov(existing_tickers, existing_data)
        r0, v0, s0 = portfolio_stats(w_curr, mu_curr, cov_curr, rf)

        new_tickers = existing_tickers + [candidate_ticker]
        new_weights = np.append(w_curr * (1 - add_pct), add_pct)
        new_weights /= new_weights.sum()
        all_data    = {**existing_data, candidate_ticker: candidate_data}
        mu_new  = np.array([all_data[t]['ann_ret'] for t in new_tickers])
        cov_new = build_cov(new_tickers, all_data)
        r1, v1, s1 = portfolio_stats(new_weights, mu_new, cov_new, rf)

        min_len = min(len(all_data[t]['returns']) for t in new_tickers)
        M    = np.array([np.array(all_data[t]['returns'])[:min_len] for t in new_tickers])
        corr = np.corrcoef(M)
        corr_to_book = float(np.average(corr[-1, :-1], weights=w_curr))

        return {
            'sharpe_delta': round(s1 - s0, 3),
            'vol_delta':    round((v1 - v0) * 100, 2),
            'ret_delta':    round((r1 - r0) * 100, 2),
            'corr_to_book': round(corr_to_book, 3),
            'new_sharpe':   round(s1, 3),
            'new_vol':      round(v1 * 100, 1),
            'new_ret':      round(r1 * 100, 1),
        }
    except Exception:
        return {'sharpe_delta':0,'vol_delta':0,'ret_delta':0,
                'corr_to_book':0,'new_sharpe':0,'new_vol':0,'new_ret':0}


def smart_suggestions_v2(tickers, weights, data):
    existing = {t.upper() for t in tickers}
    all_candidates = []
    for cluster in ['AI_OPTICAL','AI_POWER','AI_NETWORK','AI_COMPUTE',
                    'ENERGY_TRANS','BLUECHIP','GROWTH_DIV']:
        for (t, desc, sec, ret, vol) in SMART_DB[cluster]:
            if t not in existing:
                all_candidates.append({
                    'ticker': t, 'desc': desc, 'sector': sec,
                    'exp_return': ret, 'ann_vol': vol,
                    'type': 'complement' if cluster not in ['BLUECHIP','GROWTH_DIV'] else 'diversifier'
                })

    results = []
    for cand in all_candidates:
        t = cand['ticker']
        _, prior_vol, prior_price = TICKER_PRIORS.get(t, DEFAULT_PRIOR)
        capm_r = RF + 1.0 * ERP   # default beta=1 for DB candidates
        cand_data = {
            'returns':  _simulated_returns(t).tolist(),
            'ann_ret':  capm_r,
            'ann_vol':  prior_vol,
            'beta':     1.0,
            'price':    prior_price,
            'sharpe':   round((capm_r - RF) / prior_vol, 3),
        }
        impact = (marginal_impact(tickers, weights, data, t, cand_data)
                  if data and all(k in data for k in tickers)
                  else {'sharpe_delta': round((capm_r-RF)/prior_vol*0.05,3),
                        'vol_delta': 0.0, 'ret_delta': round(capm_r*0.05*100,2),
                        'corr_to_book': 0.3 if cand['type']=='complement' else 0.1,
                        'new_sharpe':0,'new_vol':0,'new_ret':0})
        results.append({**cand, **impact})

    sharpe_enhancers = sorted([r for r in results if r['type']=='complement'],
                               key=lambda x: -x['sharpe_delta'])[:5]
    vol_reducers     = sorted([r for r in results if r['type']=='diversifier'],
                               key=lambda x: (x['corr_to_book'], x['ann_vol']))[:5]

    ai_w  = sum(w for t,w in zip(tickers,weights)
                if any(t.upper()==db_t for cl in ['AI_COMPUTE','AI_OPTICAL','AI_NETWORK']
                       for db_t,*_ in SMART_DB[cl]))
    pwr_w = sum(w for t,w in zip(tickers,weights)
                if any(t.upper()==db_t for db_t,*_ in SMART_DB['AI_POWER']))

    warnings = []
    if ai_w > 0.60:
        warnings.append(f'High AI concentration ({ai_w*100:.0f}%). A risk-off AI drawdown hits the majority simultaneously.')
    if pwr_w < 0.10:
        warnings.append('Low power & energy exposure. AI data-center electricity is a structural multi-year tailwind.')
    if not any(t.upper() in {db_t for db_t,*_ in SMART_DB['BLUECHIP']} for t in tickers):
        warnings.append('No blue-chip defensive positions. Consider 5-10% WMT/JPM/JNJ to reduce max drawdown depth.')

    return {'sharpe_enhancers':sharpe_enhancers, 'vol_reducers':vol_reducers,
            'warnings':warnings,
            'exposure':{'ai':round(ai_w*100,1),'power':round(pwr_w*100,1),
                        'defensive':0,'other':round(max(0,1-ai_w-pwr_w)*100,1)}}
