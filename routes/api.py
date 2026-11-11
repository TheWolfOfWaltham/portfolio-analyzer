from flask import Blueprint, request, jsonify
import sys, os, json, requests as req
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import portfolio_engine as pe
from portfolio_engine import (fetch_returns, build_cov, optimize, efficient_frontier,
                               monte_carlo, risk_contributions, portfolio_stats,
                               scenario_projections, smart_suggestions_v2, score_candidates,
                               exposure_warnings, portfolio_summary, historical_drawdown,
                               current_rf, equal_weight_stats, position_cap, momentum_universe, ERP)
import market_data as md
from dotenv import load_dotenv
import numpy as np

load_dotenv()
api_bp = Blueprint('api', __name__)

ANTHROPIC_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_BASE = 'https://api.anthropic.com/v1/messages'

# ── Sector / colour maps ──────────────────────────────────────────────────────
SECTOR_MAP = {
    'GLW':'AI Infra Optical','SNDK':'Semiconductors','NBIS':'AI Cloud Infra',
    'GEV':'Power Infra','MRVL':'Custom ASIC','COHR':'Optical Transceivers',
    'ANET':'AI Networking','VST':'Power Generation','NOW':'Enterprise SaaS',
    'CEG':'Nuclear Power','MU':'Semiconductors','AVGO':'Semiconductors',
    'WMT':'Consumer Staples','JPM':'Financials','JNJ':'Healthcare',
    'BRK/B':'Conglomerate','PG':'Consumer Staples','SOFI':'Fintech',
    'CRWD':'Cybersecurity','NEE':'Utilities','LITE':'AI Infra Optical','ETR':'Utility',
}
SECTOR_COLORS = {
    'AI Infra Optical':'#111827','Optical Transceivers':'#0f1a2e',
    'Semiconductors':'#1a1a1a','AI Cloud Infra':'#1c1c22',
    'Custom ASIC':'#160d38','AI Networking':'#130b30',
    'Power Infra':'#200808','Power Generation':'#240a0a','Nuclear Power':'#1a0606',
    'Enterprise SaaS':'#1e1205','Fintech':'#1a1005','Cybersecurity':'#151020',
    'Consumer Staples':'#0a1a0e','Financials':'#0a100e',
    'Healthcare':'#0c120f','Conglomerate':'#101010',
    'Utilities':'#0d150d','Utility':'#141414','Other':'#131313',
}
MACRO_COLORS = {
    'AI Compute':'#1a1a1a','AI Infrastructure':'#111827',
    'Power & Energy':'#200808','Growth/SaaS':'#1e1205',
    'Defensive':'#0a1a0e','Other':'#160d38',
}
MACRO_BUCKET = {
    'Semiconductors':'AI Compute','AI Cloud Infra':'AI Compute',
    'AI Infra Optical':'AI Infrastructure','Optical Transceivers':'AI Infrastructure',
    'AI Networking':'AI Infrastructure','Custom ASIC':'AI Infrastructure',
    'Power Infra':'Power & Energy','Power Generation':'Power & Energy',
    'Nuclear Power':'Power & Energy','Enterprise SaaS':'Growth/SaaS',
    'Fintech':'Growth/SaaS','Cybersecurity':'Growth/SaaS',
    'Consumer Staples':'Defensive','Healthcare':'Defensive',
    'Conglomerate':'Defensive','Financials':'Defensive',
    'Utilities':'Defensive','Utility':'Defensive','Other':'Other',
}

def _sectors(tickers):
    return {t: {'sector': SECTOR_MAP.get(t,'Other'),
                'color':  SECTOR_COLORS.get(SECTOR_MAP.get(t,'Other'),'#131313'),
                'macro':  MACRO_BUCKET.get(SECTOR_MAP.get(t,'Other'),'Other'),
                'macro_color': MACRO_COLORS.get(MACRO_BUCKET.get(SECTOR_MAP.get(t,'Other'),'Other'),'#160d38')}
            for t in tickers}

