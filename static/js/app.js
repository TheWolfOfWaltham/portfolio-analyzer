const DEFAULT_TICKERS = ['GLW','SNDK','NBIS','GEV','MRVL','COHR','ANET','VST','NOW'];
const TICKER_COLORS = {
  'GLW':'#6b3aff','SNDK':'#fb923c','NBIS':'#22c55e','GEV':'#f43f5e',
  'MRVL':'#c084ff','COHR':'#2dd4bf','ANET':'#60a5fa','VST':'#a3e635',
  'NOW':'#94a3b8','CEG':'#f59e0b','MU':'#38bdf8','AVGO':'#818cf8',
  'WMT':'#4ade80','JPM':'#facc15','JNJ':'#fb7185','PG':'#86efac',
  'SOFI':'#f97316','CRWD':'#a78bfa','NEE':'#34d399','LITE':'#67e8f9','ETR':'#bef264',
};
const PALETTE = ['#6b3aff','#fb923c','#22c55e','#f43f5e','#c084ff',
                 '#2dd4bf','#60a5fa','#a3e635','#94a3b8','#f59e0b',
                 '#38bdf8','#818cf8','#4ade80','#facc15','#fb7185'];

let tickers = [];
let currentMode = 'sharpe';
let chartInstances = {};

function tickerColor(t, i) { return TICKER_COLORS[t] || PALETTE[i % PALETTE.length]; }

function renderChips() {
  const row = document.getElementById('tickerRow');
  row.querySelectorAll('.ticker-chip').forEach(c => c.remove());
  tickers.forEach((t, i) => {
    const chip = document.createElement('span');
    chip.className = 'ticker-chip';
    chip.style.background = tickerColor(t,i) + '22';
    chip.style.color = tickerColor(t,i);
    chip.style.border = '1px solid ' + tickerColor(t,i) + '55';
    chip.innerHTML = t + '<button onclick="removeTicker(' + i + ')">✕</button>';
    row.insertBefore(chip, document.getElementById('tickerField'));
  });
}

function addTicker(raw) {
  const t = raw.trim().toUpperCase().replace(/[^A-Z0-9.\-/]/g,'');
  if (t && !tickers.includes(t) && tickers.length < 15) tickers.push(t);
  renderChips();
}
function removeTicker(i) { tickers.splice(i,1); renderChips(); }

document.getElementById('tickerField').addEventListener('keydown', e => {
  const v = e.target.value;
  if (e.key==='Enter'||e.key===','||e.key===' ') {
    e.preventDefault();
    if (v.trim()) addTicker(v);
    e.target.value = '';
  } else if (e.key==='Backspace' && !v && tickers.length) {
    tickers.pop(); renderChips();
  }
});
document.getElementById('tickerField').addEventListener('blur', e => {
  if (e.target.value.trim()) { addTicker(e.target.value); e.target.value = ''; }
});

function setMode(btn) {
  document.querySelectorAll('.mode-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentMode = btn.dataset.mode;
}
function loadDefault() { tickers = [...DEFAULT_TICKERS]; renderChips(); }
function clearAll() { tickers = []; renderChips(); }

function showStatus(msg, isErr=false) {
  const bar = document.getElementById('statusBar');
  bar.className = 'status-bar visible' + (isErr ? ' err' : '');
  document.getElementById('statusMsg').textContent = msg;
}
function hideStatus() { document.getElementById('statusBar').className = 'status-bar'; }

async function runAnalysis() {
  if (tickers.length < 2) { showStatus('Add at least 2 tickers.', true); return; }
  showStatus('Fetching market data and running optimization…');
  document.getElementById('analyzeBtn').disabled = true;
  document.getElementById('results').className = '';
  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        tickers,
        capital: +document.getElementById('capital').value,
        biweekly: +document.getElementById('biweekly').value,
        mode: currentMode
      })
    });
    const data = await res.json();
    if (data.error) { showStatus(data.error, true); return; }
    hideStatus();
    renderAll(data);
    document.getElementById('results').className = 'visible';
    document.getElementById('results').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(e) {
    showStatus('Network error — is the Flask server running?', true);
  } finally {
    document.getElementById('analyzeBtn').disabled = false;
  }
}

function renderAll(d) {
  document.getElementById('dataNote').textContent = d.data_note || '';
  renderKPIs(d);
  renderStackedBar(d);
  renderPositionTable(d);
  renderSectorChart(d);
  renderRCChart(d);
  renderFrontier(d);
  renderMonteCarlo(d);
  renderCorrMatrix(d);
  renderScenarios(d);
  renderScenarioTables(d);
}

