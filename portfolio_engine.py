"""
portfolio_engine.py
Quant logic: expected returns, covariance, MVO, Monte Carlo, frontier, scenarios, smart suggestions.
Data: Massive daily bars only (market_data.py). A ticker without real price history is excluded and
reported, never estimated or simulated.

Expected return for each stock:
    mu = rf + beta_adj x ERP                                      CAPM anchor, Blume-adjusted beta
       + ic x resid_vol x z                                       12-1 momentum, z-scored across the cached watchlist
       + ANALYST_WEIGHT x ((target / price - 1 - ANALYST_BIAS) - anchor)   only when the user gives a target
"""
import datetime as dt

import numpy as np
from scipy.optimize import minimize
from dotenv import load_dotenv

import market_data as md

load_dotenv()

ERP            = 0.055   # equity risk premium: an assumption (long-run historical average), not market data
MARKET         = "SPY"   # market proxy for beta, residual vol and the momentum regime
IC             = 0.05    # information coefficient of 12-1 momentum, halved when MARKET's own 12-1 is negative
Z_CLIP         = 3.0     # momentum z-scores are clipped to [-Z_CLIP, Z_CLIP]
MOM_LOOKBACK   = 252     # 12-1 momentum: close MOM_SKIP bars ago over close MOM_LOOKBACK bars ago
MOM_SKIP       = 21
MIN_UNIVERSE   = 10      # fewer names with a 12-1 value than this and momentum is switched off
ANALYST_BIAS   = 0.15    # haircut on target-implied upside (sell-side targets run optimistic)
ANALYST_WEIGHT = 0.25    # share of the haircut target's excess over the anchor that enters mu
MAX_WEIGHT     = 0.40    # position cap floor: cap = min(1, max(MAX_WEIGHT, 1.5 / n))
MIN_WEIGHT     = 0.005
LOOKBACK_DAYS  = 725     # calendar days of returns used for vol, beta and covariance


def current_rf() -> tuple[float, str]:
    """Live 3-month Treasury yield from Massive, cached for the day."""
    return md.risk_free()


# ── Beta handling for short-history listings ──────────────────────────────────
MIN_BARS_FOR_BETA = 180   # ~9 months of overlapping days with MARKET; below this OLS beta is unreliable
TICKER_BETA_PRIORS = {
    'SNDK': 2.8,   # SanDisk spinoff Feb 2025 — NAND/AI memory peers
    'NBIS': 2.5,   # Nebius — GPU cloud, new listing
    'CEG':  1.2,   # Constellation — regulated utility-adjacent
}

# ── Market scenarios for beta-driven projections (Option B) ───────────────────
MARKET_SCENARIOS = {
    "bull": {"spy": 0.22,  "label": "Bull: AI supercycle holds 3yr",
             "color": "#2e7d32", "bg": "#e8f5e9"},
    "base": {"spy": 0.09,  "label": "Base: normal market conditions",
             "color": "#1565c0", "bg": "#e3f2fd"},
    "bear": {"spy": -0.15, "label": "Bear: AI capex pause / recession",
             "color": "#b71c1c", "bg": "#ffebee"},
}