def _exposure(tickers, weights, sectors):
    macro, sub = {}, {}
    for t, w in zip(tickers, weights):
        m = sectors[t]['macro']; s = sectors[t]['sector']
        macro[m] = macro.get(m,0) + w*100
        sub[s]   = sub.get(s,0)   + w*100
    return {
        'macro': {k:round(v,1) for k,v in sorted(macro.items(), key=lambda x:-x[1])},
        'sub':   {k:round(v,1) for k,v in sorted(sub.items(),   key=lambda x:-x[1])},
        'macro_colors': {m: MACRO_COLORS.get(m,'#160d38') for m in macro},
        'sub_colors':   {s: SECTOR_COLORS.get(s,'#131313') for s in sub},
    }


# ── Claude smart suggestions ──────────────────────────────────────────────────
def _call_claude(tickers, weights, sectors, exposure, user_prompt=''):
    if not ANTHROPIC_KEY:
        return None
    weighted  = ', '.join(f"{t} ({w*100:.1f}%)" for t,w in zip(tickers,weights))
    macro_str = ', '.join(f"{k}: {v}%" for k,v in (exposure.get('macro',{}) or {}).items())
    existing  = ', '.join(tickers)
    constraint = user_prompt.strip() or \
        "Suggest stocks that complement this AI infrastructure portfolio with best risk-adjusted returns."

    prompt = f"""You are an expert quantitative portfolio analyst.

CURRENT PORTFOLIO:
Holdings: {weighted}
Macro exposure: {macro_str}
Theme: AI Infrastructure, Power & Energy, Enterprise Software

USER REQUEST: {constraint}

TASK: Suggest exactly 5 Sharpe Enhancers and 5 Volatility Reducers.
DO NOT suggest any of: {existing}
All tickers must be valid NYSE/NASDAQ US symbols.

Return ONLY valid JSON (no markdown, no preamble):
{{"portfolio_analysis":"One concise sentence on the portfolio strength and main risk.",
  "sharpe_enhancers":[
    {{"ticker":"NVDA","company":"NVIDIA Corporation","sector":"Semiconductors",
      "rationale":"Why this improves Sharpe","why_now":"Current catalyst",
      "exp_return":0.45,"ann_vol":0.65}}],
  "vol_reducers":[
    {{"ticker":"WMT","company":"Walmart Inc","sector":"Consumer Staples",
      "rationale":"Why this reduces vol","why_now":"Defensive rationale",
      "exp_return":0.08,"ann_vol":0.18}}]}}"""

    try:
        r = req.post(ANTHROPIC_BASE,
            headers={'x-api-key':ANTHROPIC_KEY,'anthropic-version':'2023-06-01',
                     'content-type':'application/json'},
            json={'model':'claude-sonnet-4-6','max_tokens':2000,
                  'messages':[{'role':'user','content':prompt}]}, timeout=30)
        if r.status_code != 200:
            print(f'[Claude] HTTP {r.status_code}')
            return None
        text = r.json()['content'][0]['text']
        s, e = text.find('{'), text.rfind('}') + 1
        return json.loads(text[s:e]) if s >= 0 and e > 0 else None
    except Exception as ex:
        print(f'[Claude] error: {ex}')
        return None


def _enrich_with_impact(claude_result, tickers, weights, data):
    """Scores Claude's picks on real price history. Its own return and vol guesses are discarded."""
    def candidates(items, kind):
        out = []
        for s in items:
            t = s.get('ticker','').upper()
            if t:
                out.append({'ticker': t, 'desc': s.get('company','') + ': ' + s.get('why_now',''),
                            'company': s.get('company',''), 'why_now': s.get('why_now',''),
                            'sector': s.get('sector','Other'), 'rationale': s.get('rationale',''),
                            'type': kind})
        return out

    sharpe_c = candidates(claude_result.get('sharpe_enhancers',[]), 'complement')
    vol_c    = candidates(claude_result.get('vol_reducers',[]),     'diversifier')
    scored, pending = score_candidates(tickers, weights, data, sharpe_c + vol_c)
    return ([x for x in scored if x['type']=='complement'],
            [x for x in scored if x['type']=='diversifier'],
            claude_result.get('portfolio_analysis',''), pending)


