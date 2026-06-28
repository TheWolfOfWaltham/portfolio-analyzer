"""
portfolio_engine.py
Quant logic: MVO, Monte Carlo, frontier, scenarios, smart suggestions.
Data: Alpaca Markets API with realistic simulated fallback.
"""
import os, requests, datetime
import numpy as np
from scipy.optimize import minimize
from dotenv import load_dotenv

load_dotenv()

ALPACA_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE   = "https://data.alpaca.markets"

# ── Smart DB ──────────────────────────────────────────────────────────────────
SMART_DB = {
    "AI_OPTICAL":  [("GLW","Corning — optical fiber, AI data-center supply chain","AI Infra Optical",0.55,0.70),
                    ("COHR","Coherent — optical transceivers, NVDA stake","AI Infra Optical",0.55,0.75),
                    ("LITE","Lumentum — optical components, AI network","AI Infra Optical",0.48,0.72)],
    "AI_POWER":    [("GEV","GE Vernova — gas turbines, AI data-center power","Power Infra",0.45,0.42),
                    ("CEG","Constellation Energy — nuclear PPAs, Microsoft/Walmart","Nuclear Power",0.20,0.35),
                    ("VST","Vistra — power gen, KKR+NVDA Helix, beta 0.52","Power Generation",0.25,0.38),
                    ("ETR","Entergy — utility, low-vol AI power exposure","Utility",0.12,0.22)],
    "AI_NETWORK":  [("ANET","Arista Networks — 40%+ EBITDA margin, AI ethernet","AI Networking",0.38,0.45),
                    ("MRVL","Marvell — custom ASIC, hyperscaler chip design","Custom ASIC",0.65,0.65),
                    ("AVGO","Broadcom — custom ASIC + networking","Semiconductors",0.40,0.45)],
    "AI_COMPUTE":  [("SNDK","SanDisk — NAND AI memory, RAM supercycle","Semiconductors",0.80,1.80),
                    ("NBIS","Nebius — GPU cloud infra, $47B backlog","AI Cloud",0.60,0.85),
                    ("MU","Micron — DRAM/HBM, AI memory","Semiconductors",0.50,0.70)],
    "BLUECHIP":    [("WMT","Walmart — defensive retail, low vol","Consumer Staples",0.08,0.18),
                    ("JPM","JPMorgan — largest US bank, dividend","Financials",0.12,0.22),
                    ("JNJ","Johnson & Johnson — healthcare, defensive","Healthcare",0.06,0.16),
                    ("BRK/B","Berkshire Hathaway — Buffett diversified","Conglomerate",0.09,0.15),
                    ("PG","Procter & Gamble — consumer staples","Consumer Staples",0.07,0.14)],
    "GROWTH_DIV":  [("NOW","ServiceNow — enterprise SaaS, AI workflow","Enterprise SaaS",-0.05,0.40),
                    ("SOFI","SoFi — fintech, S&P500 candidate","Fintech",0.10,0.55),
                    ("CRWD","CrowdStrike — cybersecurity, AI-native","Cybersecurity",0.30,0.50)],
    "ENERGY_TRANS":[("NEE","NextEra Energy — renewable power, utility","Utilities",0.10,0.20)],
}

# Realistic per-ticker priors (ann_ret, ann_vol, current_price)
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
    "ETR":  (0.12, 0.22, 82),
}
DEFAULT_PRIOR = (0.15, 0.45, 100)

# Correlation matrix seed for simulation (used when Alpaca unavailable)
CORR_SEED = {
    ("GLW","COHR"):0.62, ("GLW","GEV"):0.48, ("GLW","ANET"):0.32,
    ("SNDK","NBIS"):0.55,("SNDK","MRVL"):0.55,("NBIS","MRVL"):0.50,
    ("GEV","VST"):0.55,  ("GEV","CEG"):0.58,  ("VST","CEG"):0.72,
    ("MRVL","ANET"):0.48,("COHR","ANET"):0.38,
}