function destroyChart(id) {
  if (chartInstances[id]) { chartInstances[id].destroy(); delete chartInstances[id]; }
}

function renderKPIs(d) {
  const p = d.portfolio;
  document.getElementById('kpiStrip').innerHTML =
    '<div class="kpi kpi-green"><div class="kpi-label">Exp. Annual Return</div><div class="kpi-val">' + p.ann_ret + '%</div><div class="kpi-sub">forward estimate</div></div>' +
    '<div class="kpi"><div class="kpi-label">Portfolio Volatility</div><div class="kpi-val" style="color:var(--text)">' + p.ann_vol + '%</div><div class="kpi-sub">annualized</div></div>' +
    '<div class="kpi kpi-purple"><div class="kpi-label">Sharpe Ratio</div><div class="kpi-val">' + p.sharpe + '</div><div class="kpi-sub">rf = 4.5%</div></div>' +
    '<div class="kpi kpi-green"><div class="kpi-label">3yr Compounded</div><div class="kpi-val">+' + p.port_3yr_geom + '%</div><div class="kpi-sub">geometric mean</div></div>' +
    '<div class="kpi kpi-red"><div class="kpi-label">VaR 95% (1yr)</div><div class="kpi-val">' + p.var_95 + '%</div><div class="kpi-sub">1-in-20 year</div></div>' +
    '<div class="kpi kpi-red"><div class="kpi-label">Est. Max Drawdown</div><div class="kpi-val">' + p.max_dd_est + '%</div><div class="kpi-sub">2.5\u03c3 stress</div></div>';
}

function renderStackedBar(d) {
  const bar = document.getElementById('stackedBar');
  const legend = document.getElementById('stackedLegend');
  bar.innerHTML = '';
  legend.innerHTML = '';
  const maxW = Math.max(...d.weights);
  d.positions.forEach((p, i) => {
    const col = tickerColor(p.ticker, i);
    const seg = document.createElement('div');
    seg.className = 'seg' + (p.weight < 8 ? ' seg-sm' : '');
    seg.style.cssText = 'width:' + p.weight + '%;background:' + col;
    seg.innerHTML = '<span class="seg-pct">' + p.weight + '%</span><span class="seg-ticker">' + p.ticker + '</span>';
    bar.appendChild(seg);
    const li = document.createElement('div');
    li.className = 'legend-item';
    li.innerHTML = '<div class="legend-dot" style="background:' + col + '"></div>' + p.ticker + ' ' + p.weight + '%';
    legend.appendChild(li);
  });
}

function renderPositionTable(d) {
  document.getElementById('posBody').innerHTML = d.positions.map((p, i) => {
    const col = tickerColor(p.ticker, i);
    const sec = d.sectors[p.ticker] ? d.sectors[p.ticker].sector : 'Other';
    const rcClass = p.rc_pct > 25 ? 'tag-high' : p.rc_pct > 12 ? 'tag-med' : 'tag-low';
    const retColor = p.ann_ret >= 0 ? 'var(--green)' : 'var(--red)';
    return '<tr>' +
      '<td><span class="ticker-cell" style="color:' + col + '">' + p.ticker + '</span></td>' +
      '<td style="color:var(--text-muted);font-size:11px;font-weight:500">' + sec + '</td>' +
      '<td style="font-weight:800">' + p.weight + '%</td>' +
      '<td style="font-family:\'DM Mono\',monospace">$' + p.dollars.toLocaleString() + '</td>' +
      '<td style="font-weight:700;color:' + retColor + '">' + (p.ann_ret >= 0 ? '+' : '') + p.ann_ret + '%</td>' +
      '<td style="font-family:\'DM Mono\',monospace">' + p.ann_vol + '%</td>' +
      '<td style="font-weight:700">' + p.sharpe + '</td>' +
      '<td><span class="tag ' + rcClass + '">' + p.rc_pct + '%</span></td>' +
      '</tr>';
  }).join('');
}

function chartDefaults() {
  return {
    gc: 'rgba(42,32,64,0.6)',
    tc: '#5a5270',
    font: "'Space Grotesk', sans-serif"
  };
}