# ── Smart suggestions candidate list (used when Claude is unavailable) ────────
# Return and volatility for every candidate are computed from its real price history at request time.
SMART_DB = {
    "AI_OPTICAL":  [("GLW","Corning: optical fiber, AI data-center supply chain","AI Infra Optical"),
                    ("COHR","Coherent: optical transceivers, NVDA stake","AI Infra Optical"),
                    ("LITE","Lumentum: optical components, AI network","AI Infra Optical")],
    "AI_POWER":    [("GEV","GE Vernova: gas turbines, AI data-center power","Power Infra"),
                    ("CEG","Constellation Energy: nuclear PPAs, Microsoft/Walmart","Nuclear Power"),
                    ("VST","Vistra: power gen, KKR+NVDA Helix","Power Generation"),
                    ("ETR","Entergy: utility, low-vol AI power exposure","Utility")],
    "AI_NETWORK":  [("ANET","Arista Networks: 40%+ EBITDA margin, AI ethernet","AI Networking"),
                    ("MRVL","Marvell: custom ASIC, hyperscaler chip design","Custom ASIC"),
                    ("AVGO","Broadcom: custom ASIC + networking","Semiconductors")],
    "AI_COMPUTE":  [("SNDK","SanDisk: NAND AI memory, RAM supercycle","Semiconductors"),
                    ("NBIS","Nebius: GPU cloud infra, $47B backlog","AI Cloud"),
                    ("MU","Micron: DRAM/HBM, AI memory","Semiconductors")],
    "BLUECHIP":    [("WMT","Walmart: defensive retail, low vol","Consumer Staples"),
                    ("JPM","JPMorgan: largest US bank, dividend","Financials"),
                    ("JNJ","Johnson & Johnson: healthcare, defensive","Healthcare"),
                    ("BRK/B","Berkshire Hathaway: Buffett diversified","Conglomerate"),
                    ("PG","Procter & Gamble: consumer staples","Consumer Staples")],
    "GROWTH_DIV":  [("NOW","ServiceNow: enterprise SaaS, AI workflow","Enterprise SaaS"),
                    ("SOFI","SoFi: fintech, S&P500 candidate","Fintech"),
                    ("CRWD","CrowdStrike: cybersecurity, AI-native","Cybersecurity")],
    "ENERGY_TRANS":[("NEE","NextEra Energy: renewable power, utility","Utilities")],
}
DEFAULT_PORTFOLIO = ['GLW','SNDK','NBIS','GEV','MRVL','COHR','ANET','VST','NOW']


def prefetch_universe() -> list:
    """Every ticker worth warming in the cache at startup."""
    db = [t for cl in SMART_DB.values() for (t, *_) in cl]
    return list(dict.fromkeys([MARKET] + DEFAULT_PORTFOLIO + db))


def position_cap(n: int) -> float:
    """Largest weight one position may take: 0.75 for 2 names, 0.5 for 3, 0.4 from 4 names up."""
    return min(1.0, max(MAX_WEIGHT, 1.5 / n)) if n > 0 else 1.0


# ── Date-aligned returns ──────────────────────────────────────────────────────

def _returns_from_bars(bars: list) -> tuple[list, np.ndarray]:
    """Daily simple returns over the lookback window, keyed by the date each return ends on."""
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


def _regress_on_market(dates: list, rets: np.ndarray, mkt: dict) -> tuple[float | None, float | None, int]:
    """OLS beta and annualised residual vol on overlapping dates. (None, None, overlap) when too short."""
    mkt_map = dict(zip(mkt["dates"], mkt["returns"]))
    pairs = [(r, mkt_map[d]) for d, r in zip(dates, rets) if d in mkt_map]
    if len(pairs) < MIN_BARS_FOR_BETA:
        return None, None, len(pairs)
    y, x = np.array(pairs).T
    var_x = float(np.var(x, ddof=1))
    if var_x <= 1e-12:
        return None, None, len(pairs)
    beta = float(np.cov(y, x)[0, 1] / var_x)
    resid_vol = float(np.std(y - beta * x, ddof=1) * np.sqrt(252))
    return beta, resid_vol, len(pairs)


def momentum_12_1(bars: list) -> float | None:
    """close[-1-MOM_SKIP] / close[-1-MOM_LOOKBACK] - 1, or None with fewer than MOM_LOOKBACK + 1 bars."""
    if len(bars) < MOM_LOOKBACK + 1:
        return None
    return float(bars[-1 - MOM_SKIP][1] / bars[-1 - MOM_LOOKBACK][1] - 1)


def trailing_12m(bars: list) -> float | None:
    if len(bars) < 253:
        return None
    return float(bars[-1][1] / bars[-253][1] - 1)


def momentum_universe(extra_bars: dict | None = None) -> dict:
    """{ticker: 12-1 return} for every cached ticker except MARKET, plus extra_bars (which win over the cache)."""
    pool = {**md.cached_bars(), **(extra_bars or {})}
    out = {}
    for t, bars in pool.items():
        if t == MARKET:
            continue
        m = momentum_12_1(bars)
        if m is not None and np.isfinite(m):
            out[t] = m
    return out


