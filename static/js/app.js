// ── Approved dark space color palette ────────────────────────────────────────
const TICKER_COLORS = {
  // Group 1 — AI Optical — near-black navy (#111827 family)
  'GLW':'#111827', 'COHR':'#0f1a2e', 'LITE':'#131e30',
  // Group 2 — AI Compute/Memory — dark charcoal (#1a1a1a family)
  'SNDK':'#1a1a1a', 'NBIS':'#1c1c22', 'MU':'#161618',
  // Group 3 — Custom ASIC/Networking — vantablack violet (#160d38 family)
  'MRVL':'#160d38', 'ANET':'#130b30', 'AVGO':'#1a0f40',
  // Group 4 — Power & Energy — near-black crimson (#200808 family)
  'GEV':'#200808', 'VST':'#240a0a', 'CEG':'#1a0606',
  // Group 5 — SaaS/Fintech — near-black amber (#1e1205 family)
  'NOW':'#1e1205', 'SOFI':'#1a1005', 'CRWD':'#151020',
  // Group 6 — Defensive — near-black forest (#0a1a0e family)
  'WMT':'#0a1a0e', 'JPM':'#0a100e', 'JNJ':'#0c120f',
  'BRK/B':'#101010', 'PG':'#0d1a0a',
  // Utility
  'NEE':'#0d150d', 'ETR':'#141414',
};
const PALETTE = ['#0e7490','#334155','#5b21b6','#7f1d1d','#4338ca',
                 '#155e75','#9f1239','#7c2d12','#1e3a5f','#3730a3',
                 '#312e81','#92400e','#14532d','#78350f','#164e63'];

const MACRO_COLORS = {
  'AI Compute':       '#1a1a1a',  // dark charcoal (Group 2)
  'AI Infrastructure':'#111827',  // near-black navy (Group 1)
  'Power & Energy':   '#200808',  // near-black crimson (Group 4)
  'Growth/SaaS':      '#1e1205',  // near-black amber (Group 5)
  'Defensive':        '#0a1a0e',  // near-black forest (Group 6)
  'Other':            '#160d38',  // vantablack violet (Group 3)
};
const SUB_TO_MACRO = {
  'Semiconductors':'AI Compute','AI Cloud Infra':'AI Compute',
  'AI Infra Optical':'AI Infrastructure','Optical Transceivers':'AI Infrastructure',
  'AI Networking':'AI Infrastructure','Custom ASIC':'AI Infrastructure',
  'Power Infra':'Power & Energy','Power Generation':'Power & Energy','Nuclear Power':'Power & Energy',
  'Enterprise SaaS':'Growth/SaaS','Fintech':'Growth/SaaS','Cybersecurity':'Growth/SaaS',
  'Consumer Staples':'Defensive','Healthcare':'Defensive','Conglomerate':'Defensive',
  'Financials':'Defensive','Utilities':'Defensive','Utility':'Defensive','Other':'Other',
};

// Glow colors — lighter/more vibrant than fill colors for visible glow effect
const GLOW_COLORS = {
  // AI Optical — teal glow
  'GLW':'rgba(20,140,170,0.7)', 'COHR':'rgba(15,110,140,0.7)', 'LITE':'rgba(10,100,130,0.7)',
  // AI Compute — slate-blue glow
  'SNDK':'rgba(70,80,100,0.6)', 'NBIS':'rgba(50,80,140,0.65)', 'MU':'rgba(60,90,130,0.6)',
  // ASIC/Networking — violet glow
  'MRVL':'rgba(110,55,230,0.7)', 'ANET':'rgba(80,65,220,0.7)', 'AVGO':'rgba(70,55,200,0.65)',
  // Power & Energy — crimson glow
  'GEV':'rgba(220,35,35,0.7)', 'VST':'rgba(200,25,55,0.7)', 'CEG':'rgba(180,20,20,0.65)',
  // SaaS/Enterprise — amber-brown glow
  'NOW':'rgba(100,55,20,0.65)', 'SOFI':'rgba(120,65,20,0.6)', 'CRWD':'rgba(70,55,190,0.65)',
  // Defensive — forest glow
  'WMT':'rgba(20,100,40,0.6)', 'JPM':'rgba(100,70,15,0.6)', 'JNJ':'rgba(15,80,120,0.6)',
  'BRK/B':'rgba(40,40,40,0.5)', 'PG':'rgba(20,90,30,0.55)',
  'NEE':'rgba(20,80,35,0.55)', 'ETR':'rgba(50,50,55,0.5)',
};
// Macro sector glow colors
const MACRO_GLOW = {
  'AI Compute':       'rgba(70,80,110,0.65)',
  'AI Infrastructure':'rgba(20,130,165,0.65)',
  'Power & Energy':   'rgba(215,35,35,0.65)',
  'Growth/SaaS':      'rgba(100,55,20,0.6)',
  'Defensive':        'rgba(20,95,35,0.6)',
  'Other':            'rgba(90,50,200,0.55)',
};
function glowFor(ticker){ return GLOW_COLORS[ticker]||'rgba(107,58,255,0.55)'; }
function macroGlowFor(key){ return MACRO_GLOW[key]||'rgba(107,58,255,0.55)'; }
let tickers = [], currentMode = 'sharpe', chartInstances = {};
let sortCol = 'weight', sortDir = 'desc', lastPositionData = null;
let scenarioSortState = {};

// Contribution frequency
const FREQ = {
  weekly:   {label:'Weekly',   col:'Weekly DCA ($)',   periods:52, toAnnual:v=>v*52},
  biweekly: {label:'Biweekly', col:'Biweekly DCA ($)', periods:26, toAnnual:v=>v*26},
  monthly:  {label:'Monthly',  col:'Monthly DCA ($)',  periods:12, toAnnual:v=>v*12},
};
let currentFreq = 'biweekly';

function tickerColor(t,i){ return TICKER_COLORS[t]||PALETTE[i%PALETTE.length]; }