function renderSectorChart(d) {
  destroyChart('s');
  const sectorMap = {};
  d.positions.forEach(p => {
    const sec = d.sectors[p.ticker] ? d.sectors[p.ticker].sector : 'Other';
    const col = d.sectors[p.ticker] ? d.sectors[p.ticker].color : '#94a3b8';
    if (!sectorMap[sec]) sectorMap[sec] = {weight:0, color:col};
    sectorMap[sec].weight += p.weight;
  });
  const labels = Object.keys(sectorMap);
  const vals = labels.map(k => +sectorMap[k].weight.toFixed(1));
  const cols = labels.map(k => sectorMap[k].color);
  const {tc} = chartDefaults();
  chartInstances['s'] = new Chart(document.getElementById('sectorChart').getContext('2d'), {
    type: 'doughnut',
    data: {labels, datasets: [{data:vals, backgroundColor:cols, borderWidth:2, borderColor:'#16141f'}]},
    options: {responsive:true, maintainAspectRatio:false, cutout:'55%',
      plugins:{legend:{position:'right',labels:{color:tc,font:{size:11,family:"'Space Grotesk', sans-serif"},padding:8,boxWidth:10}},
               tooltip:{callbacks:{label:c => c.label + ': ' + c.parsed.toFixed(1) + '%'}}}}
  });
}

function renderRCChart(d) {
  destroyChart('rc');
  const rc = d.rc.map(v => +(v*100).toFixed(1));
  const colors = d.tickers.map((t,i) => {
    const r = rc[i]; return r > 25 ? '#f87171' : r > 12 ? '#fbbf24' : tickerColor(t,i);
  });
  const {gc,tc} = chartDefaults();
  chartInstances['rc'] = new Chart(document.getElementById('rcChart').getContext('2d'), {
    type: 'bar',
    data: {labels:d.tickers, datasets:[{data:rc, backgroundColor:colors, borderRadius:5}]},
    options: {responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false}, tooltip:{callbacks:{label:c => c.parsed.y.toFixed(1) + '% of portfolio risk'}}},
      scales:{x:{ticks:{color:tc,font:{size:10,family:"'Space Grotesk', sans-serif"}},grid:{display:false}},
              y:{ticks:{color:tc,font:{size:9},callback:v => v + '%'},grid:{color:gc}}}}
  });
}

function renderFrontier(d) {
  destroyChart('f');
  const {gc,tc} = chartDefaults();
  chartInstances['f'] = new Chart(document.getElementById('frontierChart').getContext('2d'), {
    type: 'scatter',
    data:{datasets:[
      {label:'Efficient Frontier', data:d.frontier.map(p => ({x:p.vol,y:p.ret})),
       borderColor:'#6b3aff', backgroundColor:'rgba(107,58,255,0.06)',
       showLine:true, tension:.4, pointRadius:0, borderWidth:2},
      {label:'Your Portfolio', data:[{x:d.portfolio.ann_vol, y:d.portfolio.ann_ret}],
       backgroundColor:'#9b6dff', borderColor:'#9b6dff', pointRadius:10, pointStyle:'star'},
    ]},
    options:{responsive:true, maintainAspectRatio:false,
      plugins:{legend:{labels:{color:tc,font:{size:10,family:"'Space Grotesk', sans-serif"},boxWidth:10}},
               tooltip:{callbacks:{label:c => 'Vol ' + c.parsed.x.toFixed(1) + '% | Ret ' + c.parsed.y.toFixed(1) + '%'}}},
      scales:{x:{title:{display:true,text:'Volatility (%)',color:tc,font:{size:10}},ticks:{color:tc,font:{size:9}},grid:{color:gc}},
              y:{title:{display:true,text:'Return (%)',color:tc,font:{size:10}},ticks:{color:tc,font:{size:9}},grid:{color:gc}}}}
  });
}

