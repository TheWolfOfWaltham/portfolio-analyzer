// ── Industry-based color palette ──────────────────────────────────────────────
// AI Compute/Memory: silver/platinum tones
// AI Optical/Networking: teal-to-cyan tones  
// Custom ASIC/Purple AI: violet tones
// Power/Energy: crimson-to-maroon tones
// SaaS/Fintech: burnt orange tones
// Defensive: muted gold/sage

const TICKER_COLORS = {
  // AI Compute / Memory — silver
  'SNDK':'#e2e8f0', 'NBIS':'#94a3b8', 'MU':'#cbd5e1',
  // AI Infra Optical — teal/cyan
  'GLW':'#2dd4bf', 'COHR':'#67e8f9', 'LITE':'#06b6d4',
  // AI Networking — blue-purple
  'ANET':'#818cf8',
  // Custom ASIC — violet
  'MRVL':'#a78bfa', 'AVGO':'#7c3aed',
  // Power & Energy — crimson to maroon
  'GEV':'#e11d48', 'VST':'#be123c', 'CEG':'#9f1239',
  // Utility / Nuclear
  'ETR':'#f97316', 'NEE':'#fb923c',
  // Enterprise SaaS — burnt orange
  'NOW':'#c2410c',
  // Fintech — orange
  'SOFI':'#f97316',
  // Cybersecurity — indigo
  'CRWD':'#4338ca',
  // Defensive / Blue chip — muted gold/sage
  'WMT':'#84cc16', 'JPM':'#a16207', 'JNJ':'#0284c7',
  'BRK/B':'#475569', 'PG':'#65a30d',
};
const PALETTE = ['#2dd4bf','#e2e8f0','#94a3b8','#e11d48','#a78bfa',
                 '#67e8f9','#818cf8','#be123c','#c2410c','#84cc16',
                 '#06b6d4','#7c3aed','#a16207','#f97316','#4338ca'];

const DEFAULT_TICKERS = ['GLW','SNDK','NBIS','GEV','MRVL','COHR','ANET','VST','NOW'];
let tickers = [], currentMode = 'sharpe', chartInstances = {};
let sortCol = 'weight', sortDir = 'desc', lastPositionData = null;

function tickerColor(t,i){ return TICKER_COLORS[t]||PALETTE[i%PALETTE.length]; }

// ── Stars inside hero ─────────────────────────────────────────────────────────
function initStars(){
  const hero = document.querySelector('.hero');
  const canvas = document.createElement('canvas');
  canvas.style.cssText='position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:0.5';
  hero.insertBefore(canvas, hero.firstChild);
  const ctx = canvas.getContext('2d');
  let stars = [];
  function resize(){ canvas.width=hero.offsetWidth; canvas.height=hero.offsetHeight; }
  resize();
  new ResizeObserver(resize).observe(hero);
  for(let i=0;i<100;i++) stars.push({
    x:Math.random()*canvas.width, y:Math.random()*canvas.height,
    size:Math.random()*1.1+0.3, phase:Math.random()*Math.PI*2,
    speed:Math.random()*0.006+0.002, alpha:Math.random()*0.7+0.2
  });
  function drawPlus(x,y,s,a){
    ctx.save(); ctx.globalAlpha=a; ctx.strokeStyle='#fff';
    ctx.lineWidth=s*0.65; ctx.lineCap='round';
    ctx.beginPath(); ctx.moveTo(x-s,y); ctx.lineTo(x+s,y); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x,y-s); ctx.lineTo(x,y+s); ctx.stroke();
    ctx.restore();
  }
  function animate(t){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    stars.forEach(s=>{
      const a=s.alpha*(0.25+0.75*Math.abs(Math.sin(s.phase+t*0.001*s.speed*6)));
      drawPlus(s.x,s.y,s.size,a);
    });
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
}