// ── Stars — screen blend mode overlay, appears over all content ───────────────
function initStars(){
  const canvas = document.getElementById('starsCanvas');
  if(!canvas) return;
  const ctx = canvas.getContext('2d');
  let stars = [];
  let W = 0, H = 0;

  function resize(){
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width  = W;
    canvas.height = H;
  }
  resize();
  window.addEventListener('resize', resize);

  function makeStar(){
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      size: Math.random() * 1.2 + 0.3,
      phase: Math.random() * Math.PI * 2,
      speed: Math.random() * 0.006 + 0.002,
      peak: Math.random() * 0.28 + 0.08, // max brightness — keep subtle
    };
  }
  for(let i = 0; i < 180; i++) stars.push(makeStar());

  function drawPlus(x, y, s, a){
    ctx.save();
    // screen blend: draw white on black → shows through everything
    ctx.globalAlpha = a;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = s * 0.65;
    ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(x-s, y); ctx.lineTo(x+s, y); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x, y-s); ctx.lineTo(x, y+s); ctx.stroke();
    ctx.restore();
  }

  let frame = 0;
  function animate(){
    frame++;
    // fill black so screen blend shows only the stars
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, W, H);
    stars.forEach(s => {
      const a = s.peak * (0.15 + 0.85 * Math.abs(Math.sin(s.phase + frame * s.speed)));
      drawPlus(s.x, s.y, s.size, a);
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
    const glow=glowFor(t);
    const chip=document.createElement('span');
    chip.className='ticker-chip';
    chip.style.cssText='background:#000;color:rgba(255,255,255,0.9);box-shadow:0 0 14px 3px '+glow+',0 0 28px 6px '+glow.replace(/[\d.]+\)$/,'0.25)')+'';
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
function setFreq(btn){
  document.querySelectorAll('.freq-tab').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  currentFreq = btn.dataset.freq;
  updateRothDisplay();
}
function loadDefault(){ tickers=[...DEFAULT_TICKERS]; renderChips(); }
function clearAll(){ tickers=[]; renderChips(); }

document.getElementById('biweekly').addEventListener('input', ()=>{});

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
    const rawContrib = +document.getElementById('biweekly').value;
    const annualContrib = FREQ[currentFreq].toAnnual(rawContrib);
    const biweeklyEquiv = annualContrib / 26; // normalize to biweekly for backend
    const res=await fetch('/api/analyze',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tickers,capital:+document.getElementById('capital').value,
        biweekly:biweeklyEquiv, mode:currentMode})
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

let lastCovMatrix = null;
let lastBetas = {};

function renderAll(d){
  document.getElementById('dataNote').textContent=d.data_note||'';
  lastPositionData=d;
  lastCovMatrix = d.cov_matrix||null;
  lastBetas = {};
  (d.positions||[]).forEach(p=>{ lastBetas[p.ticker]=p.beta||1.0; });
  renderHeroBubbles(d);
  renderKPIs(d); renderRiskPanel(d); renderStackedBar(d); renderExposure(d);
  renderFrontier(d); renderMonteCarlo(d);
  renderScenarios(d); renderPositionTable(d); renderScenarioTables(d);
}

function renderRiskPanel(d, extraRisks){
  const p=d.portfolio;
  const exp=d.exposure||{};
  const macro=exp.macro||{};
  const aiPct=(macro['AI Infrastructure']||0)+(macro['AI Compute']||0);
  const risks=[];

  // Dynamic risks based on actual portfolio metrics
  if(p.max_dd_est<-60){
    risks.push({
      header:'Drawdown Risk: Extreme downside exposure',
      body:'Estimated drawdown of '+p.max_dd_est+'% in a 2.5σ down year'+(p.max_dd_hist!=null?' (these weights fell '+p.max_dd_hist+'% peak to trough over the past year)':'')+'. Consider adding low-beta defensive positions (WMT, JNJ, BRK/B) to reduce tail risk.'
    });
  } else if(p.max_dd_est<-40){
    risks.push({
      header:'Drawdown Risk: High downside in stress scenarios',
      body:'Estimated drawdown of '+p.max_dd_est+'% in a 2.5σ down year'+(p.max_dd_hist!=null?' (past year, peak to trough: '+p.max_dd_hist+'%)':'')+'. Adding 10-15% in low-vol blue-chips could reduce this materially without sacrificing core AI upside.'
    });
  }
  if(aiPct>65){
    risks.push({
      header:'Concentration Risk: '+aiPct.toFixed(0)+'% AI sector exposure',
      body:'A single AI capex pause or macro risk-off event would hit the majority of this portfolio simultaneously. Consider adding uncorrelated sectors — energy, healthcare, or consumer staples.'
    });
  } else if(aiPct>50){
    risks.push({
      header:'Concentration Risk: Elevated AI exposure at '+aiPct.toFixed(0)+'%',
      body:'More than half the portfolio is correlated to AI infrastructure capex. A 2027-style slowdown scenario could impact most positions at once.'
    });
  }
  if(p.ann_vol>60){
    risks.push({
      header:'Volatility Risk: Portfolio vol of '+p.ann_vol+'% is very high',
      body:'Annualized volatility of '+p.ann_vol+'% means the portfolio can swing ±'+Math.round(p.ann_vol/Math.sqrt(12))+'% in a typical month. DCA strategy helps — but consider a vol-reducing hedge position.'
    });
  } else if(p.ann_vol>40){
    risks.push({
      header:'Volatility Risk: '+p.ann_vol+'% annualized vol',
      body:'Moderate-to-high volatility. Systematic profit-taking rules on high-conviction positions like SNDK help manage this behaviorally.'
    });
  }

  // Merge any extra risks from Claude smart suggestions
  if(extraRisks&&extraRisks.length){
    extraRisks.forEach(r=>{
      if(risks.length<4) risks.push({header:r.split(':')[0]||'Risk', body:r});
    });
  }

  const panel=document.getElementById('riskPanel');
  if(!risks.length){ panel.style.display='none'; return; }
  panel.style.display='block';
  panel.innerHTML='<div class="risk-panel">'+
    '<div class="risk-panel-title">Portfolio Risk Assessment</div>'+
    risks.slice(0,3).map(r=>
      '<div class="risk-item">'+
        '<div class="risk-item-header">'+r.header+'</div>'+
        '<div class="risk-item-body">'+r.body+'</div>'+
      '</div>'
    ).join('')+
  '</div>';
}