function renderMonteCarlo(d) {
  destroyChart('mc');
  const paths = d.mc_paths;
  const labels = Array.from({length:37}, (_,i) => i===0?'Now':i===12?'Yr 1':i===24?'Yr 2':i===36?'Yr 3':'');
  const pct = (arr, p) => { const s = [...arr].sort((a,b)=>a-b); return s[Math.floor(s.length*p)]; };
  const p5  = labels.map((_,t) => Math.round(pct(paths.map(p=>p[t]),.05)));
  const p50 = labels.map((_,t) => Math.round(pct(paths.map(p=>p[t]),.50)));
  const p95 = labels.map((_,t) => Math.round(pct(paths.map(p=>p[t]),.95)));
  const {gc,tc} = chartDefaults();
  const pathDatasets = paths.slice(0,40).map(p => ({
    data:p, borderColor:'rgba(107,58,255,0.07)', borderWidth:0.8, pointRadius:0, fill:false, tension:.3
  }));
  chartInstances['mc'] = new Chart(document.getElementById('mcChart').getContext('2d'), {
    type: 'line',
    data:{labels, datasets:[
      ...pathDatasets,
      {label:'95th pct', data:p95, borderColor:'rgba(74,222,128,.5)', borderWidth:1.5, borderDash:[4,3], pointRadius:0, fill:false},
      {label:'Median',   data:p50, borderColor:'#9b6dff', borderWidth:2.5, pointRadius:0, fill:false},
      {label:'5th pct',  data:p5,  borderColor:'rgba(248,113,113,.5)', borderWidth:1.5, borderDash:[4,3], pointRadius:0, fill:false},
    ]},
    options:{responsive:true, maintainAspectRatio:false,
      plugins:{legend:{labels:{filter:i=>['Median','95th pct','5th pct'].includes(i.text),
                               color:tc,font:{size:10,family:"'Space Grotesk', sans-serif"},boxWidth:10}},
               tooltip:{enabled:false}},
      scales:{x:{ticks:{color:tc,font:{size:9}},grid:{color:gc}},
              y:{ticks:{color:tc,font:{size:9},callback:v=>'$'+Math.round(v/1000)+'K'},grid:{color:gc}}}}
  });
}

function renderCorrMatrix(d) {
  const tix = d.tickers, corr = d.corr;
  const head = '<tr><th></th>' + tix.map(t => '<th>' + t + '</th>').join('') + '</tr>';
  const rows = tix.map((t,i) =>
    '<tr><td class="row-lbl">' + t + '</td>' +
    corr[i].map((v,j) => {
      const c = Math.round(v*100)/100;
      const bg = v>=.99?'#6b3aff'
        :v>.6?'rgba(107,58,255,'+(v*.75).toFixed(2)+')'
        :v>.3?'rgba(107,58,255,'+(v*.5).toFixed(2)+')'
        :v>.1?'rgba(107,58,255,'+(v*.3).toFixed(2)+')'
        :'rgba(22,20,31,0.8)';
      const fc = Math.abs(v)>.55?'#fff':'#7a7090';
      return '<td style="background:' + bg + ';color:' + fc + ';border-radius:3px;font-family:\'Space Grotesk\',sans-serif;font-weight:600">' + c.toFixed(2) + '</td>';
    }).join('') + '</tr>'
  ).join('');
  document.getElementById('corrTable').innerHTML = head + rows;
}

function renderScenarios(d) {
  document.getElementById('scenarioGrid').innerHTML =
    Object.entries(d.scenarios).map(([key,s]) =>
      '<div class="scenario-card sc-' + key + '">' +
      '<div class="sc-label" style="color:' + s.color + '">' + s.label + '</div>' +
      '<div class="sc-total" style="color:' + s.color + '">$' + s.totals.yr3.toLocaleString() + '</div>' +
      '<div class="sc-sub">' + (s.total_return_pct > 0 ? '+' : '') + s.total_return_pct + '% total return</div>' +
      '<div class="sc-rows">' +
      '<div class="sc-row"><span class="sc-row-lbl">Year 1</span><span style="color:' + s.color + ';font-weight:800">$' + s.totals.yr1.toLocaleString() + '</span></div>' +
      '<div class="sc-row"><span class="sc-row-lbl">Year 2</span><span style="color:' + s.color + ';font-weight:800">$' + s.totals.yr2.toLocaleString() + '</span></div>' +
      '<div class="sc-row"><span class="sc-row-lbl">Year 3</span><span style="color:' + s.color + ';font-weight:800">$' + s.totals.yr3.toLocaleString() + '</span></div>' +
      '</div>' +
      '<div class="sc-contrib">Incl. contributions: +$' + s.totals.yr3_contrib.toLocaleString() + '</div>' +
      '</div>'
    ).join('');
}