def _loading_response(pending):
    eta = md.eta_seconds(len(pending))
    mins = max(1, round(eta / 60))
    return jsonify({'error': f"Loading price history for {', '.join(pending)}. The free data tier allows "
                             f"5 requests a minute, so this takes about {mins} minute{'s' if mins != 1 else ''}. "
                             "Press Analyze again then.",
                    'pending': pending, 'retry_after': eta}), 503


def _parse_targets(raw) -> dict:
    """{TICKER: price} from the request. Keys are uppercased; non-numeric or non-positive values are ignored."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if isinstance(v, bool) or not isinstance(k, str) or not k.strip():
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if np.isfinite(x) and x > 0:
            out[k.strip().upper()] = x
    return out


def _pct(x, nd=2):
    return round(x * 100, nd) if x is not None else None


def _ew_fields(mu, cov, rf):
    r, v, s = equal_weight_stats(mu, cov, rf)
    return {'ew_ret': round(r*100, 1), 'ew_vol': round(v*100, 1), 'ew_sharpe': round(s, 2)}


def _data_note(fetched, data, tickers, cap, shrink, missing):
    rf, ic, n_u = fetched['rf'], fetched['mom_ic'], fetched['mom_universe_n']
    if fetched['mom_active']:
        mom = (f"plus a 12-1 momentum alpha of {ic:.3f} x residual vol x z-score, where momentum is ranked within "
               f"the analyzer's {n_u}-name watchlist, not the whole market")
        if ic < pe.IC:
            mom += f" (weight halved because {pe.MARKET}'s own 12-1 return is negative)"
    else:
        mom = (f"with momentum switched off because only {n_u} names in the analyzer's watchlist have a full "
               f"year of history ({pe.MIN_UNIVERSE} needed), and momentum is ranked within that watchlist, "
               "not the whole market")
    with_target = [t for t in tickers if data[t]['alpha_analyst'] is not None]
    tgt = (f", plus {pe.ANALYST_WEIGHT*100:.0f}% of the gap between your price target (less a "
           f"{pe.ANALYST_BIAS*100:.0f}% optimism haircut) and that anchor for {', '.join(with_target)}"
           if with_target else "")
    cov_txt = (f"Ledoit-Wolf shrinkage toward constant correlation (intensity {shrink:.2f})" if shrink is not None
               else "the sample covariance (too little shared history to shrink)")
    note = (f"Live data: Massive daily closes through {fetched['through']}. Expected return is a CAPM anchor of "
            f"rf {rf*100:.2f}% ({fetched['rf_source']}) plus Blume-adjusted beta x an assumed {ERP*100:.1f}% "
            f"equity risk premium, {mom}{tgt}. Covariance uses {cov_txt} on shared trading days, and no "
            f"position may exceed {cap*100:.0f}%.")
    if missing:
        note += f" Excluded, no price history: {', '.join(missing)}."
    if fetched.get('rejected_targets'):
        note += (" Ignored price targets outside 0.2x to 5x the current price: "
                 f"{', '.join(fetched['rejected_targets'])}.")
    return note


# ── Routes ────────────────────────────────────────────────────────────────────
@api_bp.route('/analyze', methods=['POST'])
def analyze():
    body     = request.get_json(force=True)
    tickers  = [t.strip().upper() for t in body.get('tickers', [])]
    capital  = float(body.get('capital', 10000))
    biweekly = float(body.get('biweekly', 500))
    mode     = body.get('mode', 'sharpe')
    targets  = _parse_targets(body.get('targets'))

    if len(tickers) < 2:
        return jsonify({'error': 'Add at least 2 tickers.'}), 400

    try:
        fetched = fetch_returns(tickers, targets=targets)
    except md.MassiveError as ex:
        return jsonify({'error': str(ex)}), 502
    if fetched['pending']:
        return _loading_response(fetched['pending'])
    data, missing = fetched['data'], fetched['missing']
    if len(data) < 2:
        msg = 'Fewer than 2 tickers have price history.'
        if missing:
            msg += f" No daily bars found for: {', '.join(missing)}."
        return jsonify({'error': msg}), 400

    tickers  = list(data.keys())
    rf       = fetched['rf']
    mu       = np.array([data[t]['ann_ret'] for t in tickers])
    cov, shrink = build_cov(tickers, data)
    cap      = position_cap(len(tickers))
    try:
        weights = optimize(mu.tolist(), cov, mode, rf)
    except ValueError as ex:
        return jsonify({'error': str(ex)}), 500
    port_ret, port_vol, sharpe = portfolio_stats(weights, mu, cov, rf)
    rc       = risk_contributions(weights, cov)
    hist_dd  = historical_drawdown(tickers, weights, data)
    sectors  = _sectors(tickers)
    exposure = _exposure(tickers, weights, sectors)

    positions = []
    for i, t in enumerate(tickers):
        d = data[t]
        positions.append({
            'ticker':          t,
            'weight':          round(weights[i]*100, 1),
            'dollars':         round(weights[i]*capital, 2),
            'price':           round(d['price'], 2),
            'price_date':      d['price_date'],
            'beta':            round(d['beta'], 3),
            'beta_raw':        round(d['beta_raw'], 3) if d['beta_raw'] is not None else None,
            'beta_note':       d['beta_note'],
            'anchor_return':   _pct(d['anchor']),
            'capm_return':     _pct(d['anchor']),
            'alpha_mom':       _pct(d['alpha_mom']),
            'alpha_analyst':   _pct(d['alpha_analyst']),
            'mom_12_1':        _pct(d['mom_12_1'], 1),
            'mom_z':           round(d['mom_z'], 2) if d['mom_z'] is not None else None,
            'resid_vol':       _pct(d['resid_vol'], 1),
            'analyst_target':  round(d['analyst_target'], 2) if d['analyst_target'] is not None else None,
            'analyst_implied': _pct(d['analyst_implied'], 1),
            'blended_return':  _pct(d['ann_ret']),
            'ann_ret':         _pct(d['ann_ret']),
            'return_source':   d['return_source'],
            'trailing_ret':    _pct(d['trailing_12m'], 1),
            'ann_vol':         _pct(d['ann_vol'], 1),
            'sharpe':          round(d['sharpe'], 2),
            'rc_pct':          round(rc[i]*100, 1),
            'data_source':     d['data_source'],
        })

    return jsonify({
        'tickers':   tickers,
        'weights':   [round(w*100,1) for w in weights],
        'positions': positions,
        'portfolio': {**portfolio_summary(port_ret, port_vol, sharpe, hist_dd), **_ew_fields(mu, cov, rf)},
        'frontier':  efficient_frontier(mu.tolist(), cov),
        'mc_paths':  monte_carlo(port_ret, port_vol, capital),
        'scenarios': scenario_projections(tickers, weights, capital, biweekly, data, rf),
        'cov_matrix': cov.tolist(),
        'sectors':   sectors,
        'exposure':  exposure,
        'capital':   capital,
        'biweekly':  biweekly,
        'mode':      mode,
        'is_live':   True,
        'rf':        round(rf*100, 2),
        'erp':       round(ERP*100, 2),
        'cap':       round(cap*100, 1),
        'mom_universe_n': fetched['mom_universe_n'],
        'mom_ic':    fetched['mom_ic'],
        'mom_active': fetched['mom_active'],
        'cov_shrinkage': round(shrink, 3) if shrink is not None else None,
        'missing':   missing,
        'data_note': _data_note(fetched, data, tickers, cap, shrink, missing),
    })


@api_bp.route('/smart', methods=['POST'])
def smart():
    body        = request.get_json(force=True)
    tickers     = [t.strip().upper() for t in body.get('tickers', [])]
    weights     = body.get('weights', [1/max(len(tickers),1)]*len(tickers))
    user_prompt = body.get('user_prompt', '').strip()

    if len(tickers) < 2:
        return jsonify({'error': 'Add at least 2 tickers.'}), 400
    try:
        return _smart_body(tickers, weights, user_prompt, body.get('targets'))
    except md.MassiveError as ex:
        return jsonify({'error': str(ex)}), 502


def _smart_body(tickers, weights, user_prompt, raw_targets):
    fetched = fetch_returns(tickers, targets=_parse_targets(raw_targets))
    if fetched['pending']:
        return _loading_response(fetched['pending'])
    data = fetched['data']
    if len(weights) != len(tickers):
        weights = [1/len(tickers)] * len(tickers)
    pairs = [(t, w) for t, w in zip(tickers, weights) if t in data]
    if len(pairs) < 2:
        return jsonify({'error': 'Fewer than 2 tickers have price history.'}), 400
    tickers, weights = [p[0] for p in pairs], [float(p[1]) for p in pairs]
    sectors  = _sectors(tickers)
    exposure = _exposure(tickers, weights, sectors)

    claude_result = _call_claude(tickers, weights, sectors, exposure, user_prompt)

    if claude_result:
        sharpe_e, vol_r, analysis, pending = _enrich_with_impact(claude_result, tickers, weights, data)
        warnings, _ = exposure_warnings(tickers, weights)
        if pending:
            warnings.append(f"Still loading price history for {', '.join(pending)}; "
                            "those picks appear once it arrives.")
        return jsonify({
            'sharpe_enhancers':   sharpe_e,
            'vol_reducers':       vol_r,
            'warnings':           warnings,
            'portfolio_analysis': analysis,
            'powered_by':         'claude',
        })

    result = smart_suggestions_v2(tickers, weights, data)
    if result.get('pending'):
        result['warnings'].append(f"Still loading price history for {', '.join(result['pending'])}; "
                                  "those candidates appear once it arrives.")
    result['powered_by']         = 'database'
    result['portfolio_analysis'] = ''
    return jsonify(result)


@api_bp.route('/recalculate', methods=['POST'])
def recalculate():
    """
    Re-run optimizer and scenarios with user-overridden expected returns.
    Accepts the covariance matrix and betas from the prior analyze call to avoid re-fetching data.
    Each stock's scenario alpha is its override minus its CAPM anchor (rf + beta x ERP).
    """
    body        = request.get_json(force=True)
    tickers     = [t.strip().upper() for t in body.get('tickers', [])]
    overrides   = body.get('returns', {})     # {ticker: pct e.g. 45.0}
    cov_flat    = body.get('cov_matrix', [])  # from prior analyze response
    betas       = body.get('betas', {})       # adjusted betas from the prior analyze response
    capital     = float(body.get('capital', 10000))
    biweekly    = float(body.get('biweekly', 500))
    mode        = body.get('mode', 'sharpe')

    if not tickers or not cov_flat:
        return jsonify({'error': 'Missing tickers or cov_matrix'}), 400
    lacking = [t for t in tickers if not isinstance(overrides.get(t), (int, float))
               or not isinstance(betas.get(t), (int, float))]
    if lacking:
        return jsonify({'error': f"Missing return estimate or beta for {', '.join(lacking)}. Run Analyze again."}), 400
    bad = [t for t in tickers if overrides[t] <= -100 or not np.isfinite(overrides[t])]
    if bad:
        return jsonify({'error': f"Return estimates must be above -100%: {', '.join(bad)}."}), 400

    try:
        rf, _ = current_rf()
    except md.MassiveError as ex:
        return jsonify({'error': str(ex)}), 502

    try:
        cov = np.array(cov_flat, dtype=float)
        mu  = np.array([overrides[t] / 100.0 for t in tickers])
        weights  = optimize(mu.tolist(), cov, mode, rf)
        port_ret, port_vol, sharpe = portfolio_stats(weights, mu, cov, rf)

        # Minimal data dict for scenario_projections: beta and the alpha implied by the override
        data_stub = {t: {'beta': float(betas[t]), 'alpha': float(mu[i] - (rf + float(betas[t]) * ERP))}
                     for i, t in enumerate(tickers)}

        return jsonify({
            'tickers':   tickers,
            'weights':   [round(w*100,1) for w in weights],
            'portfolio': {**portfolio_summary(port_ret, port_vol, sharpe), **_ew_fields(mu, cov, rf)},
            'frontier':  efficient_frontier(mu.tolist(), cov),
            'mc_paths':  monte_carlo(port_ret, port_vol, capital),
            'scenarios': scenario_projections(tickers, weights, capital, biweekly, data_stub, rf),
            'rf':        round(rf*100, 2),
            'rc':        risk_contributions(weights, cov),
            'exposure':  _exposure(tickers, weights, _sectors(tickers)),
        })
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500

@api_bp.route('/market-data', methods=['GET'])
def market_data():
    """Last close and daily change for the Nasdaq 100 banner, from Massive's daily market summary."""
    NDX50 = ['AAPL','MSFT','NVDA','AMZN','GOOG','META','TSLA','AVGO','NFLX','COST',
             'AMD','QCOM','ADBE','TXN','AMGN','CSCO','SBUX','GILD','PANW','LRCX',
             'AMAT','KLAC','REGN','ADP','BKNG','MRVL','CRWD','DDOG','TEAM','ZS',
             'WDAY','ABNB','FTNT','CDNS','SNPS','ORLY','CTAS','PCAR','MNST','EA',
             'BIIB','IDXX','ANSS','HON','PEP','INTC','MDLZ','ADI','VRTX','FISV']

    try:
        sessions = md.last_two_sessions()
    except md.MassiveError as ex:
        return jsonify({'tickers': [], 'error': str(ex)}), 200
    if not sessions:
        return jsonify({'tickers': [], 'error': 'Daily summary not available yet'}), 200
    curr = sessions[0][1]
    prev = sessions[1][1] if len(sessions) > 1 else {}
    result = []
    for t in NDX50:
        c = curr.get(t)
        if not c or not c.get('c'):
            continue
        p = (prev.get(t) or {}).get('c') or c.get('o')
        result.append({'ticker': t, 'price': round(c['c'], 2),
                       'change': round((c['c'] - p) / p * 100, 2), 'prev': round(p, 2)})
    return jsonify({'tickers': result, 'as_of': sessions[0][0].isoformat()})


