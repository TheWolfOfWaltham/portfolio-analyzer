from flask import Blueprint, request, jsonify
import sys, os, json, requests as req
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio_engine import (fetch_returns, build_cov, optimize, efficient_frontier,
                               monte_carlo, risk_contributions, portfolio_stats,
                               scenario_projections, smart_suggestions_v2,
                               marginal_impact, _simulated_returns, TICKER_PRIORS,
                               DEFAULT_PRIOR)
from dotenv import load_dotenv
import numpy as np

load_dotenv()
api_bp = Blueprint('api', __name__)

# ── Colour / sector maps ──────────────────────────────────────────────────────
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
ANTHROPIC_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_BASE = 'https://api.anthropic.com/v1/messages'

def _call_claude(tickers, weights, sectors, exposure, user_prompt=''):
    """
    Call Claude claude-sonnet-4-6 to generate stock suggestions.
    Returns parsed dict or None on failure.
    """
    if not ANTHROPIC_KEY:
        return None

    weighted = ', '.join(f"{t} ({w*100:.1f}%)" for t,w in zip(tickers,weights))
    macro_str = ', '.join(f"{k}: {v}%" for k,v in (exposure.get('macro',{}) or {}).items())
    existing  = ', '.join(tickers)
    constraint = user_prompt.strip() or (
        "Suggest stocks that complement this AI infrastructure portfolio. "
        "Prioritise high Sharpe ratio picks and uncorrelated diversifiers."
    )

    prompt = f"""You are an expert quantitative portfolio analyst with deep knowledge of US equity markets.

CURRENT PORTFOLIO:
Holdings: {weighted}
Macro exposure: {macro_str}
Theme: AI Infrastructure, Power & Energy, Enterprise Software

USER REQUEST: {constraint}

TASK: Suggest exactly 5 Sharpe Enhancers and exactly 5 Volatility Reducers.
- Sharpe Enhancers: stocks with strong risk-adjusted return that complement or extend the portfolio theme
- Vol Reducers: low-beta, low-correlation, defensive stocks that reduce drawdown risk
- DO NOT suggest any of these existing holdings: {existing}
- All tickers must be valid NYSE/NASDAQ-listed US stock symbols
- Use realistic forward-looking estimates based on fundamentals and market position

Return ONLY valid JSON with no markdown fences, no explanation outside the JSON:
{{
  "portfolio_analysis": "One concise sentence on the portfolio's key strength and main risk.",
  "sharpe_enhancers": [
    {{
      "ticker": "NVDA",
      "company": "NVIDIA Corporation",
      "sector": "Semiconductors",
      "rationale": "Why this improves portfolio Sharpe — be specific",
      "why_now": "Current catalyst or structural thesis",
      "exp_return": 0.45,
      "ann_vol": 0.65
    }}
  ],
  "vol_reducers": [
    {{
      "ticker": "WMT",
      "company": "Walmart Inc",
      "sector": "Consumer Staples",
      "rationale": "Why this reduces portfolio volatility",
      "why_now": "Defensive rationale or catalyst",
      "exp_return": 0.08,
      "ann_vol": 0.18
    }}
  ]
}}"""

    try:
        r = req.post(
            ANTHROPIC_BASE,
            headers={
                'x-api-key': ANTHROPIC_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': 'claude-sonnet-4-6',
                'max_tokens': 2000,
                'messages': [{'role': 'user', 'content': prompt}],
            },
            timeout=30,
        )
        if r.status_code != 200:
            print(f'[Claude] HTTP {r.status_code}: {r.text[:200]}')
            return None
        text = r.json()['content'][0]['text']
        s, e = text.find('{'), text.rfind('}') + 1
        if s < 0 or e <= 0: return None
        return json.loads(text[s:e])
    except Exception as ex:
        print(f'[Claude] error: {ex}')
        return None


