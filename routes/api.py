from flask import Blueprint, request, jsonify
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio_engine import (fetch_returns, build_cov, optimize, efficient_frontier,
                               monte_carlo, correlation_matrix, risk_contributions,
                               portfolio_stats, scenario_projections, smart_suggestions)
import numpy as np

api_bp = Blueprint("api", __name__)

SECTOR_MAP = {
    "GLW":"AI Infra Optical","SNDK":"Semiconductors","NBIS":"AI Cloud Infra",
    "GEV":"Power Infra","MRVL":"Custom ASIC","COHR":"Optical Transceivers",
    "ANET":"AI Networking","VST":"Power Generation","NOW":"Enterprise SaaS",
    "CEG":"Nuclear Power","MU":"Semiconductors","AVGO":"Semiconductors",
    "WMT":"Consumer Staples","JPM":"Financials","JNJ":"Healthcare",
    "BRK/B":"Conglomerate","PG":"Consumer Staples","SOFI":"Fintech",
    "CRWD":"Cybersecurity","NEE":"Utilities","LITE":"AI Infra Optical","ETR":"Utility",
}
SECTOR_COLORS = {
    "Semiconductors":"#e65100","AI Cloud Infra":"#2e7d32","AI Infra Optical":"#1565c0",
    "Power Infra":"#b71c1c","Custom ASIC":"#4a148c","Optical Transceivers":"#00695c",
    "AI Networking":"#1a237e","Power Generation":"#1b5e20","Enterprise SaaS":"#4e342e",
    "Nuclear Power":"#880e4f","Financials":"#0d47a1","Consumer Staples":"#558b2f",
    "Healthcare":"#006064","Conglomerate":"#37474f","Fintech":"#f57f17",
    "Cybersecurity":"#4a148c","Utilities":"#006064","Utility":"#33691e","Other":"#78909c",
}

def _sectors(tickers):
    return {t: {"sector": SECTOR_MAP.get(t,"Other"),
                "color":  SECTOR_COLORS.get(SECTOR_MAP.get(t,"Other"), "#78909c")}
            for t in tickers}


@api_bp.route("/analyze", methods=["POST"])
def analyze():
    body     = request.get_json(force=True)
    tickers  = [t.strip().upper() for t in body.get("tickers", [])]
    capital  = float(body.get("capital", 10000))
    biweekly = float(body.get("biweekly", 500))
    mode     = body.get("mode", "sharpe")

    if len(tickers) < 2:
        return jsonify({"error": "Add at least 2 tickers."}), 400

    data, is_live = fetch_returns(tickers)

    if len(data) < 2:
        return jsonify({"error": "Could not load data for these tickers."}), 400

    tickers = list(data.keys())
    mu  = np.array([data[t]["ann_ret"] for t in tickers])
    cov = build_cov(tickers, data)

    weights   = optimize(mu.tolist(), cov, mode)
    port_ret, port_vol, sharpe = portfolio_stats(weights, mu, cov)

    positions = [{
        "ticker":  t,
        "weight":  round(weights[i]*100, 1),
        "dollars": round(weights[i]*capital, 2),
        "price":   data[t]["price"],
        "ann_ret": round(data[t]["ann_ret"]*100, 1),
        "ann_vol": round(data[t]["ann_vol"]*100, 1),
        "sharpe":  round(data[t]["sharpe"], 2),
        "rc_pct":  round(risk_contributions(weights, cov)[i]*100, 1),
    } for i, t in enumerate(tickers)]

    return jsonify({
        "tickers":   tickers,
        "weights":   [round(w*100, 1) for w in weights],
        "positions": positions,
        "portfolio": {
            "ann_ret":       round(port_ret*100, 1),
            "ann_vol":       round(port_vol*100, 1),
            "sharpe":        round(sharpe, 2),
            "port_3yr_geom": round(((1+port_ret-0.5*port_vol**2)**3-1)*100, 1),
            "var_95":        round(-1.645*port_vol*100, 1),
            "max_dd_est":    round(-2.5*port_vol*100, 1),
        },
        "frontier":  efficient_frontier(mu.tolist(), cov),
        "mc_paths":  monte_carlo(port_ret, port_vol, capital),
        "corr":      correlation_matrix(tickers, data),
        "rc":        risk_contributions(weights, cov),
        "scenarios": scenario_projections(tickers, weights, capital, biweekly, data),
        "sectors":   _sectors(tickers),
        "capital":   capital,
        "biweekly":  biweekly,
        "mode":      mode,
        "is_live":   is_live,
        "data_note": "Live Alpaca data" if is_live else
                     "Simulated data — calibrated to known return/vol priors. "
                     "Live data loads when running locally with valid Alpaca credentials.",
    })


@api_bp.route("/smart", methods=["POST"])
def smart():
    body    = request.get_json(force=True)
    tickers = [t.strip().upper() for t in body.get("tickers", [])]
    weights = body.get("weights", [1/max(len(tickers),1)]*len(tickers))
    result  = smart_suggestions(tickers, weights, {})
    return jsonify(result)