// ── KPIs ──────────────────────────────────────────────────────────────────────
function renderKPIs(d){
  const p=d.portfolio;
  const rawRoth = +document.getElementById('rothBiweekly').value || 0;
  const annualRoth = FREQ[currentFreq].toAnnual(rawRoth);
  const rothBiweekly = annualRoth / 26;
  // FV of Roth contributions over 3yr at portfolio geometric return
  const geomR = (p.ann_ret/100) - 0.5*Math.pow(p.ann_vol/100,2);
  const rPerPeriod = (1+geomR)**(1/26)-1;
  const roth3yrFV = rPerPeriod > 0
    ? rothBiweekly * ((Math.pow(1+rPerPeriod,26*3)-1)/rPerPeriod)
    : rothBiweekly * 26 * 3;
  document.getElementById('kpiStrip').innerHTML=
    '<div class="kpi kpi-green"><div class="kpi-label">Exp. Annual Return</div><div class="kpi-val">'+p.ann_ret+'%</div><div class="kpi-sub">forward estimate</div></div>'+
    '<div class="kpi"><div class="kpi-label">Portfolio Volatility</div><div class="kpi-val" style="color:var(--text)">'+p.ann_vol+'%</div><div class="kpi-sub">annualized</div></div>'+
    '<div class="kpi kpi-purple"><div class="kpi-label">Sharpe Ratio</div><div class="kpi-val">'+p.sharpe+'</div><div class="kpi-sub">rf = '+(d.rf!=null?d.rf+'%':'n/a')+'</div></div>'+
    '<div class="kpi kpi-green"><div class="kpi-label">3yr Compounded</div><div class="kpi-val">'+((+p.port_3yr_geom)>=0?'+':'')+p.port_3yr_geom+'%</div><div class="kpi-sub">median outcome</div></div>'+
    '<div class="kpi kpi-red"><div class="kpi-label">Est. Max Drawdown</div><div class="kpi-val">'+p.max_dd_est+'%</div><div class="kpi-sub">2.5\u03c3 stress'+(p.max_dd_hist!=null?' · past year: '+p.max_dd_hist+'%':'')+'</div></div>'+
    '<div class="kpi kpi-purple"><div class="kpi-label">Roth IRA — 3yr Est.</div><div class="kpi-val" style="font-size:18px">$'+Math.round(roth3yrFV).toLocaleString()+'</div><div class="kpi-sub">DCA @ portfolio return</div></div>';
}

// ── Stacked bar ───────────────────────────────────────────────────────────────
function renderStackedBar(d){
  const bar=document.getElementById('stackedBar'), leg=document.getElementById('stackedLegend');
  bar.innerHTML=''; leg.innerHTML='';
  const sorted=[...d.positions].sort((a,b)=>b.weight-a.weight);
  sorted.forEach((p,i)=>{
    const col=tickerColor(p.ticker,i);
    const glow=glowFor(p.ticker);
    const glowOuter=glow.replace(/[\d.]+\)$/,'0.25)');
    const seg=document.createElement('div');
    seg.className='seg'+(p.weight<8?' seg-sm':'');
    seg.style.cssText='width:'+p.weight+'%;background:#000;border:1.5px solid '+col+';box-shadow:0 0 14px 3px '+glow+',inset 0 0 10px '+glow.replace(/[\d.]+\)$/,'0.12)')+',0 0 28px 6px '+glowOuter;
    seg.innerHTML='<span class="seg-pct">'+p.weight+'%</span><span class="seg-ticker">'+p.ticker+'</span>';
    bar.appendChild(seg);
    const li=document.createElement('div'); li.className='legend-item';
    li.innerHTML='<div class="legend-dot" style="background:'+col+';box-shadow:0 0 6px 1px '+glow+'"></div>'+p.ticker+' '+p.weight+'%';
    leg.appendChild(li);
  });
}

// ── Sector exposure ───────────────────────────────────────────────────────────
function renderExposure(d){
  if(!d.exposure){ document.getElementById('exposureCard').innerHTML=''; return; }
  const macro=d.exposure.macro;
  const sorted=Object.entries(macro).sort((a,b)=>b[1]-a[1]);
  let html='<div class="exposure-macro-bar">';
  sorted.forEach(([label,pct])=>{
    const baseCol=MACRO_COLORS[label]||'#1e1b4b';
    const glow=macroGlowFor(label);
    const glowOuter=glow.replace(/[\d.]+\)$/,'0.2)');
    html+='<div class="exp-seg" style="width:'+pct+'%;background:#000;border:1.5px solid '+baseCol+';box-shadow:0 0 14px 3px '+glow+',inset 0 0 10px '+glow.replace(/[\d.]+\)$/,'0.1)')+',0 0 26px 5px '+glowOuter+'">'+
      '<span class="exp-seg-label">'+label+'</span>'+
      '<span class="exp-seg-pct">'+pct+'%</span></div>';
  });
  html+='</div>';
  document.getElementById('exposureCard').innerHTML=html;
}