// ── Chip management ───────────────────────────────────────────────────────────
function renderChips(){
  const row=document.getElementById('tickerRow');
  row.querySelectorAll('.ticker-chip').forEach(c=>c.remove());
  tickers.forEach((t,i)=>{
    const col=tickerColor(t,i);
    const chip=document.createElement('span');
    chip.className='ticker-chip';
    chip.style.cssText='background:'+col+'22;color:'+col+';border:1px solid '+col+'55';
    chip.innerHTML=t+'<button onclick="removeTicker('+i+')">✕</button>';
    row.insertBefore(chip,document.getElementById('tickerField'));
  });
}
function addTicker(raw){
  const t=raw.trim().toUpperCase().replace(/[^A-Z0-9.\-/]/g,'');
  if(t&&!tickers.includes(t)&&tickers.length<15) tickers.push(t);
  renderChips();
}
function removeTicker(i){ tickers.splice(i,1); renderChips(); }
document.getElementById('tickerField').addEventListener('keydown',e=>{
  const v=e.target.value;
  if(e.key==='Enter'||e.key===','||e.key===' '){ e.preventDefault(); if(v.trim()) addTicker(v); e.target.value=''; }
  else if(e.key==='Backspace'&&!v&&tickers.length){ tickers.pop(); renderChips(); }
});
document.getElementById('tickerField').addEventListener('blur',e=>{
  if(e.target.value.trim()){ addTicker(e.target.value); e.target.value=''; }
});
function setMode(btn){ document.querySelectorAll('.mode-tab').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); currentMode=btn.dataset.mode; }
function loadDefault(){ tickers=[...DEFAULT_TICKERS]; renderChips(); }
function clearAll(){ tickers=[]; renderChips(); }

// ── Status ────────────────────────────────────────────────────────────────────
function showStatus(msg,isErr=false){
  const bar=document.getElementById('statusBar');
  bar.className='status-bar visible'+(isErr?' err':'');
  document.getElementById('statusMsg').textContent=msg;
}
function hideStatus(){ document.getElementById('statusBar').className='status-bar'; }

// ── Analysis ──────────────────────────────────────────────────────────────────
async function runAnalysis(){
  if(tickers.length<2){ showStatus('Add at least 2 tickers.',true); return; }
  showStatus('Fetching market data and running optimization…');
  document.getElementById('analyzeBtn').disabled=true;
  document.getElementById('results').className='';
  try{
    const res=await fetch('/api/analyze',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tickers,capital:+document.getElementById('capital').value,
        biweekly:+document.getElementById('biweekly').value, mode:currentMode})
    });
    const data=await res.json();
    if(data.error){ showStatus(data.error,true); return; }
    hideStatus(); renderAll(data);
    document.getElementById('results').className='visible';
    document.getElementById('results').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(e){ showStatus('Error: '+e.message,true); console.error(e); }
  finally{ document.getElementById('analyzeBtn').disabled=false; }
}

function destroyChart(id){ if(chartInstances[id]){ chartInstances[id].destroy(); delete chartInstances[id]; } }

function renderAll(d){
  document.getElementById('dataNote').textContent=d.data_note||'';
  lastPositionData=d;
  renderKPIs(d); renderStackedBar(d); renderExposure(d);
  renderFrontier(d); renderMonteCarlo(d);
  renderScenarios(d);
  renderPositionTable(d);
  renderScenarioTables(d);
}

// ── KPIs ──────────────────────────────────────────────────────────────────────
function renderKPIs(d){
  const p=d.portfolio;
  document.getElementById('kpiStrip').innerHTML=
    '<div class="kpi kpi-green"><div class="kpi-label">Exp. Annual Return</div><div class="kpi-val">'+p.ann_ret+'%</div><div class="kpi-sub">forward estimate</div></div>'+
    '<div class="kpi"><div class="kpi-label">Portfolio Volatility</div><div class="kpi-val" style="color:var(--text)">'+p.ann_vol+'%</div><div class="kpi-sub">annualized</div></div>'+
    '<div class="kpi kpi-purple"><div class="kpi-label">Sharpe Ratio</div><div class="kpi-val">'+p.sharpe+'</div><div class="kpi-sub">rf = 4.5%</div></div>'+
    '<div class="kpi kpi-green"><div class="kpi-label">3yr Compounded</div><div class="kpi-val">+'+p.port_3yr_geom+'%</div><div class="kpi-sub">geometric mean</div></div>'+
    '<div class="kpi kpi-red"><div class="kpi-label">VaR 95% (1yr)</div><div class="kpi-val">'+p.var_95+'%</div><div class="kpi-sub">1-in-20 year</div></div>'+
    '<div class="kpi kpi-red"><div class="kpi-label">Est. Max Drawdown</div><div class="kpi-val">'+p.max_dd_est+'%</div><div class="kpi-sub">2.5\u03c3 stress</div></div>';
}

