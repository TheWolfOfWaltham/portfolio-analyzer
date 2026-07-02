from flask import Blueprint, request, jsonify
import sys, os, json, requests as req
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio_engine import (fetch_returns, build_cov, optimize, efficient_frontier,
                               monte_carlo, risk_contributions, portfolio_stats,
                               scenario_projections, smart_suggestions_v2,
                               marginal_impact, _simulated_returns, _fetch_alpaca,
                               TICKER_PRIORS, DEFAULT_PRIOR, RF, ERP,
                               CAPM_WEIGHT, MOMENTUM_WEIGHT, ANALYST_WEIGHT)
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
    def enrich(items, kind):
        out = []
        for s in items:
            t = s.get('ticker','').upper()
            if not t: continue
            ann_r = s.get('exp_return', 0.15)
            ann_v = s.get('ann_vol',    0.40)
            _, prior_vol, prior_price = TICKER_PRIORS.get(t, DEFAULT_PRIOR)
            cand_data = {
                'returns':  _simulated_returns(t).tolist(),
                'ann_ret':  RF + 1.0 * ERP,   # CAPM with beta=1 for candidates
                'ann_vol':  ann_v,
                'beta':     1.0,
                'price':    prior_price,
                'sharpe':   round((RF + ERP - RF) / ann_v, 3) if ann_v else 0,
            }
            impact = (marginal_impact(tickers, weights, data, t, cand_data)
                      if data and len(data) >= 2
                      else {'sharpe_delta':0,'vol_delta':0,'ret_delta':0,
                             'corr_to_book':0.25,'new_sharpe':0,'new_vol':0,'new_ret':0})
            out.append({
                'ticker': t, 'desc': s.get('company','') + ' — ' + s.get('why_now',''),
                'sector': s.get('sector','Other'), 'rationale': s.get('rationale',''),
                'exp_return': ann_r, 'ann_vol': ann_v, 'type': kind, **impact,
            })
        return out

    return (enrich(claude_result.get('sharpe_enhancers',[]), 'complement'),
            enrich(claude_result.get('vol_reducers',[]),     'diversifier'),
            claude_result.get('portfolio_analysis',''))


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

    data, is_live = fetch_returns(tickers)
    if len(data) < 2:
        return jsonify({'error': 'Could not load data.'}), 400

    tickers  = list(data.keys())
    mu       = np.array([data[t]['ann_ret'] for t in tickers])
    cov      = build_cov(tickers, data)
    weights  = optimize(mu.tolist(), cov, mode)
    port_ret, port_vol, sharpe = portfolio_stats(weights, mu, cov)
    rc       = risk_contributions(weights, cov)
    sectors  = _sectors(tickers)
    exposure = _exposure(tickers, weights, sectors)

    live_sources = {t: data[t].get('data_source','') for t in tickers}
    any_prior = any('PRIOR' in v for v in live_sources.values())
    data_note = ('Live data: vol/beta from price bars, returns = 30% CAPM + 40% momentum + 30% analyst (Finnhub)'
                 if is_live and not any_prior
                 else 'Partial live data — blended returns where available, CAPM fallback for missing tickers'
                 if is_live
                 else 'Simulated — add FINNHUB_API_KEY + yfinance/Alpaca keys to Railway for live data')

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
        'is_live':   is_live,
        'data_note': data_note,
    })