def momentum_z(universe: dict) -> dict | None:
    """Clipped cross-sectional z-scores, or None when momentum is off (too few names or no dispersion)."""
    if len(universe) < MIN_UNIVERSE:
        return None
    vals = np.array(list(universe.values()), dtype=float)
    sd = float(vals.std(ddof=1))
    if not sd > 0:
        return None
    mean = float(vals.mean())
    return {t: float(np.clip((m - mean) / sd, -Z_CLIP, Z_CLIP)) for t, m in universe.items()}


# ── Main data pipeline ────────────────────────────────────────────────────────

def fetch_returns(tickers: list, budget_s: float = 20, targets: dict | None = None) -> dict:
    """
    Real daily bars for every ticker plus MARKET, then anchor-plus-alpha expected returns.
    targets: optional {ticker: user price target > 0}.

    Returns {"data": {ticker: {...}}, "pending": [...], "missing": [...], "through": "YYYY-MM-DD",
             "rf", "rf_source", "mom_universe_n", "mom_ic", "mom_active"}.
      pending: tickers whose history is still downloading (rate limit); retry shortly
      missing: tickers Massive has no daily bars for (bad symbol, delisted)
    """
    print(f"\n[fetch_returns] tickers={tickers}")
    targets = targets or {}
    rejected_targets = []
    bars, pending = md.get_many(list(dict.fromkeys(tickers + [MARKET])), budget_s=budget_s)
    missing = [t for t in tickers if t in bars and len(bars[t]) < 31]
    if MARKET in pending:
        return {"data": {}, "pending": pending, "missing": missing, "through": None, "rf": None,
                "rf_source": None, "mom_universe_n": 0, "mom_ic": None, "mom_active": False, "rejected_targets": []}
    if len(bars.get(MARKET) or []) < 31:
        raise md.MassiveError(f"No usable price history for the market proxy {MARKET}.")

    rf, rf_source = current_rf()
    mkt_dates, mkt_ret = _returns_from_bars(bars[MARKET])
    mkt = {"dates": mkt_dates, "returns": mkt_ret}
    usable = [t for t in tickers if t in bars and len(bars[t]) >= 31]

    universe = momentum_universe({t: bars[t] for t in usable})
    zs = momentum_z(universe)
    mkt_mom = momentum_12_1(bars[MARKET])
    ic = IC / 2 if (mkt_mom is not None and mkt_mom < 0) else IC

    result = {}
    for t in usable:
        dates, daily_ret = _returns_from_bars(bars[t])
        ann_vol = float(daily_ret.std(ddof=1) * np.sqrt(252))
        price   = float(bars[t][-1][1])

        beta_raw, resid_vol, overlap = _regress_on_market(dates, daily_ret, mkt)
        if beta_raw is None:
            listed = t.upper() in TICKER_BETA_PRIORS
            beta = TICKER_BETA_PRIORS.get(t.upper(), 1.2)
            resid_vol = ann_vol
            beta_note = (f"sector proxy beta, only {overlap} days of history" if listed
                         else f"default beta 1.2 (short history), only {overlap} days of history")
        else:
            beta = 0.67 * beta_raw + 0.33
            beta_note = f"Blume-adjusted OLS vs {MARKET}, {overlap} days"
        anchor = rf + beta * ERP

        mom = universe.get(t)
        z = zs.get(t) if zs is not None else None
        alpha_mom = ic * resid_vol * z if z is not None else 0.0

        target = targets.get(t)
        if target and price > 0 and not (0.2 * price <= target <= 5 * price):
            rejected_targets.append(f"{t} ({target:g} vs price {price:.2f})")
            target = None
        if target and price > 0:
            analyst_implied = target / price - 1
            alpha_analyst = ANALYST_WEIGHT * ((analyst_implied - ANALYST_BIAS) - anchor)
        else:
            target, analyst_implied, alpha_analyst = None, None, None

        alpha = alpha_mom + (alpha_analyst or 0.0)
        mu = anchor + alpha
        parts = ["CAPM anchor"] + (["momentum"] if z is not None else []) + (["your target"] if target else [])
        return_source = " + ".join(parts) + (" only" if len(parts) == 1 else "")

        result[t] = {
            "dates":           dates,
            "returns":         daily_ret.tolist(),
            "ann_ret":         mu,
            "ann_vol":         ann_vol,
            "beta":            beta,
            "beta_raw":        beta_raw,
            "beta_note":       beta_note,
            "anchor":          anchor,
            "alpha_mom":       alpha_mom,
            "alpha_analyst":   alpha_analyst,
            "alpha":           alpha,
            "mom_12_1":        mom,
            "mom_z":           z,
            "resid_vol":       resid_vol,
            "trailing_12m":    trailing_12m(bars[t]),
            "analyst_target":  target,
            "analyst_implied": analyst_implied,
            "return_source":   return_source,
            "price":           price,
            "price_date":      bars[t][-1][0],
            "sharpe":          (mu - rf) / ann_vol if ann_vol > 0 else 0.0,
            "data_source":     f"Massive daily bars through {bars[t][-1][0]}",
            "n_days":          len(daily_ret),
        }
        print(f"[fetch_returns] {t}: beta={beta:.2f} ({beta_note}) anchor={anchor*100:.1f}% "
              f"mom={alpha_mom*100:+.1f}% analyst={(alpha_analyst or 0)*100:+.1f}% mu={mu*100:.1f}% "
              f"vol={ann_vol*100:.1f}%")

    through = max((v["price_date"] for v in result.values()), default=None)
    return {"data": result, "pending": [t for t in pending if t != MARKET], "missing": missing,
            "through": through, "rf": rf, "rf_source": rf_source, "mom_universe_n": len(universe),
            "mom_ic": ic, "mom_active": zs is not None, "rejected_targets": rejected_targets}