// ── Stacked bar ───────────────────────────────────────────────────────────────
function renderStackedBar(d){
  const bar=document.getElementById('stackedBar'), leg=document.getElementById('stackedLegend');
  bar.innerHTML=''; leg.innerHTML='';
  d.positions.forEach((p,i)=>{
    const col=tickerColor(p.ticker,i);
    const seg=document.createElement('div');
    seg.className='seg'+(p.weight<8?' seg-sm':'');
    seg.style.cssText='width:'+p.weight+'%;background:'+col;
    seg.innerHTML='<span class="seg-pct">'+p.weight+'%</span><span class="seg-ticker">'+p.ticker+'</span>';
    bar.appendChild(seg);
    const li=document.createElement('div'); li.className='legend-item';
    li.innerHTML='<div class="legend-dot" style="background:'+col+'"></div>'+p.ticker+' '+p.weight+'%';
    leg.appendChild(li);
  });
}

// ── Exposure bars ─────────────────────────────────────────────────────────────
function renderExposure(d){
  if(!d.exposure){ document.getElementById('exposureCard').innerHTML=''; return; }
  const exp=d.exposure;
  const macro=exp.macro, sub=exp.sub, mc=exp.macro_colors, sc=exp.sub_colors;
  const maxSub=Math.max(...Object.values(sub));
  let macroHTML='<div class="exposure-macro-bar">';
  Object.entries(macro).forEach(([label,pct])=>{
    const col=mc[label]||'#5a5270';
    macroHTML+='<div class="exp-seg" style="width:'+pct+'%;background:'+col+'">'+
      '<span class="exp-seg-label">'+label+'</span>'+
      '<span class="exp-seg-pct">'+pct+'%</span></div>';
  });
  macroHTML+='</div>';
  let subHTML='<div class="exposure-sub-label">Sub-sector breakdown</div><div class="sub-bars">';
  Object.entries(sub).forEach(([label,pct])=>{
    const col=sc[label]||'#5a5270';
    subHTML+='<div class="sub-bar-row">'+
      '<div class="sub-bar-label">'+label+'</div>'+
      '<div class="sub-bar-bg"><div class="sub-bar-fill" style="width:'+(pct/maxSub*100).toFixed(0)+'%;background:'+col+'"></div></div>'+
      '<div class="sub-bar-pct" style="color:'+col+'">'+pct+'%</div></div>';
  });
  subHTML+='</div>';
  document.getElementById('exposureCard').innerHTML=macroHTML+subHTML;
}

// ── Frontier ──────────────────────────────────────────────────────────────────
function renderFrontier(d){
  destroyChart('f');
  const gc='rgba(42,32,64,0.6)', tc='#5a5270';
  chartInstances['f']=new Chart(document.getElementById('frontierChart').getContext('2d'),{
    type:'scatter',
    data:{datasets:[
      {label:'Efficient Frontier',data:d.frontier.map(p=>({x:p.vol,y:p.ret})),
       borderColor:'#6b3aff',backgroundColor:'rgba(107,58,255,0.06)',showLine:true,tension:.4,pointRadius:0,borderWidth:2},
      {label:'Your Portfolio',data:[{x:d.portfolio.ann_vol,y:d.portfolio.ann_ret}],
       backgroundColor:'#9b6dff',borderColor:'#9b6dff',pointRadius:10,pointStyle:'star'},
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{labels:{color:tc,font:{size:10,family:"'Space Grotesk',sans-serif"},boxWidth:10}},
               tooltip:{callbacks:{label:c=>'Vol '+c.parsed.x.toFixed(1)+'% | Ret '+c.parsed.y.toFixed(1)+'%'}}},
      scales:{x:{title:{display:true,text:'Volatility (%)',color:tc,font:{size:10}},ticks:{color:tc,font:{size:9}},grid:{color:gc}},
              y:{title:{display:true,text:'Return (%)',color:tc,font:{size:10}},ticks:{color:tc,font:{size:9}},grid:{color:gc}}}}
  });
}

