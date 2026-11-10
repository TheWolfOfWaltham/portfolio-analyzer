from flask import Blueprint, request, jsonify
import sys, os, json, requests as req
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio_engine import (fetch_returns, build_cov, optimize, efficient_frontier,
                               monte_carlo, risk_contributions, portfolio_stats,
                               scenario_projections, smart_suggestions_v2, score_candidates,
                               exposure_warnings)
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
                out.append({'ticker': t, 'desc': s.get('company','') + ' — ' + s.get('why_now',''),
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


# ── Routes ────────────────────────────────────────────────────────────────────
@api_bp.route('/analyze', methods=['POST'])
def analyze():
    body     = request.get_json(force=True)
    tickers  = [t.strip().upper() for t in body.get('tickers', [])]
    capital  = float(body.get('capital', 10000))
    biweekly = float(body.get('biweekly', 500))
    mode     = body.get('mode', 'sharpe')

    if len(tickers) < 2:
        return jsonify({'error': 'Add at least 2 tickers.'}), 400

    try:
        fetched = fetch_returns(tickers)
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
    mu       = np.array([data[t]['ann_ret'] for t in tickers])
    cov      = build_cov(tickers, data)
    weights  = optimize(mu.tolist(), cov, mode)
    port_ret, port_vol, sharpe = portfolio_stats(weights, mu, cov)
    rc       = risk_contributions(weights, cov)
    sectors  = _sectors(tickers)
    exposure = _exposure(tickers, weights, sectors)

    data_note = (f"Live data: Massive daily closes through {fetched['through']}. Vol, beta and covariance "
                 f"from real returns on shared trading days. Returns = {data[tickers[0]]['return_source']}.")
    if missing:
        data_note += f" Excluded, no price history: {', '.join(missing)}."

    positions = [{
        'ticker':          t,
        'weight':          round(weights[i]*100, 1),
        'dollars':         round(weights[i]*capital, 2),
        'price':           data[t]['price'],
        'beta':            data[t]['beta'],
        'capm_return':     data[t]['capm_return'],
        'analyst_target':  data[t].get('analyst_target'),
        'analyst_implied': data[t].get('analyst_implied'),
        'blended_return':  data[t].get('blended_return', data[t]['capm_return']),
        'return_source':   data[t].get('return_source', 'CAPM only'),
        'ann_ret':         data[t].get('blended_return', data[t]['capm_return']),
        'trailing_ret':    data[t].get('trailing_ret', 0),
        'ann_vol':         round(data[t]['ann_vol']*100, 1),
        'sharpe':          round(data[t]['sharpe'], 2),
        'rc_pct':          round(rc[i]*100, 1),
        'data_source':     data[t].get('data_source',''),
    } for i, t in enumerate(tickers)]

    return jsonify({
        'tickers':   tickers,
        'weights':   [round(w*100,1) for w in weights],
        'positions': positions,
        'portfolio': {
            'ann_ret':       round(port_ret*100,1),
            'ann_vol':       round(port_vol*100,1),
            'sharpe':        round(sharpe,2),
            'port_3yr_geom': round(((1+port_ret-0.5*port_vol**2)**3-1)*100,1),
            'var_95':        round(-1.645*port_vol*100,1),
            'max_dd_est':    round(-2.5*port_vol*100,1),
        },
        'frontier':  efficient_frontier(mu.tolist(), cov),
        'mc_paths':  monte_carlo(port_ret, port_vol, capital),
        'scenarios': scenario_projections(tickers, weights, capital, biweekly, data),
        'cov_matrix': cov.tolist(),
        'sectors':   sectors,
        'exposure':  exposure,
        'capital':   capital,
        'biweekly':  biweekly,
        'mode':      mode,
        'is_live':   True,
        'missing':   missing,
        'data_note': data_note,
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
        fetched = fetch_returns(tickers)
    except md.MassiveError as ex:
        return jsonify({'error': str(ex)}), 502
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
    Accepts the covariance matrix from the prior analyze call to avoid re-fetching data.
    """
    body        = request.get_json(force=True)
    tickers     = [t.strip().upper() for t in body.get('tickers', [])]
    overrides   = body.get('returns', {})     # {ticker: pct e.g. 45.0}
    cov_flat    = body.get('cov_matrix', [])  # from prior analyze response
    betas       = body.get('betas', {})
    capital     = float(body.get('capital', 10000))
    biweekly    = float(body.get('biweekly', 500))
    mode        = body.get('mode', 'sharpe')

    if not tickers or not cov_flat:
        return jsonify({'error': 'Missing tickers or cov_matrix'}), 400

    try:
        cov = np.array(cov_flat)
        mu  = np.array([overrides.get(t, 10.0) / 100.0 for t in tickers])

        weights  = optimize(mu.tolist(), cov, mode)
        port_ret, port_vol, sharpe = portfolio_stats(weights, mu, cov)
        rc = risk_contributions(weights, cov)

        # Reconstruct minimal data dict for scenario_projections (needs beta)
        data_stub = {t: {'ann_ret': mu[i], 'ann_vol': 0.5,
                         'beta': betas.get(t, 1.0), 'returns': [0]*252}
                     for i, t in enumerate(tickers)}

        return jsonify({
            'tickers':   tickers,
            'weights':   [round(w*100,1) for w in weights],
            'portfolio': {
                'ann_ret':       round(port_ret*100,1),
                'ann_vol':       round(port_vol*100,1),
                'sharpe':        round(sharpe,2),
                'port_3yr_geom': round(((1+port_ret-0.5*port_vol**2)**3-1)*100,1),
                'var_95':        round(-1.645*port_vol*100,1),
                'max_dd_est':    round(-2.5*port_vol*100,1),
            },
            'frontier':  efficient_frontier(mu.tolist(), cov),
            'mc_paths':  monte_carlo(port_ret, port_vol, capital),
            'scenarios': scenario_projections(tickers, weights, capital, biweekly, data_stub),
            'rc':        risk_contributions(weights, cov),
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
<p>MASSIVE_API_KEY: {'set' if key_set else '<b style="color:#f87171">missing — add it in Railway Variables</b>'}<br>
Calls in the last minute: {md.calls_last_minute()} of {md._calls_per_min() or 'unlimited'}<br>
Expected latest session: {md.expected_last_session()}<br>Cache folder: {md.CACHE_DIR}</p>
<table><tr><th>Ticker</th><th>Bars</th><th>Range</th><th>Fetched</th><th>State</th></tr>{rows}</table>
</body></html>"""
    return html, 200, {'Content-Type': 'text/html'}


@api_bp.route('/fmp-test', methods=['GET'])
def fmp_test():
    import os, requests as req
    fh_key = os.environ.get("FINNHUB_API_KEY","").strip()
    fmp_key = os.environ.get("FMP_API_KEY","").strip()
    out = [f"FINNHUB_API_KEY: {'SET (' + fh_key[:8] + '...)' if fh_key else 'NOT SET'}",
           f"FMP_API_KEY: {'SET (' + fmp_key[:8] + '...)' if fmp_key else 'NOT SET'}", ""]
    if fh_key:
        try:
            r = req.get(f"https://finnhub.io/api/v1/stock/price-target",
                        params={"symbol":"AAPL","token":fh_key}, timeout=8)
            out.append(f"Finnhub AAPL test: HTTP {r.status_code}")
            out.append(r.text[:300])
        except Exception as ex:
            out.append(f"Finnhub error: {ex}")
    return "<pre>" + "\n".join(out) + "</pre>", 200