def _simulated_returns(ticker: str, n: int = 252) -> np.ndarray:
    """Generate realistic daily returns matching known vol/return priors."""
    ann_ret, ann_vol, _ = TICKER_PRIORS.get(ticker.upper(), DEFAULT_PRIOR)
    daily_mu  = ann_ret / 252
    daily_sig = ann_vol / np.sqrt(252)
    np.random.seed(abs(hash(ticker)) % (2**31))
    return np.random.normal(daily_mu, daily_sig, n)


def _fetch_alpaca(tickers: list, days: int = 365) -> dict:
    """Try Alpaca API. Returns {} on any failure."""
    if not ALPACA_KEY or not ALPACA_SECRET:
        return {}
    end   = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    headers = {
        "APCA-API-KEY-ID":     ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
        "Accept":              "application/json",
    }
    params = {
        "symbols":    ",".join(tickers),
        "timeframe":  "1Day",
        "start":      start.isoformat(),
        "end":        end.isoformat(),
        "limit":      10000,
        "adjustment": "all",
        "sort":       "asc",
    }
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/stocks/bars",
                         headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json().get("bars", {})
    except Exception:
        pass
    return {}


def fetch_returns(tickers: list, period_days: int = 365) -> tuple[dict, bool]:
    """
    Returns (data_dict, is_live).
    is_live=True  → real Alpaca data
    is_live=False → simulated data based on calibrated priors
    """
    raw = _fetch_alpaca(tickers, days=period_days)
    result = {}
    is_live = False

    for t in tickers:
        bars = raw.get(t) or raw.get(t.replace("/", ""))
        if bars and len(bars) >= 30:
            closes    = np.array([b["c"] for b in bars], dtype=float)
            daily_ret = np.diff(closes) / closes[:-1]
            ann_ret   = float((1 + daily_ret.mean()) ** 252 - 1)
            ann_vol   = float(daily_ret.std() * np.sqrt(252))
            price     = float(closes[-1])
            is_live   = True
        else:
            # Fallback: calibrated simulation
            ann_ret, ann_vol, price = TICKER_PRIORS.get(t.upper(), DEFAULT_PRIOR)
            daily_ret = _simulated_returns(t)

        result[t] = {
            "returns": daily_ret.tolist(),
            "ann_ret": ann_ret,
            "ann_vol": ann_vol,
            "price":   round(price, 2),
            "sharpe":  round((ann_ret - 0.045) / ann_vol, 3) if ann_vol > 0 else 0,
        }

    return result, is_live


# ── Covariance ────────────────────────────────────────────────────────────────
def build_cov(tickers: list, data: dict) -> np.ndarray:
    min_len = min(len(data[t]["returns"]) for t in tickers)
    M = np.array([np.array(data[t]["returns"])[:min_len] for t in tickers])
    return np.cov(M) * 252


# ── Portfolio stats ───────────────────────────────────────────────────────────
def portfolio_stats(weights, mu, cov, rf: float = 0.045):
    w        = np.array(weights)
    port_ret = float(w @ mu)
    port_vol = float(np.sqrt(w @ cov @ w))
    sharpe   = (port_ret - rf) / port_vol if port_vol > 0 else 0.0
    return port_ret, port_vol, sharpe


# ── Optimization ──────────────────────────────────────────────────────────────
def optimize(mu, cov, mode: str = "sharpe", rf: float = 0.045) -> list:
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


# ── Efficient frontier ────────────────────────────────────────────────────────
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


# ── Monte Carlo ───────────────────────────────────────────────────────────────
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
        v = capital
        path = [capital]
        for j in range(steps):
            v *= np.exp(mu_g * dt + sig * Z[i, j])
            path.append(round(v, 2))
        monthly.append([path[min(k * 21, steps)] for k in range(37)])
    return monthly


# ── Correlation matrix ────────────────────────────────────────────────────────
def correlation_matrix(tickers: list, data: dict) -> list:
    min_len = min(len(data[t]["returns"]) for t in tickers)
    M = np.array([np.array(data[t]["returns"])[:min_len] for t in tickers])
    return np.corrcoef(M).tolist()