// ── Monte Carlo ───────────────────────────────────────────────────────────────
function renderMonteCarlo(d){
  destroyChart('mc');
  const paths=d.mc_paths, gc='rgba(42,32,64,0.6)', tc='#5a5270';
  const labels=Array.from({length:37},(_,i)=>i===0?'Now':i===12?'Yr 1':i===24?'Yr 2':i===36?'Yr 3':'');
  const pct=(arr,p)=>{ const s=[...arr].sort((a,b)=>a-b); return s[Math.floor(s.length*p)]; };
  const p5=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.05)));
  const p50=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.50)));
  const p95=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.95)));
  const pDs=paths.slice(0,40).map(p=>({data:p,borderColor:'rgba(107,58,255,0.07)',borderWidth:.8,pointRadius:0,fill:false,tension:.3}));
  chartInstances['mc']=new Chart(document.getElementById('mcChart').getContext('2d'),{
    type:'line',
    data:{labels,datasets:[...pDs,
      {label:'95th pct',data:p95,borderColor:'rgba(74,222,128,.5)',borderWidth:1.5,borderDash:[4,3],pointRadius:0,fill:false},
      {label:'Median',data:p50,borderColor:'#9b6dff',borderWidth:2.5,pointRadius:0,fill:false},
      {label:'5th pct',data:p5,borderColor:'rgba(248,113,113,.5)',borderWidth:1.5,borderDash:[4,3],pointRadius:0,fill:false},
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{labels:{filter:i=>['Median','95th pct','5th pct'].includes(i.text),color:tc,font:{size:10,family:"'Space Grotesk',sans-serif"},boxWidth:10}},tooltip:{enabled:false}},
      scales:{x:{ticks:{color:tc,font:{size:9}},grid:{color:gc}},
              y:{ticks:{color:tc,font:{size:9},callback:v=>'$'+Math.round(v/1000)+'K'},grid:{color:gc}}}}
  });
}

// ── Scenario summary cards (Bull → Base → Bear) ───────────────────────────────
function renderScenarios(d){
  const order=['bull','base','bear'];
  document.getElementById('scenarioGrid').innerHTML=order.map(key=>{
    const s=d.scenarios[key];
    return '<div class="scenario-card sc-'+key+'">'+
      '<div class="sc-label" style="color:'+s.color+'">'+s.label+'</div>'+
      '<div class="sc-total" style="color:'+s.color+'">$'+s.totals.yr3.toLocaleString()+'</div>'+
      '<div class="sc-sub">'+(s.total_return_pct>0?'+':'')+s.total_return_pct+'% total return</div>'+
      '<div class="sc-rows">'+
      '<div class="sc-row"><span class="sc-row-lbl">Year 1</span><span style="color:'+s.color+';font-weight:800">$'+s.totals.yr1.toLocaleString()+'</span></div>'+
      '<div class="sc-row"><span class="sc-row-lbl">Year 2</span><span style="color:'+s.color+';font-weight:800">$'+s.totals.yr2.toLocaleString()+'</span></div>'+
      '<div class="sc-row"><span class="sc-row-lbl">Year 3</span><span style="color:'+s.color+';font-weight:800">$'+s.totals.yr3.toLocaleString()+'</span></div>'+
      '</div><div class="sc-contrib">Incl. DCA contributions: +$'+s.totals.yr3_contrib.toLocaleString()+'</div></div>';
  }).join('');
}