# ── Portfolio math ────────────────────────────────────────────────────────────

def ledoit_wolf_cc(X: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Ledoit and Wolf (2004), "Honey, I Shrunk the Sample Covariance Matrix": shrink the sample covariance
    toward the constant-correlation target with their optimal intensity. X is T x N daily returns.
    Returns (shrunk daily covariance, intensity in [0, 1]).
    """
    T, N = X.shape
    Y = X - X.mean(axis=0)
    S = Y.T @ Y / T
    sd = np.sqrt(np.diag(S))
    corr = S / np.outer(sd, sd)
    rbar = (corr.sum() - N) / (N * (N - 1))
    F = rbar * np.outer(sd, sd)
    np.fill_diagonal(F, np.diag(S))

    Y2 = Y ** 2
    pi_mat = Y2.T @ Y2 / T - S ** 2                       # pi_ij
    pi_hat = pi_mat.sum()
    theta = (Y ** 3).T @ Y / T - np.diag(S)[:, None] * S  # theta_ii,ij in row i, column j
    rho_off = rbar / 2 * ((np.outer(1 / sd, sd) * theta) + (np.outer(sd, 1 / sd) * theta.T))
    np.fill_diagonal(rho_off, 0.0)
    rho_hat = np.diag(pi_mat).sum() + rho_off.sum()
    gamma_hat = ((F - S) ** 2).sum()
    kappa = (pi_hat - rho_hat) / gamma_hat if gamma_hat > 0 else 0.0
    delta = float(max(0.0, min(1.0, kappa / T)))
    return delta * F + (1 - delta) * S, delta


def build_cov(tickers: list, data: dict) -> tuple[np.ndarray, float | None]:
    """
    Annualised covariance on the dates every ticker traded on, Ledoit-Wolf shrunk toward constant correlation.
    Returns (cov, shrinkage intensity). One ticker or under 30 shared days: sample covariance, intensity None.
    """
    R = aligned_matrix(tickers, data)
    if len(tickers) == 2:      # constant-correlation target equals the sample matrix: shrinkage is meaningless
        return np.atleast_2d(np.cov(R)) * 252, None
    if len(tickers) < 2 or R.shape[1] < 30:
        return np.atleast_2d(np.cov(R)) * 252, None
    cov, delta = ledoit_wolf_cc(R.T)
    return cov * 252, delta


def portfolio_stats(weights, mu, cov, rf: float | None = None):
    rf       = current_rf()[0] if rf is None else rf
    w        = np.array(weights)
    port_ret = float(w @ mu)
    port_vol = float(np.sqrt(w @ cov @ w))
    sharpe   = (port_ret - rf) / port_vol if port_vol > 0 else 0.0
    return port_ret, port_vol, sharpe


def equal_weight_stats(mu, cov, rf: float) -> tuple[float, float, float]:
    """Return, vol and Sharpe of the equal-weight portfolio on the same mu, cov and rf."""
    n = len(mu)
    return portfolio_stats(np.ones(n) / n, np.array(mu), cov, rf)


def _bounds(n: int) -> list:
    return [(MIN_WEIGHT, position_cap(n))] * n


def optimize(mu, cov, mode: str = "sharpe", rf: float | None = None) -> list:
    rf  = current_rf()[0] if rf is None else rf
    mu  = np.array(mu)
    n   = len(mu)
    w0  = np.ones(n) / n
    bnd = _bounds(n)
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
    if not res.success or not np.all(np.isfinite(res.x)):
        raise ValueError(f"Optimizer ({mode}) did not converge: {res.message}")
    w = res.x / res.x.sum()
    return w.tolist()


def _extreme_return(mu: np.ndarray, highest: bool) -> float:
    """Highest (or lowest) portfolio return reachable inside the weight bounds: fill the best names to the cap."""
    n = len(mu)
    lo, cap = MIN_WEIGHT, position_cap(n)
    w, left = np.full(n, lo), 1.0 - n * lo
    for i in (np.argsort(-mu) if highest else np.argsort(mu)):
        add = min(cap - lo, left)
        w[i] += add
        left -= add
    return float(w @ mu)


def efficient_frontier(mu, cov, n_points: int = 40) -> list:
    mu  = np.array(mu)
    n   = len(mu)
    bnd = _bounds(n)
    pts = []
    for target in np.linspace(_extreme_return(mu, False), _extreme_return(mu, True), n_points):
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
    mu_g  = float(np.log1p(port_ret)) - 0.5 * port_vol ** 2   # simple expected return -> log drift
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


def portfolio_summary(port_ret, port_vol, sharpe, hist_dd=None) -> dict:
    """Headline numbers. Loss figures use log returns, so no figure can fall below -100%."""
    mu_g = float(np.log1p(port_ret)) - 0.5 * port_vol ** 2    # median log return per year (lognormal)
    return {
        'ann_ret':       round(port_ret*100, 1),
        'ann_vol':       round(port_vol*100, 1),
        'sharpe':        round(sharpe, 2),
        'port_3yr_geom': round(float(np.expm1(3 * mu_g)) * 100, 1),
        'var_95':        round(float(np.expm1(mu_g - 1.645 * port_vol)) * 100, 1),   # 1-year, 95%
        'max_dd_est':    round(float(np.expm1(-2.5 * port_vol)) * 100, 1),         # 2.5-sigma log move
        'max_dd_hist':   round(hist_dd * 100, 1) if hist_dd is not None else None,
    }


def historical_drawdown(tickers, weights, data):
    """Worst peak-to-trough loss of these weights over the lookback, rebalanced daily, real returns."""
    R = aligned_matrix(tickers, data)
    if R.shape[1] < 2:
        return None
    wealth = np.cumprod(1 + np.array(weights) @ R)
    peak = np.maximum.accumulate(np.concatenate([[1.0], wealth]))[1:]
    return float((wealth / peak - 1).min())


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


def scenario_projections(tickers, weights, initial_capital, biweekly_contrib, data, rf=None) -> dict:
    """
    Beta-driven scenario analysis. Each stock's log return = log(1+rf) + beta x (log(1+market) - log(1+rf)) + alpha,
    with alpha = momentum alpha + analyst alpha from the expected-return model (or from the user's override).
    Working in log returns keeps a high-beta stock above -100% a year in a falling market, where the
    simple-return version (rf + beta x (market - rf)) can imply losing more than everything.
    Market scenarios: Bull SPY+22%, Base SPY+9%, Bear SPY-15%.
    """
    rf = current_rf()[0] if rf is None else rf
    results = {}
    for key, scen in MARKET_SCENARIOS.items():
        spy_ret = scen["spy"]
        rows, tots = [], {k: 0.0 for k in
            ["yr1","yr2","yr3","yr1_init","yr2_init","yr3_init",
             "yr1_contrib","yr2_contrib","yr3_contrib"]}

        for t, w in zip(tickers, weights):
            beta  = data[t]["beta"]
            log_r = np.log1p(rf) + beta * (np.log1p(spy_ret) - np.log1p(rf)) + data[t].get("alpha", 0.0)
            ann_r = float(np.expm1(log_r))
            alloc = w * initial_capital
            pmt   = biweekly_contrib * w

            vi  = [alloc * (1 + ann_r) ** yr for yr in [1, 2, 3]]
            fv  = [_fv_annuity(pmt, ann_r, 26, yr) for yr in [1, 2, 3]]
            yr3_val = vi[2] + fv[2]

            total_invested   = alloc + pmt * 26 * 3
            contrib_adj_pct  = round((yr3_val - total_invested) / total_invested * 100, 1) if total_invested > 0 else 0
            initial_only_pct = round((vi[2] - alloc) / alloc * 100, 1) if alloc > 0 else 0   # initial capital alone

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
        port_pct = round((tots["yr3"]-total_invested_port)/total_invested_port*100,1) if total_invested_port else 0
        results[key] = {
            "label": scen["label"], "color": scen["color"], "bg": scen["bg"],
            "spy_scenario": f"S&P 500 {'+' if spy_ret>=0 else ''}{spy_ret*100:.0f}%/yr",
            "rows": rows, "totals": tots,
            "initial_only_pct": round((tots["yr3_init"]-initial_capital)/initial_capital*100,1) if initial_capital else 0,
            "total_return_pct": port_pct,
            "contrib_adj_pct": port_pct,
        }
    return results


# ── Smart suggestions ─────────────────────────────────────────────────────────

def marginal_impact(existing_tickers, existing_weights, existing_data,
                    candidate_ticker, candidate_data, add_pct=0.05, rf=None):
    rf = current_rf()[0] if rf is None else rf
    w_curr   = np.array(existing_weights, dtype=float)
    w_curr   = w_curr / w_curr.sum()
    mu_curr  = np.array([existing_data[t]['ann_ret'] for t in existing_tickers])
    cov_curr, _ = build_cov(existing_tickers, existing_data)
    r0, v0, s0 = portfolio_stats(w_curr, mu_curr, cov_curr, rf)

    new_tickers = existing_tickers + [candidate_ticker]
    new_weights = np.append(w_curr * (1 - add_pct), add_pct)
    all_data    = {**existing_data, candidate_ticker: candidate_data}
    mu_new  = np.array([all_data[t]['ann_ret'] for t in new_tickers])
    cov_new, _ = build_cov(new_tickers, all_data)
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
        scored.append({**c, 'exp_return': round(cd['ann_ret'], 4), 'ann_vol': round(cd['ann_vol'], 4), **impact})
    return scored, fetched.get("pending", [])


def smart_suggestions_v2(tickers, weights, data):
    existing = {t.upper() for t in tickers}
    candidates = []
    for cluster in ['AI_OPTICAL','AI_POWER','AI_NETWORK','AI_COMPUTE','ENERGY_TRANS','BLUECHIP','GROWTH_DIV']:
        for (t, desc, sec) in SMART_DB[cluster]:
            if t not in existing:
                company, _, why_now = desc.partition(': ')
                candidates.append({'ticker': t, 'desc': desc, 'sector': sec,
                                   'company': company, 'why_now': why_now,
                                   'type': 'complement' if cluster not in ['BLUECHIP','GROWTH_DIV'] else 'diversifier'})
    results, pending = score_candidates(tickers, weights, data, candidates)

    sharpe_enhancers = sorted([r for r in results if r['type']=='complement'],
                               key=lambda x: -x['sharpe_delta'])[:5]
    vol_reducers     = sorted([r for r in results if r['type']=='diversifier'],
                               key=lambda x: (x['corr_to_book'], x['ann_vol']))[:5]
    warnings, exposure = exposure_warnings(tickers, weights)
    return {'sharpe_enhancers':sharpe_enhancers, 'vol_reducers':vol_reducers,
            'warnings':warnings, 'exposure':exposure, 'pending': pending}