@api_bp.route('/smart', methods=['POST'])
def smart():
    body        = request.get_json(force=True)
    tickers     = [t.strip().upper() for t in body.get('tickers', [])]
    weights     = body.get('weights', [1/max(len(tickers),1)]*len(tickers))
    user_prompt = body.get('user_prompt', '').strip()

    data, _ = fetch_returns(tickers) if tickers else ({}, False)
    sectors  = _sectors(tickers) if tickers else {}
    exposure = _exposure(tickers, weights, sectors) if tickers else {}

    claude_result = _call_claude(tickers, weights, sectors, exposure, user_prompt)

    if claude_result:
        sharpe_e, vol_r, analysis = _enrich_with_impact(claude_result, tickers, weights, data)
        fallback = smart_suggestions_v2(tickers, weights, data)
        return jsonify({
            'sharpe_enhancers':   sharpe_e,
            'vol_reducers':       vol_r,
            'warnings':           fallback.get('warnings', []),
            'portfolio_analysis': analysis,
            'powered_by':         'claude',
        })

    result = smart_suggestions_v2(tickers, weights, data)
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
    """Previous-day OHLCV for Nasdaq 100 banner tickers via Alpaca."""
    NDX50 = ['AAPL','MSFT','NVDA','AMZN','GOOG','META','TSLA','AVGO','NFLX','COST',
             'AMD','QCOM','ADBE','TXN','AMGN','CSCO','SBUX','GILD','PANW','LRCX',
             'AMAT','KLAC','REGN','ADP','BKNG','MRVL','CRWD','DDOG','TEAM','ZS',
             'WDAY','ABNB','FTNT','CDNS','SNPS','ORLY','CTAS','PCAR','MNST','EA',
             'BIIB','IDXX','ANSS','HON','PEP','INTC','MDLZ','ADI','VRTX','FISV']

    ALPACA_KEY_    = os.environ.get('ALPACA_API_KEY', '')
    ALPACA_SECRET_ = os.environ.get('ALPACA_SECRET_KEY', '')

    if not ALPACA_KEY_ or not ALPACA_SECRET_:
        return jsonify({'tickers': [], 'error': 'No Alpaca keys'}), 200

    end   = __import__('datetime').date.today()
    start = end - __import__('datetime').timedelta(days=5)
    try:
        r = __import__('requests').get(
            'https://data.alpaca.markets/v2/stocks/bars',
            headers={'APCA-API-KEY-ID': ALPACA_KEY_,
                     'APCA-API-SECRET-KEY': ALPACA_SECRET_,
                     'Accept': 'application/json'},
            params={'symbols': ','.join(NDX50), 'timeframe': '1Day',
                    'start': start.isoformat(), 'end': end.isoformat(),
                    'limit': 10, 'sort': 'desc'},
            timeout=15
        )
        if r.status_code != 200:
            return jsonify({'tickers': [], 'error': f'Alpaca {r.status_code}'}), 200

        bars = r.json().get('bars', {})
        result = []
        for t in NDX50:
            t_bars = bars.get(t, [])
            if len(t_bars) >= 2:
                prev = t_bars[1]  # previous day (sorted desc)
                curr = t_bars[0]
                chg  = (curr['c'] - prev['c']) / prev['c'] * 100
                result.append({'ticker': t, 'price': round(curr['c'],2),
                                'change': round(chg,2), 'prev': round(prev['c'],2)})
            elif len(t_bars) == 1:
                b = t_bars[0]
                chg = (b['c'] - b['o']) / b['o'] * 100
                result.append({'ticker': t, 'price': round(b['c'],2),
                                'change': round(chg,2), 'prev': round(b['o'],2)})
        return jsonify({'tickers': result})
    except Exception as ex:
        return jsonify({'tickers': [], 'error': str(ex)}), 200