// ── Frontier ──────────────────────────────────────────────────────────────────
function renderFrontier(d){
  destroyChart('f');
  const gc='rgba(42,32,64,0.5)', tc='#5a5270';
  chartInstances['f']=new Chart(document.getElementById('frontierChart').getContext('2d'),{
    type:'scatter',
    data:{datasets:[
      {label:'Efficient Frontier',data:d.frontier.map(p=>({x:p.vol,y:p.ret})),
       borderColor:'#6b3aff',backgroundColor:'rgba(107,58,255,0.05)',showLine:true,tension:.4,pointRadius:0,borderWidth:2},
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
  const paths=d.mc_paths, gc='rgba(42,32,64,0.5)', tc='#5a5270';
  const labels=Array.from({length:37},(_,i)=>i===0?'Now':i===12?'Yr 1':i===24?'Yr 2':i===36?'Yr 3':'');
  const pct=(arr,p)=>{ const s=[...arr].sort((a,b)=>a-b); return s[Math.floor(s.length*p)]; };
  const p5=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.05)));
  const p50=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.50)));
  const p95=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.95)));
  const pDs=paths.slice(0,200).map(p=>({data:p,borderColor:'rgba(155,109,255,0.10)',borderWidth:0.8,pointRadius:0,fill:false,tension:.3}));
  const namedDatasets = [
    {label:'95th pct', color:'rgba(107,58,255,0.9)'},
    {label:'Median',   color:'#c084ff'},
    {label:'5th pct',  color:'rgba(159,18,57,0.9)'},
  ];
  const mcEndLabels = {
    id:'mcEndLabels',
    afterDraw(chart){
      const ctx=chart.ctx;
      const allDs=chart.data.datasets;
      // Named datasets are the last 3
      const startIdx=allDs.length-3;
      namedDatasets.forEach((nd,i)=>{
        const idx=startIdx+i;
        if(idx<0||idx>=allDs.length) return;
        const meta=chart.getDatasetMeta(idx);
        if(!meta||!meta.data||!meta.data.length) return;
        const lastPt=meta.data[meta.data.length-1];
        if(!lastPt) return;
        const val=allDs[idx].data[allDs[idx].data.length-1];
        if(!val&&val!==0) return;
        const x=lastPt.x, y=lastPt.y;
        if(isNaN(x)||isNaN(y)) return;
        ctx.save();
        ctx.fillStyle=nd.color;
        ctx.font='700 10px Space Grotesk, sans-serif';
        ctx.textAlign='left';
        ctx.textBaseline='middle';
        ctx.fillText('$'+Math.round(val/1000)+'K', x+6, y);
        ctx.restore();
      });
    }
  };
  chartInstances['mc']=new Chart(document.getElementById('mcChart').getContext('2d'),{
    type:'line',
    plugins:[mcEndLabels],
    data:{labels,datasets:[...pDs,
      {label:'95th pct',data:p95,borderColor:'rgba(107,58,255,0.5)',borderWidth:1.5,borderDash:[4,3],pointRadius:0,fill:false},
      {label:'Median',data:p50,borderColor:'#9b6dff',borderWidth:2.5,pointRadius:0,fill:false},
      {label:'5th pct',data:p5,borderColor:'rgba(159,18,57,0.6)',borderWidth:1.5,borderDash:[4,3],pointRadius:0,fill:false},
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{labels:{filter:i=>['Median','95th pct','5th pct'].includes(i.text),color:tc,font:{size:10,family:"'Space Grotesk',sans-serif"},boxWidth:10}},tooltip:{enabled:false}},
      scales:{x:{ticks:{color:tc,font:{size:9}},grid:{color:gc}},
              y:{ticks:{color:tc,font:{size:9},callback:v=>'$'+Math.round(v/1000)+'K'},grid:{color:gc}}}}
  });
}

// ── Scenario summary cards ────────────────────────────────────────────────────
function renderScenarios(d){
  const order=['bull','base','bear'];
  const totalBiweekly3yr = d.biweekly * 26 * 3;
  const totalInvested = d.capital + totalBiweekly3yr;
  document.getElementById('scenarioGrid').innerHTML=order.map(key=>{
    const s=d.scenarios[key];
    const contribAdjRet=totalInvested>0?((s.totals.yr3-totalInvested)/totalInvested*100).toFixed(1):0;
    const initOnlyRet=(s.initial_only_pct!=null?s.initial_only_pct:(d.capital>0?((s.totals.yr3_init-d.capital)/d.capital*100).toFixed(1):0));
    const adjColor=+contribAdjRet>=0?s.color:'var(--red)';
    return '<div class="scenario-card sc-'+key+'">'+
      '<div class="sc-label" style="color:'+s.color+'">'+s.label+'</div>'+
      '<div class="sc-total" style="color:'+s.color+'">$'+s.totals.yr3.toLocaleString()+'</div>'+
      '<div class="sc-sub" style="color:'+adjColor+';opacity:1;font-weight:700">'+(+contribAdjRet>=0?'+':'')+contribAdjRet+'% on all capital deployed</div>'+
      '<div style="font-size:10px;color:var(--text-dim);margin-bottom:10px;font-family:\'DM Mono\',monospace">('+((+initOnlyRet)>=0?'+':'')+initOnlyRet+'% on initial capital alone)</div>'+
      '<div class="sc-rows">'+
      '<div class="sc-row"><span class="sc-row-lbl">Year 1</span><span style="color:'+s.color+';font-weight:800">$'+s.totals.yr1.toLocaleString()+'</span></div>'+
      '<div class="sc-row"><span class="sc-row-lbl">Year 2</span><span style="color:'+s.color+';font-weight:800">$'+s.totals.yr2.toLocaleString()+'</span></div>'+
      '<div class="sc-row"><span class="sc-row-lbl">Year 3</span><span style="color:'+s.color+';font-weight:800">$'+s.totals.yr3.toLocaleString()+'</span></div>'+
      '</div><div class="sc-contrib">Value of DCA contributions: $'+s.totals.yr3_contrib.toLocaleString()+' ($'+Math.round(d.biweekly*26*3).toLocaleString()+' paid in)</div></div>';
  }).join('');
}