// ── Sortable position table ───────────────────────────────────────────────────
function renderPositionTable(d){
  lastPositionData=d;
  const positions=[...d.positions];
  const cols=['ticker','ann_ret','ann_vol','sharpe','rc_pct','weight'];
  positions.sort((a,b)=>{
    const av=typeof a[sortCol]==='string'?a[sortCol]:+a[sortCol];
    const bv=typeof b[sortCol]==='string'?b[sortCol]:+b[sortCol];
    return sortDir==='desc'?(bv>av?1:-1):(av>bv?1:-1);
  });
  const thStyle='cursor:pointer;user-select:none;white-space:nowrap';
  const arrow=c=>c===sortCol?(sortDir==='desc'?' ▾':' ▴'):'';
  const ths=[
    {k:'ticker',l:'Ticker'},{k:'weight',l:'Weight'},{k:'ann_ret',l:'Exp. Return'},
    {k:'ann_vol',l:'Ann. Vol'},{k:'sharpe',l:'Sharpe'},{k:'rc_pct',l:'Risk Contrib.'}
  ].map(h=>'<th style="'+thStyle+'" onclick="sortTable(\''+h.k+'\')">'+h.l+arrow(h.k)+'</th>').join('');

  const rows=positions.map((p,i)=>{
    const col=tickerColor(p.ticker,i);
    const sec=d.sectors[p.ticker]?d.sectors[p.ticker].sector:'Other';
    const rcClass=p.rc_pct>25?'tag-high':p.rc_pct>12?'tag-med':'tag-low';
    const retColor=p.ann_ret>=0?'var(--green)':'var(--red)';
    return '<tr>'+
      '<td><span class="ticker-cell" style="color:'+col+'">'+p.ticker+'</span><div style="font-size:10px;color:var(--text-dim);font-weight:500;margin-top:1px">'+sec+'</div></td>'+
      '<td style="font-weight:800">'+p.weight+'%</td>'+
      '<td style="font-weight:700;color:'+retColor+'">'+(p.ann_ret>=0?'+':'')+p.ann_ret+'%</td>'+
      '<td style="font-family:\'DM Mono\',monospace">'+p.ann_vol+'%</td>'+
      '<td style="font-weight:700">'+p.sharpe+'</td>'+
      '<td><span class="tag '+rcClass+'">'+p.rc_pct+'%</span></td>'+
      '</tr>';
  }).join('');

  document.getElementById('posTable').innerHTML=
    '<thead><tr>'+ths+'</tr></thead><tbody>'+rows+'</tbody>';
}

function sortTable(col){
  if(sortCol===col) sortDir=sortDir==='desc'?'asc':'desc';
  else{ sortCol=col; sortDir='desc'; }
  if(lastPositionData) renderPositionTable(lastPositionData);
}

// ── Scenario detail tables (restructured) ─────────────────────────────────────
function renderScenarioTables(d){
  const order=['bull','base','bear'];
  document.getElementById('scenarioTables').innerHTML=order.map(key=>{
    const s=d.scenarios[key];
    // Sum row values
    const sumInit=s.rows.reduce((a,r)=>a+r.init,0);
    const sumBiweekly=s.rows.reduce((a,r)=>a+r.biweekly,0);
    const sumYr1=s.totals.yr1, sumYr2=s.totals.yr2, sumYr3=s.totals.yr3;
    const portfolioReturn=s.total_return_pct;

    const rowsHTML=s.rows.map((r,i)=>{
      const col=tickerColor(r.ticker,i);
      const retColor=r.total_return_pct>=0?'var(--green)':'var(--red)';
      return '<tr>'+
        '<td><span class="ticker-cell" style="color:'+col+'">'+r.ticker+'</span></td>'+
        '<td style="font-family:\'DM Mono\',monospace">$'+r.init.toLocaleString()+'</td>'+
        '<td style="font-family:\'DM Mono\',monospace">$'+r.biweekly.toFixed(2)+'</td>'+
        '<td style="font-weight:700;color:var(--purple-mid)">'+(r.ann_r>=0?'+':'')+r.ann_r+'%</td>'+
        '<td style="font-weight:700">$'+r.yr1.toLocaleString()+'</td>'+
        '<td style="font-weight:700">$'+r.yr2.toLocaleString()+'</td>'+
        '<td style="font-weight:800;color:'+s.color+'">$'+r.yr3.toLocaleString()+'</td>'+
        '<td style="font-weight:800;color:'+retColor+'">'+(r.total_return_pct>=0?'+':'')+r.total_return_pct+'%</td>'+
        '</tr>';
    }).join('');

    const sumRow='<tr style="background:rgba(107,58,255,.08);border-top:1px solid rgba(107,58,255,.3)">'+
      '<td style="font-weight:800;color:var(--purple-mid)">TOTAL</td>'+
      '<td style="font-weight:800;font-family:\'DM Mono\',monospace">$'+sumInit.toLocaleString()+'</td>'+
      '<td style="font-weight:800;font-family:\'DM Mono\',monospace">$'+sumBiweekly.toFixed(2)+'</td>'+
      '<td style="color:var(--text-dim)">—</td>'+
      '<td style="font-weight:800">$'+sumYr1.toLocaleString()+'</td>'+
      '<td style="font-weight:800">$'+sumYr2.toLocaleString()+'</td>'+
      '<td style="font-weight:800;color:'+s.color+'">$'+sumYr3.toLocaleString()+'</td>'+
      '<td style="font-weight:800;color:'+(portfolioReturn>=0?'var(--green)':'var(--red)')+'">'+
        (portfolioReturn>=0?'+':'')+portfolioReturn+'%</td>'+
      '</tr>';

    return '<div class="chart-card" style="margin-bottom:14px">'+
      '<h3 style="color:'+s.color+'">'+s.label+'</h3>'+
      '<div style="overflow-x:auto;margin-top:12px">'+
      '<table class="pos-table"><thead><tr>'+
      '<th>Ticker</th><th>Init Alloc ($)</th><th>Biweekly DCA ($)</th>'+
      '<th>Ann. Growth Rate</th><th>EOY Year 1</th><th>EOY Year 2</th>'+
      '<th>EOY Year 3</th><th>Total Return</th>'+
      '</tr></thead><tbody>'+rowsHTML+sumRow+'</tbody></table></div></div>';
  }).join('');
}