# ── Risk contributions ────────────────────────────────────────────────────────
def risk_contributions(weights, cov) -> list:
    w   = np.array(weights)
    vol = float(np.sqrt(w @ cov @ w))
    mrc = (cov @ w) / vol
    rc  = w * mrc
    return (rc / rc.sum()).tolist()


# ── Scenarios ─────────────────────────────────────────────────────────────────
SCENARIOS = {
    "bull": {"label":"Bull — RAM supercycle holds 3yr","color":"#2e7d32","bg":"#e8f5e9",
             "multipliers":{"GLW":0.50,"SNDK":2.80,"NBIS":2.20,"GEV":0.80,"MRVL":2.00,
                            "COHR":1.60,"ANET":0.90,"VST":0.60,"NOW":0.30,"DEFAULT":1.20}},
    "base": {"label":"Base — 2yr supercycle, 1yr plateau","color":"#1565c0","bg":"#e3f2fd",
             "multipliers":{"GLW":0.45,"SNDK":1.90,"NBIS":1.55,"GEV":0.95,"MRVL":1.80,
                            "COHR":1.40,"ANET":0.70,"VST":0.55,"NOW":-0.10,"DEFAULT":0.70}},
    "bear": {"label":"Bear — AI capex pause 2027","color":"#b71c1c","bg":"#ffebee",
             "multipliers":{"GLW":-0.35,"SNDK":-0.55,"NBIS":-0.50,"GEV":0.15,"MRVL":-0.45,
                            "COHR":-0.40,"ANET":-0.30,"VST":0.10,"NOW":-0.25,"DEFAULT":-0.20}},
}


def _fv_annuity(pmt: float, r_ann: float, n_per_yr: int, years: int) -> float:
    if abs(r_ann) < 1e-6:
        return pmt * n_per_yr * years
    r = r_ann / n_per_yr
    n = n_per_yr * years
    return pmt * ((1 + r) ** n - 1) / r


def scenario_projections(tickers, weights, initial_capital, biweekly_contrib, data) -> dict:
    results = {}
    for key, scen in SCENARIOS.items():
        mults = scen["multipliers"]
        rows, tots = [], {k: 0.0 for k in
            ["yr1","yr2","yr3","yr1_init","yr2_init","yr3_init",
             "yr1_contrib","yr2_contrib","yr3_contrib"]}
        for t, w in zip(tickers, weights):
            m3    = mults.get(t, mults["DEFAULT"])
            alloc = w * initial_capital
            ann_r = (1 + m3) ** (1/3) - 1
            vi    = [alloc * (1 + ann_r) ** yr for yr in [1, 2, 3]]
            pmt   = biweekly_contrib * w
            fv    = [_fv_annuity(pmt, ann_r, 26, yr) for yr in [1, 2, 3]]
            yr3_val = vi[2]+fv[2]
            total_biweekly_3yr = pmt * 26 * 3   # flat total DCA over 3 years
            total_invested = alloc + total_biweekly_3yr
            # Contribution-adjusted: profit vs ALL money in
            contrib_adj_pct = round((yr3_val - total_invested) / total_invested * 100, 1) if total_invested > 0 else 0
            # Initial-only: how much did the first lump sum grow
            initial_only_pct = round((yr3_val - alloc) / alloc * 100, 1) if alloc > 0 else 0
            rows.append({"ticker":t,"weight":round(w*100,1),"init":round(alloc,0),
                         "biweekly":round(pmt,2),
                         "ann_r":round(ann_r*100,1),
                         "yr1":round(vi[0]+fv[0],0),"yr2":round(vi[1]+fv[1],0),
                         "yr3":round(yr3_val,0),
                         "contrib_adj_pct": contrib_adj_pct,
                         "initial_only_pct": initial_only_pct,
                         "total_return_pct": contrib_adj_pct})
            for i, yr in enumerate(["yr1","yr2","yr3"]):
                tots[yr] += vi[i]+fv[i]
                tots[f"{yr}_init"]    += vi[i]
                tots[f"{yr}_contrib"] += fv[i]
        for k in tots: tots[k] = round(tots[k], 0)
        results[key] = {"label":scen["label"],"color":scen["color"],"bg":scen["bg"],
                        "rows":rows,"totals":tots,
                        "total_return_pct":round((tots["yr3"]-initial_capital)/initial_capital*100,1)}
    return results