// ── Sortable position table ───────────────────────────────────────────────────
function renderPositionTable(d){
  lastPositionData=d;
  const positions=[...d.positions];
  positions.sort((a,b)=>{
    const av=+a[sortCol]||0, bv=+b[sortCol]||0;
    return sortDir==='desc'?bv-av:av-bv;
  });
  const arrow=c=>c===sortCol?(sortDir==='desc'?' ▾':' ▴'):'';
  const thS='cursor:pointer;user-select:none;white-space:nowrap';
  const hdrs=[
    {k:'ticker',l:'Ticker'},{k:'weight',l:'Weight'},
    {k:'beta',l:'β Beta'},{k:'blended_return',l:'Exp. Return (blend)'},
    {k:'ann_vol',l:'Ann. Vol'},{k:'sharpe',l:'Sharpe'},{k:'rc_pct',l:'Risk Contrib.'},
    {k:'',l:'Your Estimate'}
  ].map(h=>'<th style="'+thS+(h.k?'" onclick="sortTable(\''+h.k+'\')':'')+'">'+(h.k?h.l+arrow(h.k):h.l)+'</th>').join('');

  const rows=positions.map((p,i)=>{
    const glow=glowFor(p.ticker);
    const sec=d.sectors[p.ticker]?d.sectors[p.ticker].sector:'Other';
    const rcClass=p.rc_pct>25?'tag-high':p.rc_pct>12?'tag-med':'tag-low';
    const isLive=p.data_source&&!p.data_source.includes('PRIOR');
    const srcBadge=isLive?'<span class="source-badge source-live">live</span>':'<span class="source-badge source-prior">prior</span>';
    const hasFMP=p.analyst_target&&p.analyst_implied!==null&&p.analyst_implied!==undefined;
    const blendLabel='<span style="font-size:9px;color:'+(hasFMP?'var(--purple-mid)':'var(--text-faint)')+
      ';font-weight:600">'+(p.return_source||'')+'</span>';
    const analystNote=hasFMP
      ?'<div style="font-size:9px;color:var(--text-dim);font-family:\'DM Mono\',monospace">target $'+(p.analyst_target||0).toFixed(2)+' → '+p.analyst_implied+'%</div>':'';
    const blended=p.blended_return||p.ann_ret||0;
    return '<tr>'+
      '<td><span style="color:#fff;background:#000;padding:3px 10px;border-radius:5px;display:inline-block;box-shadow:0 0 10px 2px '+glow+',0 0 20px 4px '+glow.replace(/[\d.]+\)$/,'0.18)')+';font-family:\'Space Grotesk\',sans-serif;font-size:12px;font-weight:800">'+p.ticker+'</span>'+
      '<div style="font-size:9px;color:var(--text-dim);margin-top:2px;display:flex;align-items:center;gap:4px">'+sec+' '+srcBadge+'</div></td>'+
      '<td style="font-weight:800">'+p.weight+'%</td>'+
      '<td style="font-family:\'DM Mono\',monospace;color:var(--blue)">'+(p.beta||1).toFixed(2)+'</td>'+
      '<td><span style="font-weight:800;color:var(--purple-mid)">+'+blended.toFixed(1)+'%</span>'+blendLabel+analystNote+'</td>'+
      '<td style="font-family:\'DM Mono\',monospace">'+p.ann_vol+'%</td>'+
      '<td style="font-weight:700">'+p.sharpe+'</td>'+
      '<td><span class="tag '+rcClass+'">'+p.rc_pct+'%</span></td>'+
      '<td><input type="number" class="ret-override-input" data-ticker="'+p.ticker+'" data-original="'+blended.toFixed(1)+'" value="'+blended.toFixed(1)+'" step="0.5" min="-50" max="200" onchange="markOverride(this)" style="width:70px;background:#0d0d13;border:1px solid #2a2040;border-radius:5px;padding:4px 6px;font-family:\'DM Mono\',monospace;font-size:11px;color:#e8e6f0;text-align:right"/><span style="font-size:9px;color:var(--text-faint);margin-left:3px">%</span></td>'+
      '</tr>';
  }).join('');

  document.getElementById('posTable').innerHTML='<thead><tr>'+hdrs+'</tr></thead><tbody>'+rows+'</tbody>';
}

function sortTable(col){
  if(sortCol===col) sortDir=sortDir==='desc'?'asc':'desc';
  else{ sortCol=col; sortDir='desc'; }
  if(lastPositionData) renderPositionTable(lastPositionData);
}

// ── Scenario detail tables (sortable, restructured) ───────────────────────────
function renderScenarioTables(d){
  const order=['bull','base','bear'];
  document.getElementById('scenarioTables').innerHTML=order.map(key=>{
    const s=d.scenarios[key];
    scenarioSortState[key]={col:'init',dir:'desc'};
    return buildScenarioTable(key,s);
  }).join('');
  window._lastScenarios=d.scenarios;
}

function buildScenarioTable(key,s){
  const st=scenarioSortState[key]||{col:'init',dir:'desc'};
  const rows=[...s.rows].sort((a,b)=>{
    const av=+a[st.col]||0, bv=+b[st.col]||0;
    return st.dir==='desc'?bv-av:av-bv;
  });

  const arrow=c=>c===st.col?(st.dir==='desc'?' ▾':' ▴'):'';
  const thS='cursor:pointer;user-select:none;white-space:nowrap';
  const hdrs=[
    {k:'ticker',l:'Ticker'},{k:'init',l:'Init Alloc ($)'},
    {k:'biweekly',l:FREQ[currentFreq].col},{k:'ann_r',l:'Ann. Growth'},
    {k:'yr1',l:'EOY Year 1'},{k:'yr2',l:'EOY Year 2'},{k:'yr3',l:'EOY Year 3'},
    {k:'contrib_adj_pct',l:'Total Return'},
  ].map(h=>'<th style="'+thS+'" onclick="sortScenario(\''+key+'\',\''+h.k+'\')">'+h.l+arrow(h.k)+'</th>').join('');

  const sumInit=s.rows.reduce((a,r)=>a+r.init,0);
  const sumBwk=s.rows.reduce((a,r)=>a+r.biweekly,0);

  const rowsHTML=rows.map((r,i)=>{
    const col=tickerColor(r.ticker,i);
    const adjColor=r.contrib_adj_pct>=0?'var(--green)':'var(--red)';
    const initOnly=r.initial_only_pct;
    return '<tr>'+
      '<td><span style="color:#fff;background:#000;padding:3px 10px;border-radius:5px;display:inline-block;box-shadow:0 0 10px 2px '+glowFor(r.ticker)+';font-family:\'Space Grotesk\',sans-serif;font-size:12px;font-weight:800">'+r.ticker+'</span></td>'+
      '<td style="font-family:\'DM Mono\',monospace">$'+r.init.toLocaleString()+'</td>'+
      '<td style="font-family:\'DM Mono\',monospace">$'+r.biweekly.toFixed(2)+'</td>'+
      '<td style="font-weight:700;color:var(--purple-mid)">'+(r.ann_r>=0?'+':'')+r.ann_r+'%</td>'+
      '<td style="font-weight:700">$'+r.yr1.toLocaleString()+'</td>'+
      '<td style="font-weight:700">$'+r.yr2.toLocaleString()+'</td>'+
      '<td style="font-weight:800;color:'+s.color+'">$'+r.yr3.toLocaleString()+'</td>'+
      '<td style="font-weight:800;color:'+adjColor+'">'+
        (r.contrib_adj_pct>=0?'+':'')+r.contrib_adj_pct+'%'+
        '<span style="font-size:10px;color:var(--text-dim);font-weight:400"> ('+(initOnly>=0?'+':'')+initOnly+'% on init)</span>'+
      '</td>'+
      '</tr>';
  }).join('');

  // Portfolio-level contrib-adjusted return
  const totalInvested=sumInit+sumBwk*26*3;
  const portAdjRet=totalInvested>0?((s.totals.yr3-totalInvested)/totalInvested*100).toFixed(1):0;
  const portInitRet=sumInit>0?((s.totals.yr3_init-sumInit)/sumInit*100).toFixed(1):0;
  const adjColor=+portAdjRet>=0?'var(--green)':'var(--red)';

  const sumRow='<tr style="background:rgba(107,58,255,.07);border-top:1px solid rgba(107,58,255,.25)">'+
    '<td style="font-weight:800;color:var(--purple-mid)">TOTAL</td>'+
    '<td style="font-weight:800;font-family:\'DM Mono\',monospace">$'+Math.round(sumInit).toLocaleString()+'</td>'+
    '<td style="font-weight:800;font-family:\'DM Mono\',monospace">$'+sumBwk.toFixed(2)+'</td>'+
    '<td style="color:var(--text-dim)">—</td>'+
    '<td style="font-weight:800">$'+s.totals.yr1.toLocaleString()+'</td>'+
    '<td style="font-weight:800">$'+s.totals.yr2.toLocaleString()+'</td>'+
    '<td style="font-weight:800;color:'+s.color+'">$'+s.totals.yr3.toLocaleString()+'</td>'+
    '<td style="font-weight:800;color:'+adjColor+'">'+
      (+portAdjRet>=0?'+':'')+portAdjRet+'%'+
      '<span style="font-size:10px;color:var(--text-dim);font-weight:400"> ('+((+portInitRet)>=0?'+':'')+portInitRet+'% on init)</span>'+
    '</td>'+
    '</tr>';

  return '<div class="chart-card" id="scen-table-'+key+'" style="margin-bottom:14px">'+
    '<h3 style="color:'+s.color+'">'+s.label+' <span style="font-size:10px;color:var(--text-dim);font-weight:400;text-transform:none">— click columns to sort · Total Return = gain vs all capital deployed (init + DCA)</span></h3>'+
    '<div style="overflow-x:auto;margin-top:12px">'+
    '<table class="pos-table"><thead><tr>'+hdrs+'</tr></thead>'+
    '<tbody>'+rowsHTML+sumRow+'</tbody></table></div></div>';
}