// ── Smart suggestions ─────────────────────────────────────────────────────────
async function runSmart(){
  if(tickers.length<1){ showStatus('Add tickers first.',true); return; }
  showStatus('Running marginal impact analysis on candidate stocks…');
  try{
    const res=await fetch('/api/smart',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tickers,weights:tickers.map(()=>1/tickers.length)})
    });
    const data=await res.json();
    hideStatus(); renderSmart(data);
  } catch(e){ showStatus('Could not load suggestions.',true); }
}

function impactTag(label,val,isPositiveGood=true){
  const num=parseFloat(val);
  const pos=(isPositiveGood&&num>0)||(!isPositiveGood&&num<0);
  const cls=Math.abs(num)<0.001?'impact-neu':pos?'impact-pos':'impact-neg';
  return '<span class="impact-tag '+cls+'">'+label+': '+(num>0?'+':'')+val+'</span>';
}

function renderSmart(data){
  document.getElementById('smartWarnings').innerHTML=
    data.warnings.map(w=>'<div class="warning-item">'+w+'</div>').join('');
  function cardHTML(s){
    const col=TICKER_COLORS[s.ticker]||'#9b6dff';
    const sd=s.sharpe_delta, vd=s.vol_delta, rd=s.ret_delta;
    return '<div class="smart-card">'+
      '<div class="smart-card-top">'+
        '<div>'+
          '<div class="smart-ticker" style="color:'+col+'">'+s.ticker+'</div>'+
          '<div class="smart-sector">'+s.sector+'</div>'+
        '</div>'+
        '<div style="text-align:right">'+
          '<div style="font-size:13px;font-weight:800;color:var(--green)">'+(s.exp_return*100).toFixed(0)+'%</div>'+
          '<div style="font-size:10px;color:var(--text-dim);font-family:\'DM Mono\',monospace">vol '+(s.ann_vol*100).toFixed(0)+'%</div>'+
        '</div>'+
      '</div>'+
      '<div class="smart-desc">'+s.desc+'</div>'+
      '<div class="smart-impacts">'+
        impactTag('Sharpe',(sd>=0?'+':'')+sd.toFixed(3),true)+
        impactTag('Vol',(vd>=0?'+':'')+vd.toFixed(1)+'%',false)+
        impactTag('Ret',(rd>=0?'+':'')+rd.toFixed(1)+'%',true)+
        '<span class="impact-tag impact-neu">Corr: '+s.corr_to_book.toFixed(2)+'</span>'+
      '</div>'+
      '<div class="smart-rationale">'+s.rationale+'</div>'+
      '<button class="btn-add" onclick="addSmartTicker(\''+s.ticker+'\')">+ Add to portfolio</button>'+
      '</div>';
  }
  document.getElementById('smartComplements').innerHTML=(data.sharpe_enhancers||[]).map(cardHTML).join('');
  document.getElementById('smartDiversifiers').innerHTML=(data.vol_reducers||[]).map(cardHTML).join('');
  const panel=document.getElementById('smartPanel');
  panel.className='smart-panel visible';
  panel.scrollIntoView({behavior:'smooth',block:'start'});
}

function addSmartTicker(t){
  if(!tickers.includes(t)){ tickers.push(t); renderChips(); }
}

// ── Init ──────────────────────────────────────────────────────────────────────
loadDefault();
window.addEventListener('load', initStars);
