from flask import Blueprint, request, jsonify
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio_engine import (fetch_returns, build_cov, optimize, efficient_frontier,
                               monte_carlo, risk_contributions, portfolio_stats,
                               scenario_projections, smart_suggestions_v2)
import numpy as np

api_bp = Blueprint('api', __name__)

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
    # Group 1 — AI Optical — near-black navy
    'AI Infra Optical':'#111827', 'Optical Transceivers':'#0f1a2e',
    # Group 2 — AI Compute — dark charcoal
    'Semiconductors':'#1a1a1a', 'AI Cloud Infra':'#1c1c22',
    # Group 3 — ASIC/Networking — vantablack violet
    'Custom ASIC':'#160d38', 'AI Networking':'#130b30',
    # Group 4 — Power — near-black crimson
    'Power Infra':'#200808', 'Power Generation':'#240a0a', 'Nuclear Power':'#1a0606',
    # Group 5 — SaaS/Fintech — near-black amber
    'Enterprise SaaS':'#1e1205', 'Fintech':'#1a1005', 'Cybersecurity':'#151020',
    # Group 6 — Defensive — near-black forest
    'Consumer Staples':'#0a1a0e', 'Financials':'#0a100e',
    'Healthcare':'#0c120f', 'Conglomerate':'#101010',
    'Utilities':'#0d150d', 'Utility':'#141414', 'Other':'#131313',
}
MACRO_COLORS = {
    'AI Compute':       '#1a1a1a',
    'AI Infrastructure':'#111827',
    'Power & Energy':   '#200808',
    'Growth/SaaS':      '#1e1205',
    'Defensive':        '#0a1a0e',
    'Other':            '#160d38',
}
MACRO_BUCKET = {
    'Semiconductors':'AI Compute','AI Cloud Infra':'AI Compute',
    'AI Infra Optical':'AI Infrastructure','Optical Transceivers':'AI Infrastructure',
    'AI Networking':'AI Infrastructure','Custom ASIC':'AI Infrastructure',
    'Power Infra':'Power & Energy','Power Generation':'Power & Energy','Nuclear Power':'Power & Energy',
    'Enterprise SaaS':'Growth/SaaS','Fintech':'Growth/SaaS','Cybersecurity':'Growth/SaaS',
    'Consumer Staples':'Defensive','Healthcare':'Defensive','Conglomerate':'Defensive',
    'Financials':'Defensive','Utilities':'Defensive','Utility':'Defensive','Other':'Other',
}

def _sectors(tickers):
    out = {}
    for t in tickers:
        sec = SECTOR_MAP.get(t,'Other')
        out[t] = {
            'sector': sec,
            'color': SECTOR_COLORS.get(sec,'#5a5270'),
            'macro': MACRO_BUCKET.get(sec,'Other'),
            'macro_color': MACRO_COLORS.get(MACRO_BUCKET.get(sec,'Other'),'#5a5270'),
        }
    return out

def _exposure(tickers, weights, sectors):
    macro = {}
    sub   = {}
    for t, w in zip(tickers, weights):
        s = sectors[t]
        m = s['macro']
        sec = s['sector']
        macro[m] = macro.get(m,0) + w*100
        sub[sec]  = sub.get(sec,0)  + w*100
    return {
        'macro': {k: round(v,1) for k,v in sorted(macro.items(), key=lambda x:-x[1])},
        'sub':   {k: round(v,1) for k,v in sorted(sub.items(),   key=lambda x:-x[1])},
        'macro_colors': {m: MACRO_COLORS.get(m,'#5a5270') for m in macro},
        'sub_colors':   {s: SECTOR_COLORS.get(s,'#5a5270') for s in sub},
    }

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
                     'Simulated data — calibrated to real return/vol priors. Live data loads with valid Alpaca credentials.',
    })

@api_bp.route('/smart', methods=['POST'])
def smart():
    body    = request.get_json(force=True)
    tickers = [t.strip().upper() for t in body.get('tickers', [])]
    weights = body.get('weights', [1/max(len(tickers),1)]*len(tickers))
    data, _ = fetch_returns(tickers) if tickers else ({}, False)
    result  = smart_suggestions_v2(tickers, weights, data)
    return jsonify(result)