# ── Smart suggestions ─────────────────────────────────────────────────────────
def smart_suggestions(tickers: list, weights: list, data: dict) -> dict:
    existing = {t.upper() for t in tickers}
    complements, diversifiers = [], []
    for cluster in ["AI_OPTICAL","AI_POWER","AI_NETWORK","AI_COMPUTE","ENERGY_TRANS"]:
        for (t, desc, sec, ret, vol) in SMART_DB[cluster]:
            if t not in existing and len(complements) < 5:
                complements.append({"ticker":t,"desc":desc,"sector":sec,
                    "exp_return":f"{ret*100:.0f}%","ann_vol":f"{vol*100:.0f}%",
                    "rationale":"AI-adjacent · infrastructure moat · lower vol profile"})
    for cluster in ["BLUECHIP","GROWTH_DIV"]:
        for (t, desc, sec, ret, vol) in SMART_DB[cluster]:
            if t not in existing and len(diversifiers) < 5:
                diversifiers.append({"ticker":t,"desc":desc,"sector":sec,
                    "exp_return":f"{ret*100:.0f}%","ann_vol":f"{vol*100:.0f}%",
                    "rationale":"Portfolio hedge · uncorrelated sector · AI-capex risk buffer"})
    ai_w = sum(w for t, w in zip(tickers, weights)
               if any(t.upper()==db_t for cl in ["AI_COMPUTE","AI_OPTICAL","AI_NETWORK"]
                      for db_t,*_ in SMART_DB[cl]))
    warnings = []
    if ai_w > 0.60:
        warnings.append(f"High AI concentration ({ai_w*100:.0f}%). Consider adding power/energy or blue-chip names.")
    if not any(t.upper() in {db_t for db_t,*_ in SMART_DB["BLUECHIP"]} for t in tickers):
        warnings.append("No blue-chip defensive positions. WMT/JPM/JNJ reduce max drawdown in a risk-off selloff.")
    return {"complements":complements[:5],"diversifiers":diversifiers[:5],
            "warnings":warnings,"ai_weight_pct":round(ai_w*100,1)}


# ── Enhanced smart suggestions with marginal impact ───────────────────────────
def marginal_impact(existing_tickers, existing_weights, existing_data,
                    candidate_ticker, candidate_data, add_pct=0.05, rf=0.045):
    """
    Compute the marginal Sharpe and vol impact of adding candidate_ticker
    at add_pct weight, funded proportionally from existing positions.
    Returns dict with sharpe_delta, vol_delta, corr_to_book.
    """
    try:
        # Current portfolio
        n = len(existing_tickers)
        w_curr = np.array(existing_weights)
        mu_curr = np.array([existing_data[t]['ann_ret'] for t in existing_tickers])
        cov_curr = build_cov(existing_tickers, existing_data)
        r0, v0, s0 = portfolio_stats(w_curr, mu_curr, cov_curr, rf)

        # New portfolio with candidate added
        new_tickers = existing_tickers + [candidate_ticker]
        new_weights = np.append(w_curr * (1 - add_pct), add_pct)
        new_weights /= new_weights.sum()

        # Merge data
        all_data = {**existing_data, candidate_ticker: candidate_data}
        mu_new = np.array([all_data[t]['ann_ret'] for t in new_tickers])
        cov_new = build_cov(new_tickers, all_data)
        r1, v1, s1 = portfolio_stats(new_weights, mu_new, cov_new, rf)

        # Correlation of candidate to existing book (weighted avg)
        min_len = min(len(all_data[t]['returns']) for t in new_tickers)
        M = np.array([np.array(all_data[t]['returns'])[:min_len] for t in new_tickers])
        corr = np.corrcoef(M)
        cand_idx = len(new_tickers) - 1
        # Weighted avg correlation to existing
        corr_to_book = float(np.average(corr[cand_idx, :-1], weights=w_curr))

        return {
            'sharpe_delta': round(s1 - s0, 3),
            'vol_delta':    round((v1 - v0) * 100, 2),
            'ret_delta':    round((r1 - r0) * 100, 2),
            'corr_to_book': round(corr_to_book, 3),
            'new_sharpe':   round(s1, 3),
            'new_vol':      round(v1 * 100, 1),
            'new_ret':      round(r1 * 100, 1),
        }
    except Exception as e:
        return {
            'sharpe_delta': 0, 'vol_delta': 0, 'ret_delta': 0,
            'corr_to_book': 0, 'new_sharpe': 0, 'new_vol': 0, 'new_ret': 0,
        }