@api_bp.route('/debug', methods=['GET'])
def debug():
    """Massive connection status and what is in the price cache."""
    key_set = bool(os.environ.get('MASSIVE_API_KEY', '').strip())
    rows = ''.join(
        f"<tr><td>{c['ticker']}</td><td>{c['n']}</td><td>{c['first']} → {c['last']}</td>"
        f"<td>{c['fetched_at']}</td><td style='color:{'#4ade80' if c['fresh'] else '#fbbf24'}'>"
        f"{'fresh' if c['fresh'] else 'stale, refreshing'}</td></tr>" for c in md.cache_status())
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Debug</title>
<style>body{{background:#0d0d13;color:#e8e6f0;font-family:monospace;padding:28px;font-size:13px}}
td,th{{padding:6px 10px;border-bottom:1px solid #2a2040;text-align:left}}</style></head><body>
<h2>Massive data status</h2>
<p>MASSIVE_API_KEY: {'set' if key_set else '<b style="color:#f87171">missing, add it in Railway Variables</b>'}<br>
Calls in the last minute: {md.calls_last_minute()} of {md._calls_per_min() or 'unlimited'}<br>
Expected latest session: {md.expected_last_session()}<br>Cache folder: {md.CACHE_DIR}<br>
Momentum universe: {len(momentum_universe())} cached names with a 12-1 return ({pe.MIN_UNIVERSE} needed)</p>
<table><tr><th>Ticker</th><th>Bars</th><th>Range</th><th>Fetched</th><th>State</th></tr>{rows}</table>
</body></html>"""
    return html, 200, {'Content-Type': 'text/html'}