function sortScenario(key,col){
  const st=scenarioSortState[key]||{col:'init',dir:'desc'};
  if(st.col===col) st.dir=st.dir==='desc'?'asc':'desc';
  else{ st.col=col; st.dir='desc'; }
  scenarioSortState[key]=st;
  if(window._lastScenarios&&window._lastScenarios[key]){
    const el=document.getElementById('scen-table-'+key);
    if(el) el.outerHTML=buildScenarioTable(key,window._lastScenarios[key]);
  }
}

// ── Smart suggestions ─────────────────────────────────────────────────────────
async function runSmart(){
  if(tickers.length<1){ showStatus('Add tickers first.',true); return; }
  const promptEl=document.getElementById('smartPrompt');
  const prompt=promptEl?promptEl.value.trim():'';
  const btn=document.getElementById('smartBtn');
  if(btn) btn.disabled=true;
  showStatus('Analysing your portfolio…');
  try{
    const res=await fetch('/api/smart',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tickers,weights:tickers.map(()=>1/tickers.length),user_prompt:prompt})});
    const data=await res.json();
    if(data.error){ showStatus(data.error,true); return; }
    hideStatus();
    renderSmart(data);
  } catch(e){ showStatus('Could not load suggestions: '+e.message,true); }
  finally{ if(btn) btn.disabled=false; }
}

function impactTag(label,val,posGood=true){
  const num=parseFloat(val);
  const pos=(posGood&&num>0)||(!posGood&&num<0);
  const cls=Math.abs(num)<0.001?'impact-neu':pos?'impact-pos':'impact-neg';
  return '<span class="impact-tag '+cls+'">'+label+': '+(num>0?'+':'')+val+'</span>';
}

function renderSmart(data){
  // Update risk panel with any additional warnings from smart suggestions
  if(lastPositionData) renderRiskPanel(lastPositionData, data.warnings||[]);

  // Powered-by badge
  const pbEl=document.getElementById('smartPoweredBy');
  if(pbEl) pbEl.textContent=data.powered_by==='claude'?'✦ Powered by Claude AI':'◈ Curated database';

  // Portfolio analysis banner
  const analysisEl=document.getElementById('smartAnalysis');
  if(analysisEl){
    if(data.portfolio_analysis){
      analysisEl.textContent=data.portfolio_analysis;
      analysisEl.style.display='block';
    } else { analysisEl.style.display='none'; }
  }

  // Hide old yellow warnings - they're now in the risk panel
  document.getElementById('smartWarnings').innerHTML='';

  function cardHTML(s){
    const glow=glowFor(s.ticker);
    const col=tickerColor(s.ticker,0);
    const sd=s.sharpe_delta||0, vd=s.vol_delta||0, rd=s.ret_delta||0;
    const parts=(s.desc||'').split(' — ');
    const company=parts[0]||s.ticker;
    const whyNow=parts.slice(1).join(' — ');
    const retVal=typeof s.exp_return==='number'?s.exp_return:(parseFloat(s.exp_return)||0);
    const volVal=typeof s.ann_vol==='number'?s.ann_vol:(parseFloat(s.ann_vol)||0);
    return '<div class="smart-card">'+
      '<div class="smart-card-top"><div>'+
        '<div class="smart-ticker" style="color:#fff;background:#000;padding:3px 10px;border-radius:5px;display:inline-block;box-shadow:0 0 12px 3px '+glow+',0 0 24px 5px '+glow.replace(/[\d.]+\)$/,'0.2)')+';font-size:12px;font-weight:800">'+s.ticker+'</div>'+
        '<div class="smart-sector" style="margin-top:4px">'+s.sector+'</div></div>'+
        '<div style="text-align:right">'+
          '<div style="font-size:13px;font-weight:800;color:var(--green)">'+(retVal*100).toFixed(0)+'%</div>'+
          '<div style="font-size:10px;color:var(--text-dim);font-family:\'DM Mono\',monospace">vol '+(volVal*100).toFixed(0)+'%</div>'+
        '</div></div>'+
      (company?'<div class="smart-desc" style="font-weight:600;color:var(--text-muted);margin-bottom:4px">'+company+'</div>':'')+
      (whyNow?'<div style="font-size:11px;color:var(--purple-mid);font-style:italic;margin-bottom:6px">'+whyNow+'</div>':'')+
      '<div class="smart-desc">'+s.rationale+'</div>'+
      '<div class="smart-impacts">'+
        impactTag('Sharpe',(sd>=0?'+':'')+sd.toFixed(3),true)+
        impactTag('Vol',(vd>=0?'+':'')+vd.toFixed(1)+'%',false)+
        impactTag('Ret',(rd>=0?'+':'')+rd.toFixed(1)+'%',true)+
        '<span class="impact-tag impact-neu">Corr: '+(s.corr_to_book||0).toFixed(2)+'</span>'+
      '</div>'+
      '<button class="btn-add" onclick="addSmartTicker(\''+s.ticker+'\')">+ Add to portfolio</button>'+
      '</div>';
  }

  document.getElementById('smartComplements').innerHTML=(data.sharpe_enhancers||[]).map(cardHTML).join('');
  document.getElementById('smartDiversifiers').innerHTML=(data.vol_reducers||[]).map(cardHTML).join('');
  const panel=document.getElementById('smartPanel');
  panel.className='smart-panel visible';
  panel.style.overflow='hidden';
  panel.style.maxHeight='5000px';
  smartVisible=true;
  document.getElementById('starWrap').style.display='flex';
  panel.scrollIntoView({behavior:'smooth',block:'start'});
}