function scenRowHTML(r, i, s) {
  const col = tickerColor(r.ticker, i);
  const mc = r.mult_3yr >= 0 ? 'var(--green)' : 'var(--red)';
  return '<tr>' +
    '<td><span class="ticker-cell" style="color:' + col + '">' + r.ticker + '</span></td>' +
    '<td style="font-weight:700">' + r.weight + '%</td>' +
    '<td style="font-family:\'DM Mono\',monospace">$' + r.init.toLocaleString() + '</td>' +
    '<td style="font-weight:700;color:' + mc + '">' + (r.mult_3yr>=0?'+':'') + (r.mult_3yr*100).toFixed(0) + '%</td>' +
    '<td style="font-weight:700">' + (r.ann_r>=0?'+':'') + r.ann_r + '%</td>' +
    '<td style="font-weight:700">$' + r.yr1.toLocaleString() + '</td>' +
    '<td style="font-weight:700">$' + r.yr2.toLocaleString() + '</td>' +
    '<td style="font-weight:800;color:' + s.color + '">$' + r.yr3.toLocaleString() + '</td>' +
    '</tr>';
}

function renderScenarioTables(d) {
  document.getElementById('scenarioTables').innerHTML =
    Object.entries(d.scenarios).map(([key,s]) => {
      const rowsHTML = s.rows.map((r,i) => scenRowHTML(r,i,s)).join('');
      return '<div class="chart-card" style="margin-bottom:14px">' +
        '<h3 style="color:' + s.color + '">' + s.label + '</h3>' +
        '<div style="overflow-x:auto;margin-top:12px">' +
        '<table class="pos-table"><thead><tr>' +
        '<th>Ticker</th><th>Weight</th><th>Init Alloc</th>' +
        '<th>3yr Mult</th><th>Ann Equiv</th>' +
        '<th>Year 1</th><th>Year 2</th><th>Year 3</th>' +
        '</tr></thead><tbody>' + rowsHTML +
        '<tr style="background:rgba(107,58,255,.08)">' +
        '<td colspan="5" style="font-weight:800;color:var(--purple-mid)">PORTFOLIO TOTAL</td>' +
        '<td style="font-weight:800">$' + s.totals.yr1.toLocaleString() + '</td>' +
        '<td style="font-weight:800">$' + s.totals.yr2.toLocaleString() + '</td>' +
        '<td style="font-weight:800;color:' + s.color + '">$' + s.totals.yr3.toLocaleString() + '</td>' +
        '</tr></tbody></table></div></div>';
    }).join('');
}

async function runSmart() {
  if (tickers.length < 1) { showStatus('Add tickers first.', true); return; }
  showStatus('Analysing portfolio concentration…');
  try {
    const res = await fetch('/api/smart', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({tickers, weights: tickers.map(() => 1/tickers.length)})
    });
    const data = await res.json();
    hideStatus();
    renderSmart(data);
  } catch(e) {
    showStatus('Could not load suggestions.', true);
  }
}

function renderSmart(data) {
  document.getElementById('smartWarnings').innerHTML =
    data.warnings.map(w => '<div class="warning-item">' + w + '</div>').join('');
  document.getElementById('smartComplements').innerHTML =
    data.complements.map(s =>
      '<div class="smart-card">' +
      '<div><div class="smart-ticker" style="color:' + (TICKER_COLORS[s.ticker]||'#9b6dff') + '">' + s.ticker + '</div>' +
      '<div class="smart-desc">' + s.desc + '</div>' +
      '<div class="smart-rationale">' + s.rationale + '</div>' +
      '<button class="btn-add" onclick="addSmartTicker(\'' + s.ticker + '\')">+ Add</button></div>' +
      '<div><div class="smart-ret">' + s.exp_return + '</div><div class="smart-vol">vol ' + s.ann_vol + '</div></div>' +
      '</div>'
    ).join('');
  document.getElementById('smartDiversifiers').innerHTML =
    data.diversifiers.map(s =>
      '<div class="smart-card">' +
      '<div><div class="smart-ticker" style="color:#94a3b8">' + s.ticker + '</div>' +
      '<div class="smart-desc">' + s.desc + '</div>' +
      '<div class="smart-rationale">' + s.rationale + '</div>' +
      '<button class="btn-add" onclick="addSmartTicker(\'' + s.ticker + '\')">+ Add</button></div>' +
      '<div><div class="smart-ret" style="color:var(--text-muted)">' + s.exp_return + '</div><div class="smart-vol">vol ' + s.ann_vol + '</div></div>' +
      '</div>'
    ).join('');
  const panel = document.getElementById('smartPanel');
  panel.className = 'smart-panel visible';
  panel.scrollIntoView({behavior:'smooth', block:'start'});
}

function addSmartTicker(t) {
  if (!tickers.includes(t)) { tickers.push(t); renderChips(); }
}

loadDefault();