def smart_suggestions_v2(tickers, weights, data):
    """
    Enhanced smart suggestions with marginal portfolio impact per candidate.
    Returns sharpe_enhancers and vol_reducers sorted by impact.
    """
    existing = {t.upper() for t in tickers}
    w_arr = np.array(weights)

    # Gather all candidates
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

    # Build simulated data for each candidate
    results = []
    for cand in all_candidates:
        t = cand['ticker']
        cand_data = {
            'returns': _simulated_returns(t).tolist(),
            'ann_ret': cand['exp_return'],
            'ann_vol': cand['ann_vol'],
            'price': TICKER_PRIORS.get(t, DEFAULT_PRIOR)[2],
            'sharpe': round((cand['exp_return'] - 0.045) / cand['ann_vol'], 3)
        }
        if data and all(t in data for t in tickers):
            impact = marginal_impact(tickers, weights, data, t, cand_data)
        else:
            # Fallback: estimate from vol/corr priors
            impact = {
                'sharpe_delta': round((cand['exp_return'] - 0.045) / cand['ann_vol'] * 0.05, 3),
                'vol_delta': round((cand['ann_vol'] - 0.50) * -2, 2),
                'ret_delta': round(cand['exp_return'] * 0.05 * 100, 2),
                'corr_to_book': 0.3 if cand['type'] == 'complement' else 0.1,
                'new_sharpe': 0, 'new_vol': 0, 'new_ret': 0,
            }
        results.append({**cand, **impact})

    # Sort: sharpe enhancers by sharpe_delta desc
    sharpe_enhancers = sorted(
        [r for r in results if r['type'] == 'complement'],
        key=lambda x: -x['sharpe_delta']
    )[:5]

    # Sort: vol reducers by lowest corr_to_book + lowest vol
    vol_reducers = sorted(
        [r for r in results if r['type'] == 'diversifier'],
        key=lambda x: (x['corr_to_book'], x['ann_vol'])
    )[:5]

    # Sector exposure breakdown
    ai_w  = sum(w for t,w in zip(tickers,weights)
                if any(t.upper()==db_t for cl in ['AI_COMPUTE','AI_OPTICAL','AI_NETWORK']
                       for db_t,*_ in SMART_DB[cl]))
    pwr_w = sum(w for t,w in zip(tickers,weights)
                if any(t.upper()==db_t for db_t,*_ in SMART_DB['AI_POWER']))
    def_w = sum(w for t,w in zip(tickers,weights)
                if any(t.upper()==db_t for db_t,*_ in SMART_DB['BLUECHIP']))
    oth_w = max(0, 1 - ai_w - pwr_w - def_w)

    warnings = []
    if ai_w > 0.60:
        warnings.append(f'High AI concentration ({ai_w*100:.0f}%). A single risk-off AI drawdown hits the majority of your book simultaneously.')
    if pwr_w < 0.10:
        warnings.append('Low power & energy exposure. AI data-center electricity demand is a structural multi-year tailwind.')
    if def_w == 0:
        warnings.append('No blue-chip defensive positions. Consider adding 5-10% to reduce max drawdown depth.')

    return {
        'sharpe_enhancers': sharpe_enhancers,
        'vol_reducers':     vol_reducers,
        'warnings':         warnings,
        'exposure': {
            'ai':    round(ai_w*100, 1),
            'power': round(pwr_w*100, 1),
            'defensive': round(def_w*100, 1),
            'other': round(oth_w*100, 1),
        }
    }
