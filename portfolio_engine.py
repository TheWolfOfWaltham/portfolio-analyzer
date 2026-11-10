"""
portfolio_engine.py
Quant logic: MVO, Monte Carlo, frontier, scenarios, smart suggestions.
Data: Massive daily bars only (market_data.py). A ticker without real price history is excluded and
reported, never estimated or simulated.
Returns blend CAPM (Rf + beta x ERP) with dampened momentum and, when available, analyst targets.
"""
import os, requests
import numpy as np
from scipy.optimize import minimize
from dotenv import load_dotenv

import market_data as md

load_dotenv()

FINNHUB_BASE = "https://finnhub.io/api/v1"

RF  = 0.045   # risk-free rate (approx Fed funds)
ERP = 0.055   # equity risk premium (historical avg)
CAPM_WEIGHT     = 0.30  # CAPM — stability anchor
MOMENTUM_WEIGHT = 0.40  # dampened trailing momentum (academic: Jegadeesh-Titman)
ANALYST_WEIGHT  = 0.30  # Finnhub analyst consensus

LOOKBACK_DAYS = 365       # calendar days of returns used for vol, beta, momentum and covariance

# ── Beta handling for short-history listings ──────────────────────────────────
MIN_BARS_FOR_BETA = 180   # ~9 months of overlapping days with SPY; below this OLS beta is unreliable
TICKER_BETA_PRIORS = {
    'SNDK': 2.8,   # SanDisk spinoff Feb 2025 — NAND/AI memory peers
    'NBIS': 2.5,   # Nebius — GPU cloud, new listing
    'CEG':  1.2,   # Constellation — regulated utility-adjacent
}

# ── Market scenarios for beta-driven projections (Option B) ───────────────────
MARKET_SCENARIOS = {
    "bull": {"spy": 0.22,  "label": "Bull — AI supercycle holds 3yr",
             "color": "#2e7d32", "bg": "#e8f5e9"},
    "base": {"spy": 0.09,  "label": "Base — normal market conditions",
             "color": "#1565c0", "bg": "#e3f2fd"},
    "bear": {"spy": -0.15, "label": "Bear — AI capex pause / recession",
             "color": "#b71c1c", "bg": "#ffebee"},
}

# ── Smart suggestions candidate list (used when Claude is unavailable) ────────
# Return and volatility for every candidate are computed from its real price history at request time.
SMART_DB = {
    "AI_OPTICAL":  [("GLW","Corning — optical fiber, AI data-center supply chain","AI Infra Optical"),
                    ("COHR","Coherent — optical transceivers, NVDA stake","AI Infra Optical"),
                    ("LITE","Lumentum — optical components, AI network","AI Infra Optical")],
    "AI_POWER":    [("GEV","GE Vernova — gas turbines, AI data-center power","Power Infra"),
                    ("CEG","Constellation Energy — nuclear PPAs, Microsoft/Walmart","Nuclear Power"),
                    ("VST","Vistra — power gen, KKR+NVDA Helix","Power Generation"),
                    ("ETR","Entergy — utility, low-vol AI power exposure","Utility")],
    "AI_NETWORK":  [("ANET","Arista Networks — 40%+ EBITDA margin, AI ethernet","AI Networking"),
                    ("MRVL","Marvell — custom ASIC, hyperscaler chip design","Custom ASIC"),
                    ("AVGO","Broadcom — custom ASIC + networking","Semiconductors")],
    "AI_COMPUTE":  [("SNDK","SanDisk — NAND AI memory, RAM supercycle","Semiconductors"),
                    ("NBIS","Nebius — GPU cloud infra, $47B backlog","AI Cloud"),
                    ("MU","Micron — DRAM/HBM, AI memory","Semiconductors")],
    "BLUECHIP":    [("WMT","Walmart — defensive retail, low vol","Consumer Staples"),
                    ("JPM","JPMorgan — largest US bank, dividend","Financials"),
                    ("JNJ","Johnson & Johnson — healthcare, defensive","Healthcare"),
                    ("BRK/B","Berkshire Hathaway — Buffett diversified","Conglomerate"),
                    ("PG","Procter & Gamble — consumer staples","Consumer Staples")],
    "GROWTH_DIV":  [("NOW","ServiceNow — enterprise SaaS, AI workflow","Enterprise SaaS"),
                    ("SOFI","SoFi — fintech, S&P500 candidate","Fintech"),
                    ("CRWD","CrowdStrike — cybersecurity, AI-native","Cybersecurity")],
    "ENERGY_TRANS":[("NEE","NextEra Energy — renewable power, utility","Utilities")],
}
DEFAULT_PORTFOLIO = ['GLW','SNDK','NBIS','GEV','MRVL','COHR','ANET','VST','NOW']