def _enrich_with_impact(claude_result, tickers, weights, data):
    """
    Take Claude's suggestions, fetch Alpaca data for each,
    run marginal_impact(), and return enriched card dicts.
    """
    def enrich_list(items, item_type):
        out = []
        for s in items:
            t = s.get('ticker','').upper()
            if not t: continue
            ann_r = s.get('exp_return', 0.15)
            ann_v = s.get('ann_vol',    0.40)
            # Fetch live data for this ticker
            cand_live, _ = fetch_returns([t]) if t else ({}, False)
            if t in cand_live:
                cand_data = cand_live[t]
            else:
                cand_data = {
                    'returns': _simulated_returns(t).tolist(),
                    'ann_ret': ann_r, 'ann_vol': ann_v,
                    'price':   TICKER_PRIORS.get(t, DEFAULT_PRIOR)[2],
                    'sharpe':  round((ann_r - 0.045) / ann_v, 3) if ann_v else 0,
                }
            # Marginal impact
            if data and len(data) >= 2:
                impact = marginal_impact(tickers, weights, data, t, cand_data)
            else:
                impact = {
                    'sharpe_delta': round((ann_r - 0.045) / ann_v * 0.05, 3) if ann_v else 0,
                    'vol_delta': 0.0, 'ret_delta': round(ann_r * 0.05 * 100, 2),
                    'corr_to_book': 0.25 if item_type == 'complement' else 0.08,
                    'new_sharpe': 0, 'new_vol': 0, 'new_ret': 0,
                }
            out.append({
                'ticker':       t,
                'desc':         s.get('company','') + ' — ' + s.get('why_now',''),
                'sector':       s.get('sector', 'Other'),
                'rationale':    s.get('rationale',''),
                'exp_return':   ann_r,
                'ann_vol':      ann_v,
                'type':         item_type,
                **impact,
            })
        return out

    return (
        enrich_list(claude_result.get('sharpe_enhancers',[]), 'complement'),
        enrich_list(claude_result.get('vol_reducers',[]),     'diversifier'),
        claude_result.get('portfolio_analysis',''),
    )


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
        return jsonify({'error': 'Could not load data for these tickers.'}), 400

    tickers  = list(data.keys())
    mu       = np.array([data[t]['ann_ret'] for t in tickers])
    cov      = build_cov(tickers, data)
    weights  = optimize(mu.tolist(), cov, mode)
    port_ret, port_vol, sharpe = portfolio_stats(weights, mu, cov)
    rc       = risk_contributions(weights, cov)
    sectors  = _sectors(tickers)
    exposure = _exposure(tickers, weights, sectors)

    positions = [{
        'ticker':  t,
        'weight':  round(weights[i]*100, 1),
        'dollars': round(weights[i]*capital, 2),
        'price':   data[t]['price'],
        'ann_ret': round(data[t]['ann_ret']*100, 1),
        'ann_vol': round(data[t]['ann_vol']*100, 1),
        'sharpe':  round(data[t]['sharpe'], 2),
        'rc_pct':  round(rc[i]*100, 1),
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
        'sectors':   sectors,
        'exposure':  exposure,
        'capital':   capital,
        'biweekly':  biweekly,
        'mode':      mode,
        'is_live':   is_live,
        'data_note': 'Live Alpaca market data' if is_live else
                     'Simulated data — calibrated to real return/vol priors.',
    })


@api_bp.route('/smart', methods=['POST'])
def smart():
    body        = request.get_json(force=True)
    tickers     = [t.strip().upper() for t in body.get('tickers', [])]
    weights     = body.get('weights', [1/max(len(tickers),1)]*len(tickers))
    user_prompt = body.get('user_prompt', '').strip()

    data, _ = fetch_returns(tickers) if tickers else ({}, False)

    # Build sector / exposure summaries for Claude
    sectors  = _sectors(tickers) if tickers else {}
    exposure = _exposure(tickers, weights, sectors) if tickers else {}

    # ── Try Claude first ──────────────────────────────────────────────────────
    claude_result = _call_claude(tickers, weights, sectors, exposure, user_prompt)

    if claude_result:
        sharpe_e, vol_r, analysis = _enrich_with_impact(claude_result, tickers, weights, data)
        # Compute warnings using existing logic
        fallback = smart_suggestions_v2(tickers, weights, data)
        return jsonify({
            'sharpe_enhancers':   sharpe_e,
            'vol_reducers':       vol_r,
            'warnings':           fallback.get('warnings', []),
            'portfolio_analysis': analysis,
            'powered_by':         'claude',
            'ai_weight_pct':      fallback.get('ai_weight_pct', 0),
        })

    # ── Fallback: hardcoded DB ────────────────────────────────────────────────
    result = smart_suggestions_v2(tickers, weights, data)
    result['powered_by'] = 'database'
    result['portfolio_analysis'] = ''
    return jsonify(result)