function addSmartTicker(t){
  if(!tickers.includes(t)){ tickers.push(t); renderChips(); }
}

// ── Nasdaq banner ─────────────────────────────────────────────────────────────
const COMPANY_DOMAINS = {
  AAPL:'apple.com',MSFT:'microsoft.com',NVDA:'nvidia.com',AMZN:'amazon.com',
  GOOG:'google.com',META:'meta.com',TSLA:'tesla.com',AVGO:'broadcom.com',
  NFLX:'netflix.com',COST:'costco.com',AMD:'amd.com',QCOM:'qualcomm.com',
  ADBE:'adobe.com',TXN:'ti.com',AMGN:'amgen.com',CSCO:'cisco.com',
  SBUX:'starbucks.com',GILD:'gilead.com',PANW:'paloaltonetworks.com',
  LRCX:'lamresearch.com',AMAT:'appliedmaterials.com',KLAC:'kla.com',
  REGN:'regeneron.com',ADP:'adp.com',BKNG:'booking.com',MRVL:'marvell.com',
  CRWD:'crowdstrike.com',DDOG:'datadoghq.com',TEAM:'atlassian.com',
  ZS:'zscaler.com',WDAY:'workday.com',ABNB:'airbnb.com',FTNT:'fortinet.com',
  CDNS:'cadence.com',SNPS:'synopsys.com',ORLY:'oreillyauto.com',
  CTAS:'cintas.com',PCAR:'paccar.com',MNST:'monsterenergy.com',EA:'ea.com',
  BIIB:'biogen.com',IDXX:'idexx.com',ANSS:'ansys.com',HON:'honeywell.com',
  PEP:'pepsico.com',INTC:'intel.com',MDLZ:'mondelezinternational.com',
  ADI:'analog.com',VRTX:'vrtx.com',FISV:'fiserv.com',
};

function initNasdaqBanner(){
  fetch('/api/market-data').then(r=>r.json()).then(data=>{
    const items = data.tickers||[];
    if(!items.length) return;
    const track = document.getElementById('nasdaqTrack');
    track.innerHTML = '';
    // Build two copies for seamless loop
    for(let copy=0;copy<2;copy++){
      items.forEach(item=>{
        const domain = COMPANY_DOMAINS[item.ticker]||'';
        const pos    = item.change >= 0;
        const el = document.createElement('div');
        el.className = 'nasdaq-item';
        el.innerHTML =
          (domain?`<img class="nasdaq-logo" src="https://logo.clearbit.com/${domain}" onerror="this.style.display='none'" loading="lazy"/>`:'') +
          `<span class="nasdaq-ticker">${item.ticker}</span>` +
          `<span class="nasdaq-price">$${item.price.toFixed(2)}</span>` +
          `<span class="nasdaq-chg ${pos?'pos':'neg'}">${pos?'▲':'▼'}${Math.abs(item.change).toFixed(2)}%</span>`;
        track.appendChild(el);
      });
    }
    // Animate with GSAP if available, else CSS
    const totalW = track.scrollWidth / 2;
    if(window.gsap){
      gsap.to(track, {x:-totalW, duration:totalW/50, ease:'none', repeat:-1, modifiers:{
        x: gsap.utils.wrap(-totalW, 0)
      }});
    } else {
      let pos2 = 0;
      function scroll(){ pos2 -= 0.5; if(pos2 <= -totalW) pos2=0; track.style.transform=`translateX(${pos2}px)`; requestAnimationFrame(scroll); }
      requestAnimationFrame(scroll);
    }
  }).catch(()=>{});
}

// ── Hero bubbles ──────────────────────────────────────────────────────────────
function renderHeroBubbles(d){
  const capital   = d.capital||10000;
  const biweekly  = d.biweekly||500;
  const totalDCA  = biweekly * 26 * 3;
  const totalIn   = capital + totalDCA;
  const baseYr3   = d.scenarios?.base?.totals?.yr3 || 0;
  const baseAdj   = totalIn>0?((baseYr3-totalIn)/totalIn*100).toFixed(1):0;

  const bubbles = document.getElementById('heroBubbles');
  bubbles.style.display = 'grid';
  bubbles.innerHTML =
    // 1. Total capital deployed
    '<div class="hero-bubble">' +
      '<div class="hb-label">Total Capital Deployed — 3yr</div>' +
      '<div class="hb-val" style="color:var(--purple-mid)">$'+totalIn.toLocaleString()+'</div>' +
      '<div class="hb-sub">$'+capital.toLocaleString()+' initial + $'+Math.round(totalDCA).toLocaleString()+' DCA</div>' +
    '</div>' +
    // 2. Base case future value
    '<div class="hero-bubble">' +
      '<div class="hb-label">Base Case — 3yr Portfolio Value</div>' +
      '<div class="hb-val" style="color:var(--blue)">$'+baseYr3.toLocaleString()+'</div>' +
      '<div class="hb-sub">'+( +baseAdj>=0?'+':'')+baseAdj+'% on all capital deployed</div>' +
    '</div>' +
    // 3. Treemap
    '<div class="hero-bubble">' +
      '<div class="hb-label">Portfolio Weights</div>' +
      '<div id="treemapContainer" class="treemap"></div>' +
    '</div>';

  // Build treemap
  renderTreemap(d.positions);
}