def prefetch_universe() -> list:
    """Every ticker worth warming in the cache at startup."""
    db = [t for cl in SMART_DB.values() for (t, *_) in cl]
    return list(dict.fromkeys(["SPY"] + DEFAULT_PORTFOLIO + db))


def _fetch_analyst_targets(tickers: list) -> dict:
    """
    Analyst consensus price targets from Finnhub. Returns {ticker: mean_target_price}.
    Finnhub's price-target endpoint is not on its free tier, so this usually returns nothing,
    in which case returns are blended from CAPM and momentum only.
    """
    from concurrent.futures import ThreadPoolExecutor

    finnhub_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not finnhub_key:
        return {}

    def fetch_finnhub(t):
        try:
            r = requests.get(f"{FINNHUB_BASE}/stock/price-target",
                             params={"symbol": t, "token": finnhub_key}, timeout=8)
            if r.status_code == 200:
                d = r.json()
                target = d.get("targetMean") or d.get("targetMedian")
                if target and float(target) > 0:
                    return t, float(target)
            else:
                print(f"[Finnhub] {t}: HTTP {r.status_code}")
        except Exception as ex:
            print(f"[Finnhub] {t} error: {ex}")
        return t, None

    result = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for ticker, target in pool.map(fetch_finnhub, tickers):
            if target:
                result[ticker] = target
    print(f"[analyst] Got targets for {len(result)}/{len(tickers)} tickers")
    return result


# ── Date-aligned returns ──────────────────────────────────────────────────────