@api_bp.route('/debug', methods=['GET'])
def debug():
    """Shows Alpaca connection status and real computed stats for portfolio tickers."""
    from portfolio_engine import _compute_beta
    PORT = ['GLW','SNDK','NBIS','GEV','MRVL','COHR','ANET','VST','NOW']
    all_t = PORT + ['SPY']
    raw, status = _fetch_alpaca(all_t, days=365)

    spy_bars = raw.get('SPY', [])
    spy_ret  = np.array([])
    if spy_bars and len(spy_bars) >= 30:
        sc      = np.array([b['c'] for b in spy_bars], float)
        spy_ret = np.diff(sc) / sc[:-1]

    rows = []
    for t in PORT:
        bars = raw.get(t, [])
        live = bars and len(bars) >= 30
        if live:
            closes  = np.array([b['c'] for b in bars], float)
            dr      = np.diff(closes) / closes[:-1]
            vol     = float(dr.std() * np.sqrt(252))
            trail   = float((1 + dr.mean())**252 - 1)
            price   = float(closes[-1])
            beta    = _compute_beta(dr, spy_ret) if len(spy_ret) >= 30 else 1.0
            capm    = RF + beta * ERP
            n_bars  = len(bars)
            d_from  = bars[0]['t'][:10]
            d_to    = bars[-1]['t'][:10]
        else:
            _, vol, price = TICKER_PRIORS.get(t, DEFAULT_PRIOR)
            trail  = 0.0; beta = 1.0; capm = RF + ERP
            n_bars = 0; d_from = d_to = 'N/A'
        rows.append(dict(t=t, live=live, n=n_bars, d_from=d_from, d_to=d_to,
                         price=price, vol=vol, beta=beta, capm=capm, trail=trail))

    spy_info = (f"{len(spy_bars)} bars {spy_bars[0]['t'][:10]}→{spy_bars[-1]['t'][:10]}"
                if spy_bars else "NO SPY DATA — beta defaults to 1.0")

    row_html = ''
    for r in rows:
        badge = '<span style="color:#4ade80;font-weight:800">✓ LIVE</span>' if r['live'] \
                else '<span style="color:#f87171;font-weight:800">✗ PRIOR</span>'
        row_html += f"""<tr>
          <td style="font-weight:800;font-size:14px">{r['t']}</td>
          <td>{badge}</td>
          <td style="color:#5a5270">{r['n']} bars ({r['d_from']}→{r['d_to']})</td>
          <td style="color:#e8e6f0">${r['price']:.2f}</td>
          <td style="color:#9b6dff">{r['vol']*100:.1f}%</td>
          <td style="color:#7b8fff">{r['beta']:.2f}</td>
          <td style="color:#4ade80">+{r['capm']*100:.1f}%</td>
          <td style="color:#fbbf24">{r['trail']*100:+.1f}%</td>
        </tr>"""

    ok = 'OK' in status
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Debug</title>
<style>body{{background:#0d0d13;color:#e8e6f0;font-family:monospace;padding:28px;font-size:13px}}
h1{{color:#9b6dff;margin-bottom:8px}}
.status{{background:#16141f;border:1px solid #2a2040;border-radius:8px;padding:12px 16px;margin-bottom:20px;font-size:12px;line-height:1.8}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;padding:8px 10px;color:#5a5270;border-bottom:1px solid #2a2040;font-size:10px;text-transform:uppercase;letter-spacing:.08em}}
td{{padding:9px 10px;border-bottom:0.5px solid rgba(42,32,64,.4)}}
.note{{font-size:11px;color:#5a5270;margin-top:20px;line-height:1.8}}</style></head><body>
<h1>🔬 Alpaca Debug — Wolf//Portfolio</h1>
<div class="status">
<b>Alpaca status:</b> <span style="color:{'#4ade80' if ok else '#f87171'}">{status}</span><br>
<b>SPY for beta:</b> {spy_info}<br>
<b>Keys present:</b> {'✓ ALPACA_API_KEY + ALPACA_SECRET_KEY' if ALPACA_KEY else '✗ Missing — set in Railway Variables'}</div>
<table><thead><tr><th>Ticker</th><th>Source</th><th>Coverage</th>
<th>Price</th><th>Realized Vol</th><th>Beta vs SPY</th>
<th>CAPM Return</th><th>Trailing 1yr</th></tr></thead>
<tbody>{row_html}</tbody></table>
<div class="note">
<b>Vol:</b> daily_std × √252 from real price bars<br>
<b>Beta:</b> OLS regression vs SPY daily returns<br>
<b>CAPM Return:</b> Rf(4.5%) + β × ERP(5.5%) — drives optimizer + Sharpe<br>
<b>Trailing 1yr:</b> informational only, not used in any calculation<br>
If PRIOR shows, Alpaca returned no bars — check status above for HTTP error.
</div></body></html>"""
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