function renderTreemap(positions){
  const wrap = document.getElementById('treemapContainer');
  if(!wrap||!positions) return;
  const sorted = [...positions].sort((a,b)=>b.weight-a.weight);
  const total  = sorted.reduce((s,p)=>s+p.weight,0);
  wrap.innerHTML = '';
  // Simple row-based layout
  let remaining = [...sorted];
  let totalH = wrap.offsetHeight || 180;
  let totalW = wrap.offsetWidth  || 300;
  let yOff = 0;
  while(remaining.length > 0){
    const rowW = remaining.reduce((s,p)=>s+p.weight,0)/total*totalH;
    // Decide how many go in this row (aspect ratio heuristic)
    let rowItems = [], rowWeight = 0;
    for(let i=0;i<remaining.length;i++){
      const candidate = [...rowItems, remaining[i]];
      const cw = candidate.reduce((s,p)=>s+p.weight,0)/total*totalH;
      const minW = Math.min(...candidate.map(p=>p.weight/total*totalH/cw*totalW));
      if(candidate.length > 1 && minW < 28 && rowItems.length > 0) break;
      rowItems.push(remaining[i]);
      rowWeight += remaining[i].weight;
    }
    remaining = remaining.slice(rowItems.length);
    const rowH = rowWeight / total * totalH;
    rowItems.forEach(p=>{
      const segW = p.weight / rowWeight * totalW;
      const glow = glowFor(p.ticker);
      const div  = document.createElement('div');
      div.className = 'tm-seg';
      div.style.cssText = 'width:'+segW.toFixed(1)+'px;height:'+rowH.toFixed(1)+'px;' +
        'border:1.5px solid '+tickerColor(p.ticker,0)+';' +
        'box-shadow:0 0 10px 2px '+glow+',inset 0 0 8px '+glow.replace(/[\d.]+\)$/,'0.1)')+';';
      if(segW > 24 && rowH > 24){
        div.innerHTML = '<span class="tm-ticker">'+p.ticker+'</span><span class="tm-pct">'+p.weight+'%</span>';
      }
      wrap.appendChild(div);
    });
    yOff += rowH;
    if(remaining.length===0) break;
    totalH -= rowH;
    if(totalH < 10) break;
  }
}

// ── Star hide button (GSAP) ───────────────────────────────────────────────────
let smartVisible = false;
function initStarBtn(){
  const btn = document.getElementById('starBtn');
  if(!btn) return;
  // CSS keyframe handles the spin as fallback
  // GSAP enhances with color animation if available
  if(!window.gsap) return;
  gsap.set('#starSvg', {transformOrigin:'50% 50%'});
  btn.addEventListener('mouseenter',()=>{
    // +=360 = always spin a full turn forward from current rotation
    gsap.to('#starSvg', {rotation:'+=360', duration:0.55,
      ease:'back.out(1.8)', overwrite:true});
    gsap.to('#starSvg path', {fill:'#6b3aff', stroke:'#c084ff',
      duration:0.25, overwrite:true});
  });
  btn.addEventListener('mouseleave',()=>{
    gsap.to('#starSvg path', {fill:'#2d1b69', stroke:'#6b3aff',
      duration:0.3, overwrite:true});
  });
}

function toggleSmartPanel(){
  const panel  = document.getElementById('smartPanel');
  const risk   = document.getElementById('riskPanel');
  const wrap   = document.getElementById('starWrap');
  const txt    = document.querySelector('.star-text');
  if(!window.gsap||!panel) return;

  if(smartVisible){
    // Show
    gsap.to([panel,risk], {maxHeight:2000, opacity:1, duration:0.8,
      ease:'power2.inOut', display:'block'});
    if(txt) txt.textContent = 'Hide suggestions';
  } else {
    // Hide — blind close effect
    gsap.to([panel,risk], {maxHeight:0, opacity:0, duration:0.8,
      ease:'power2.inOut', onComplete:()=>{
        panel.style.display='none';
        if(risk) risk.style.display='none';
      }});
    if(txt) txt.textContent = 'Show suggestions';
  }
  smartVisible = !smartVisible;
}


// ── Return override + recalculate ─────────────────────────────────────────────
function markOverride(input){
  const original = parseFloat(input.dataset.original);
  const current  = parseFloat(input.value);
  input.style.borderColor = Math.abs(current-original)>0.01 ? 'var(--purple)' : '#2a2040';
}

async function runRecalculate(){
  if(!lastPositionData||!lastCovMatrix){ showStatus('Run Analyze first.',true); return; }
  const inputs = document.querySelectorAll('.ret-override-input');
  const overrides = {};
  inputs.forEach(inp=>{ overrides[inp.dataset.ticker]=parseFloat(inp.value)||10; });

  showStatus('Recalculating with your return estimates…');
  document.getElementById('recalcBtn').disabled=true;
  try{
    const res=await fetch('/api/recalculate',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        tickers: lastPositionData.tickers,
        returns: overrides,
        cov_matrix: lastCovMatrix,
        betas: lastBetas,
        capital: +document.getElementById('capital').value,
        biweekly: FREQ[currentFreq].toAnnual(+document.getElementById('biweekly').value) / 26,
        mode: currentMode,
      })
    });
    const data=await res.json();
    if(data.error){ showStatus(data.error,true); return; }
    hideStatus();
    // Merge updated portfolio stats back into lastPositionData for re-renders
    const merged={...lastPositionData, portfolio:data.portfolio, rf:data.rf,
      frontier:data.frontier, mc_paths:data.mc_paths,
      scenarios:data.scenarios, weights:data.weights};
    renderKPIs(merged); renderHeroBubbles(merged);
    renderFrontier(merged); renderMonteCarlo(merged); renderScenarios(merged);
    renderScenarioTables(merged);
    // Flash the KPI strip to indicate update
    const strip=document.getElementById('kpiStrip');
    strip.style.transition='opacity 0.2s';
    strip.style.opacity='0.4';
    setTimeout(()=>strip.style.opacity='1',300);
  } catch(e){ showStatus('Recalculate error: '+e.message,true); }
  finally{ document.getElementById('recalcBtn').disabled=false; }
}

loadDefault();
window.addEventListener('load', initStars);
window.addEventListener('load', initNasdaqBanner);
window.addEventListener('load', initStarBtn);