def _returns_from_bars(bars: list) -> tuple[list, np.ndarray]:
    """Daily simple returns over the lookback window, keyed by the date each return ends on."""
    import datetime as dt
    cutoff = (dt.date.fromisoformat(bars[-1][0]) - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    window = [b for b in bars if b[0] >= cutoff]
    closes = np.array([b[1] for b in window], dtype=float)
    return [b[0] for b in window[1:]], np.diff(closes) / closes[:-1]


def aligned_matrix(tickers: list, data: dict) -> np.ndarray:
    """Returns matrix (tickers x common dates). Only dates every ticker traded on are kept."""
    common = set(data[tickers[0]]["dates"])
    for t in tickers[1:]:
        common &= set(data[t]["dates"])
    dates = sorted(common)
    rows = []
    for t in tickers:
        lookup = dict(zip(data[t]["dates"], data[t]["returns"]))
        rows.append([lookup[d] for d in dates])
    return np.array(rows, dtype=float)


def _compute_beta(stock: dict, spy: dict) -> tuple[float, int]:
    """OLS beta on overlapping dates. Returns (beta, number of overlapping days)."""
    spy_map = dict(zip(spy["dates"], spy["returns"]))
    pairs = [(r, spy_map[d]) for d, r in zip(stock["dates"], stock["returns"]) if d in spy_map]
    if len(pairs) < 30:
        return 1.0, len(pairs)
    y, x = np.array(pairs).T
    var_x = float(np.var(x, ddof=1))
    return (float(np.cov(y, x)[0, 1] / var_x) if var_x > 1e-12 else 1.0), len(pairs)


# ── Main data pipeline ────────────────────────────────────────────────────────

def fetch_returns(tickers: list, budget_s: float = 20) -> dict:
    """
    Real daily bars for every ticker plus SPY, then CAPM/momentum/analyst blended returns.

    Returns {"data": {ticker: {...}}, "pending": [...], "missing": [...], "through": "YYYY-MM-DD"}.
      pending: tickers whose history is still downloading (rate limit); retry shortly
      missing: tickers Massive has no daily bars for (bad symbol, delisted)
    """
    print(f"\n[fetch_returns] tickers={tickers}")
    bars, pending = md.get_many(list(dict.fromkeys(tickers + ["SPY"])), budget_s=budget_s)
    missing = [t for t in tickers if t in bars and len(bars[t]) < 31]
    if "SPY" in pending:
        return {"data": {}, "pending": pending, "missing": missing, "through": None}

    spy_dates, spy_ret = _returns_from_bars(bars["SPY"])
    spy = {"dates": spy_dates, "returns": spy_ret}
    usable = [t for t in tickers if t in bars and len(bars[t]) >= 31]
    targets = _fetch_analyst_targets(usable) if usable else {}

    result = {}
    for t in usable:
        dates, daily_ret = _returns_from_bars(bars[t])
        ann_vol   = float(daily_ret.std(ddof=1) * np.sqrt(252))
        trail_ret = float((1 + daily_ret.mean()) ** 252 - 1)
        price     = float(bars[t][-1][1])

        beta, overlap = _compute_beta({"dates": dates, "returns": daily_ret}, spy)
        if overlap < MIN_BARS_FOR_BETA:
            beta = TICKER_BETA_PRIORS.get(t.upper(), 1.2)
            beta_note = f"sector proxy β (only {overlap} days of history)"
        else:
            beta_note = f"OLS vs SPY, {overlap} days"
        capm_ret = RF + beta * ERP

        # Dampened trailing momentum — sqrt(|r|) compresses extremes, capped at ±100%
        if abs(trail_ret) > 0.001:
            damped_mom = float(np.clip(np.sign(trail_ret) * np.sqrt(abs(trail_ret)), -1.0, 1.0))
        else:
            damped_mom = trail_ret

        analyst_target = targets.get(t)
        if analyst_target and price > 0:
            analyst_implied = (analyst_target / price) - 1
            blended_ret = (CAPM_WEIGHT * capm_ret + MOMENTUM_WEIGHT * damped_mom
                           + ANALYST_WEIGHT * analyst_implied)
            return_source = "30% CAPM / 40% momentum / 30% analyst"
        else:
            analyst_implied = None
            w_capm = CAPM_WEIGHT / (CAPM_WEIGHT + MOMENTUM_WEIGHT)
            w_mom  = MOMENTUM_WEIGHT / (CAPM_WEIGHT + MOMENTUM_WEIGHT)
            blended_ret = w_capm * capm_ret + w_mom * damped_mom
            return_source = "43% CAPM / 57% momentum (no analyst data)"

        result[t] = {
            "dates":            dates,
            "returns":          daily_ret.tolist(),
            "ann_ret":          round(blended_ret, 4),
            "ann_vol":          round(ann_vol, 4),
            "beta":             round(beta, 3),
            "beta_note":        beta_note,
            "capm_return":      round(capm_ret * 100, 2),
            "analyst_target":   round(analyst_target, 2) if analyst_target else None,
            "analyst_implied":  round(analyst_implied * 100, 1) if analyst_implied is not None else None,
            "blended_return":   round(blended_ret * 100, 2),
            "trailing_ret":     round(trail_ret * 100, 1),
            "return_source":    return_source,
            "price":            round(price, 2),
            "price_date":       bars[t][-1][0],
            "sharpe":           round((blended_ret - RF) / ann_vol, 3) if ann_vol > 0 else 0,
            "data_source":      f"Massive daily bars through {bars[t][-1][0]}",
            "n_days":           len(daily_ret),
        }
        print(f"[fetch_returns] {t}: β={beta:.2f} ({beta_note}) blended={blended_ret*100:.1f}% "
              f"vol={ann_vol*100:.1f}%")

    through = max((v["price_date"] for v in result.values()), default=None)
    return {"data": result, "pending": [t for t in pending if t != "SPY"], "missing": missing,
            "through": through}


# ── Portfolio math ────────────────────────────────────────────────────────────

def build_cov(tickers: list, data: dict) -> np.ndarray:
    """Annualised covariance on the dates every ticker traded on."""
    return np.cov(aligned_matrix(tickers, data)) * 252


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
    w_curr   = np.array(existing_weights, dtype=float)
    w_curr   = w_curr / w_curr.sum()
    mu_curr  = np.array([existing_data[t]['ann_ret'] for t in existing_tickers])
    cov_curr = build_cov(existing_tickers, existing_data)
    r0, v0, s0 = portfolio_stats(w_curr, mu_curr, cov_curr, rf)

    new_tickers = existing_tickers + [candidate_ticker]
    new_weights = np.append(w_curr * (1 - add_pct), add_pct)
    all_data    = {**existing_data, candidate_ticker: candidate_data}
    mu_new  = np.array([all_data[t]['ann_ret'] for t in new_tickers])
    cov_new = build_cov(new_tickers, all_data)
    r1, v1, s1 = portfolio_stats(new_weights, mu_new, cov_new, rf)

    corr = np.corrcoef(aligned_matrix(new_tickers, all_data))
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


def exposure_warnings(tickers, weights):
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
    return warnings, {'ai':round(ai_w*100,1),'power':round(pwr_w*100,1),'defensive':0,
                      'other':round(max(0,1-ai_w-pwr_w)*100,1)}


def score_candidates(tickers, weights, data, candidates):
    """Adds real-data marginal impact to each candidate dict (needs 'ticker'). Returns (scored, pending)."""
    wanted = [c['ticker'] for c in candidates]
    fetched = fetch_returns(wanted, budget_s=10) if wanted else {"data": {}, "pending": []}
    scored = []
    for c in candidates:
        cd = fetched["data"].get(c['ticker'])
        if not cd:
            continue
        try:
            impact = marginal_impact(tickers, weights, data, c['ticker'], cd)
        except (ValueError, np.linalg.LinAlgError, ZeroDivisionError) as ex:
            print(f"[smart] {c['ticker']}: impact not computable ({ex})")
            continue
        scored.append({**c, 'exp_return': cd['ann_ret'], 'ann_vol': cd['ann_vol'], **impact})
    return scored, fetched.get("pending", [])


def smart_suggestions_v2(tickers, weights, data):
    existing = {t.upper() for t in tickers}
    candidates = []
    for cluster in ['AI_OPTICAL','AI_POWER','AI_NETWORK','AI_COMPUTE','ENERGY_TRANS','BLUECHIP','GROWTH_DIV']:
        for (t, desc, sec) in SMART_DB[cluster]:
            if t not in existing:
                candidates.append({'ticker': t, 'desc': desc, 'sector': sec,
                                   'type': 'complement' if cluster not in ['BLUECHIP','GROWTH_DIV'] else 'diversifier'})
    results, pending = score_candidates(tickers, weights, data, candidates)

    sharpe_enhancers = sorted([r for r in results if r['type']=='complement'],
                               key=lambda x: -x['sharpe_delta'])[:5]
    vol_reducers     = sorted([r for r in results if r['type']=='diversifier'],
                               key=lambda x: (x['corr_to_book'], x['ann_vol']))[:5]
    warnings, exposure = exposure_warnings(tickers, weights)
    return {'sharpe_enhancers':sharpe_enhancers, 'vol_reducers':vol_reducers,
            'warnings':warnings, 'exposure':exposure, 'pending': pending}
