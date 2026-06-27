

// ── State ────────────────────────────────────────────────────────────────────
let tickers = [];
let currentMode = "sharpe";
let chartInstances = {};
const DEFAULT_TICKERS = ["GLW","SNDK","NBIS","GEV","MRVL","COHR","ANET","VST","NOW"];
const TICKER_COLORS   = {
  "GLW":"#1565c0","SNDK":"#e65100","NBIS":"#2e7d32","GEV":"#b71c1c",
  "MRVL":"#4a148c","COHR":"#00695c","ANET":"#1a237e","VST":"#1b5e20","NOW":"#4e342e",
};
const PALETTE = ["#1565c0","#e65100","#2e7d32","#b71c1c","#4a148c",
                 "#00695c","#1a237e","#1b5e20","#4e342e","#880e4f",
                 "#0d47a1","#558b2f","#006064","#37474f","#f57f17"];

function tickerColor(t,i){ return TICKER_COLORS[t] || PALETTE[i % PALETTE.length]; }

// ── Ticker chip management ────────────────────────────────────────────────────
function renderChips(){
  const row = document.getElementById("tickerRow");
  row.querySelectorAll(".ticker-chip").forEach(c=>c.remove());
  tickers.forEach((t,i)=>{
    const chip = document.createElement("span");
    chip.className = "ticker-chip";
    chip.style.background = tickerColor(t,i);
    chip.innerHTML = `${t}<button onclick='removeTicker(${i})'>✕</button>`;
    row.insertBefore(chip, document.getElementById("tickerField"));
  });
}
function addTicker(raw){
  const t = raw.trim().toUpperCase().replace(/[^A-Z0-9.-]/g,"");
  if(t && !tickers.includes(t) && tickers.length < 15) tickers.push(t);
  renderChips();
}
function removeTicker(i){ tickers.splice(i,1); renderChips(); }

document.getElementById("tickerField").addEventListener("keydown", e=>{
  const v = e.target.value;
  if(e.key==="Enter"||e.key===","||e.key===" "){
    e.preventDefault();
    if(v.trim()) addTicker(v);
    e.target.value="";
  } else if(e.key==="Backspace"&&!v&&tickers.length){
    tickers.pop(); renderChips();
  }
});
document.getElementById("tickerField").addEventListener("blur",e=>{
  if(e.target.value.trim()){ addTicker(e.target.value); e.target.value=""; }
});

function setMode(btn){
  document.querySelectorAll(".mode-tab").forEach(b=>b.classList.remove("active"));
  btn.classList.add("active");
  currentMode = btn.dataset.mode;
}
function loadDefault(){ tickers=[...DEFAULT_TICKERS]; renderChips(); }
function clearAll(){ tickers=[]; renderChips(); }

// ── Status ───────────────────────────────────────────────────────────────────
function showStatus(msg,isErr=false){
  const bar=document.getElementById("statusBar");
  bar.className="status-bar visible"+(isErr?" status-err":"");
  document.getElementById("statusMsg").textContent=msg;
  document.getElementById("spinner").style.display=isErr?"none":"block";
}
function hideStatus(){ document.getElementById("statusBar").className="status-bar"; }

// ── Main analysis ─────────────────────────────────────────────────────────────
async function runAnalysis(){
  if(tickers.length<2){ showStatus("Add at least 2 tickers.",true); return; }
  showStatus("Fetching live market data from Yahoo Finance…");
  document.getElementById("analyzeBtn").disabled=true;
  document.getElementById("results").className="";

  try{
    const res = await fetch("/api/analyze",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        tickers, capital:+document.getElementById("capital").value,
        biweekly:+document.getElementById("biweekly").value,
        mode:currentMode
      })
    });
    const data = await res.json();
    if(data.error){ showStatus(data.error,true); return; }
    hideStatus();
    renderAll(data);
    document.getElementById("results").className="visible";
    document.getElementById("results").scrollIntoView({behavior:"smooth",block:"start"});
  } catch(e){
    showStatus("Network error — is the Flask server running?",true);
  } finally{
    document.getElementById("analyzeBtn").disabled=false;
  }
}

// ── Render everything ─────────────────────────────────────────────────────────
function renderAll(d){
  renderKPIs(d);
  renderPositionTable(d);
  renderWeightsChart(d);
  renderSectorChart(d);
  renderRCChart(d);
  renderFrontier(d);
  renderMonteCarlo(d);
  renderCorrMatrix(d);
  renderScenarios(d);
  renderScenarioTables(d);
}

function destroyChart(id){
  if(chartInstances[id]){ chartInstances[id].destroy(); delete chartInstances[id]; }
}

function renderKPIs(d){
  const p=d.portfolio;
  const cap=d.capital;
  const biwk=d.biweekly;
  document.getElementById("kpiStrip").innerHTML=`
    <div class="kpi kpi-green"><div class="kpi-label">Exp. Annual Return</div><div class="kpi-val">${p.ann_ret}%</div><div class="kpi-sub">fwd estimate</div></div>
    <div class="kpi"><div class="kpi-label">Portfolio Volatility</div><div class="kpi-val">${p.ann_vol}%</div><div class="kpi-sub">annualized</div></div>
    <div class="kpi kpi-blue"><div class="kpi-label">Sharpe Ratio</div><div class="kpi-val">${p.sharpe}</div><div class="kpi-sub">rf = 4.5%</div></div>
    <div class="kpi kpi-green"><div class="kpi-label">3yr Geometric Return</div><div class="kpi-val">${p.port_3yr_geom}%</div><div class="kpi-sub">compounded</div></div>
    <div class="kpi kpi-red"><div class="kpi-label">VaR 95% (1yr)</div><div class="kpi-val">${p.var_95}%</div><div class="kpi-sub">1-in-20 year</div></div>
    <div class="kpi kpi-red"><div class="kpi-label">Est. Max Drawdown</div><div class="kpi-val">${p.max_dd_est}%</div><div class="kpi-sub">2.5σ stress</div></div>`;
}

function renderPositionTable(d){
  const maxW = Math.max(...d.positions.map(p=>p.weight));
  document.getElementById("posBody").innerHTML = d.positions.map((p,i)=>{
    const col = tickerColor(p.ticker,i);
    const sec = d.sectors[p.ticker]?.sector||"Other";
    const rcClass = p.rc_pct>25?"tag-high":p.rc_pct>12?"tag-med":"tag-low";
    return `<tr>
      <td><span class="ticker-cell" style="color:${col}">${p.ticker}</span></td>
      <td style="color:var(--muted);font-size:11px">${sec}</td>
      <td style="font-weight:600">${p.weight}%</td>
      <td>$${p.dollars.toLocaleString()}</td>
      <td style="color:${p.ann_ret>=0?'var(--green)':'var(--red)'}">${p.ann_ret>=0?'+':''}${p.ann_ret}%</td>
      <td>${p.ann_vol}%</td>
      <td>${p.sharpe}</td>
      <td><span class="tag ${rcClass}">${p.rc_pct}%</span></td>
      <td><div class="bar-cell"><div class="bar-bg" style="max-width:100px"><div class="bar-fill" style="width:${(p.weight/maxW*100).toFixed(0)}%;background:${col}"></div></div></div></td>
    </tr>`;
  }).join("");
}

function renderWeightsChart(d){
  destroyChart("w");
  const ctx = document.getElementById("weightsChart").getContext("2d");
  chartInstances["w"] = new Chart(ctx,{
    type:"bar",
    data:{labels:d.tickers,datasets:[{data:d.weights,backgroundColor:d.tickers.map((t,i)=>tickerColor(t,i)),borderRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.parsed.y.toFixed(1)+"%"}}},
      scales:{x:{ticks:{color:"#78909c",font:{size:10,family:"DM Mono"}},grid:{display:false}},
              y:{ticks:{color:"#78909c",font:{size:9},callback:v=>v+"%"},grid:{color:"#eeece9"}}}}
  });
}

function renderSectorChart(d){
  destroyChart("s");
  const sectorMap={};
  d.positions.forEach(p=>{
    const sec = d.sectors[p.ticker]?.sector||"Other";
    const col = d.sectors[p.ticker]?.color||"#78909c";
    if(!sectorMap[sec]) sectorMap[sec]={weight:0,color:col};
    sectorMap[sec].weight += p.weight;
  });
  const labels=Object.keys(sectorMap);
  const vals=labels.map(k=>+sectorMap[k].weight.toFixed(1));
  const cols=labels.map(k=>sectorMap[k].color);
  const ctx=document.getElementById("sectorChart").getContext("2d");
  chartInstances["s"]=new Chart(ctx,{
    type:"doughnut",
    data:{labels,datasets:[{data:vals,backgroundColor:cols,borderWidth:2,borderColor:"#fff"}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:"55%",
      plugins:{legend:{position:"right",labels:{color:"#5a5a56",font:{size:10},padding:8,boxWidth:10}},
               tooltip:{callbacks:{label:c=>`${c.label}: ${c.parsed.toFixed(1)}%`}}}}
  });
}

function renderRCChart(d){
  destroyChart("rc");
  const rc=d.rc.map(v=>+(v*100).toFixed(1));
  const colors=d.tickers.map((t,i)=>{
    const r=rc[i]; return r>25?"#b71c1c":r>12?"#e65100":tickerColor(t,i);
  });
  const ctx=document.getElementById("rcChart").getContext("2d");
  chartInstances["rc"]=new Chart(ctx,{
    type:"bar",
    data:{labels:d.tickers,datasets:[{data:rc,backgroundColor:colors,borderRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.parsed.y.toFixed(1)+"% of portfolio risk"}}},
      scales:{x:{ticks:{color:"#78909c",font:{size:10,family:"DM Mono"}},grid:{display:false}},
              y:{ticks:{color:"#78909c",font:{size:9},callback:v=>v+"%"},grid:{color:"#eeece9"}}}}
  });
}

function renderFrontier(d){
  destroyChart("f");
  const ctx=document.getElementById("frontierChart").getContext("2d");
  chartInstances["f"]=new Chart(ctx,{
    type:"scatter",
    data:{datasets:[
      {label:"Efficient Frontier",data:d.frontier.map(p=>({x:p.vol,y:p.ret})),
       borderColor:"#1565c0",backgroundColor:"rgba(21,101,192,0.06)",
       showLine:true,tension:.4,pointRadius:0,borderWidth:2},
      {label:"Your Portfolio",data:[{x:d.portfolio.ann_vol,y:d.portfolio.ann_ret}],
       backgroundColor:"#e65100",borderColor:"#e65100",pointRadius:10,pointStyle:"star"},
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{labels:{color:"#5a5a56",font:{size:10},boxWidth:10}},
               tooltip:{callbacks:{label:c=>`Vol ${c.parsed.x.toFixed(1)}%  |  Ret ${c.parsed.y.toFixed(1)}%`}}},
      scales:{x:{title:{display:true,text:"Volatility (%)",color:"#78909c",font:{size:10}},
                 ticks:{color:"#78909c",font:{size:9}},grid:{color:"#eeece9"}},
              y:{title:{display:true,text:"Return (%)",color:"#78909c",font:{size:10}},
                 ticks:{color:"#78909c",font:{size:9}},grid:{color:"#eeece9"}}}}
  });
}

function renderMonteCarlo(d){
  destroyChart("mc");
  const paths=d.mc_paths;
  const labels=Array.from({length:37},(_,i)=>i===0?"Now":i===12?"Yr 1":i===24?"Yr 2":i===36?"Yr 3":"");
  // Compute percentiles at each step
  const pct=(arr,p)=>{const s=[...arr].sort((a,b)=>a-b);return s[Math.floor(s.length*p)];}
  const p5 =labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.05)));
  const p25=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.25)));
  const p50=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.50)));
  const p75=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.75)));
  const p95=labels.map((_,t)=>Math.round(pct(paths.map(p=>p[t]),.95)));

  // Show 40 random paths + percentile bands
  const pathDatasets=paths.slice(0,40).map(p=>({
    data:p,borderColor:"rgba(21,101,192,0.08)",borderWidth:1,
    pointRadius:0,fill:false,tension:.3
  }));

  const ctx=document.getElementById("mcChart").getContext("2d");
  chartInstances["mc"]=new Chart(ctx,{
    type:"line",
    data:{labels,datasets:[
      ...pathDatasets,
      {label:"95th pct",data:p95,borderColor:"rgba(46,125,50,.5)",borderWidth:1.5,borderDash:[4,3],pointRadius:0,fill:false},
      {label:"75th pct",data:p75,borderColor:"rgba(46,125,50,.8)",borderWidth:1.5,pointRadius:0,fill:false},
      {label:"Median",data:p50,borderColor:"#e65100",borderWidth:2.5,pointRadius:0,fill:false},
      {label:"25th pct",data:p25,borderColor:"rgba(163,45,45,.8)",borderWidth:1.5,pointRadius:0,fill:false},
      {label:"5th pct",data:p5, borderColor:"rgba(163,45,45,.5)",borderWidth:1.5,borderDash:[4,3],pointRadius:0,fill:false},
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{labels:{filter:i=>i.text!==undefined&&["Median","95th pct","5th pct"].includes(i.text),
                               color:"#5a5a56",font:{size:10},boxWidth:10}},
               tooltip:{mode:"index",intersect:false,filter:i=>["Median","95th pct","5th pct"].includes(i.dataset.label)}},
      scales:{x:{ticks:{color:"#78909c",font:{size:9}},grid:{color:"#eeece9"}},
              y:{ticks:{color:"#78909c",font:{size:9},callback:v=>"$"+Math.round(v/1000)+"K"},grid:{color:"#eeece9"}}}}
  });
}

function renderCorrMatrix(d){
  const tix=d.tickers, corr=d.corr;
  const head="<tr><th></th>"+tix.map(t=>`<th>${t}</th>`).join("")+"</tr>";
  const rows=tix.map((t,i)=>`<tr><td class="row-lbl">${t}</td>`+
    corr[i].map((v,j)=>{
      const c=Math.round(v*100)/100;
      const intensity=Math.abs(v);
      let bg=v>=.99?"#1565c0"
        :v>.6?`rgba(21,101,192,${(intensity*.75).toFixed(2)})`
        :v>.3?`rgba(21,101,192,${(intensity*.5).toFixed(2)})`
        :v>.1?`rgba(21,101,192,${(intensity*.3).toFixed(2)})`
        :"#f8f7f4";
      const fc=intensity>.55?"#fff":"#1a1a18";
      return `<td style="background:${bg};color:${fc};border-radius:3px;font-family:'DM Mono',monospace'>${c.toFixed(2)}</td>`;
    }).join("")+"</tr>"
  ).join("");
  document.getElementById("corrTable").innerHTML=head+rows;
}

function renderScenarios(d){
  const scens=d.scenarios;
  const cap=d.capital;
  const biwk=d.biweekly;
  document.getElementById("scenarioGrid").innerHTML=
    Object.entries(scens).map(([key,s])=>`
      <div class="scenario-card" style="background:${s.bg};border-color:${s.color}30">
        <div class="sc-label" style="color:${s.color}">${s.label}</div>
        <div class="sc-total" style="color:${s.color}">$${s.totals.yr3.toLocaleString()}</div>
        <div class="sc-sub" style="color:${s.color}">3-year total  ·  ${s.total_return_pct>0?'+':''}${s.total_return_pct}% return</div>
        <div class="sc-breakdown">
          <div class="sc-breakdown-title">Year-by-year</div>
          <div class="sc-row"><span>Year 1</span><span style="font-weight:600">$${s.totals.yr1.toLocaleString()}</span></div>
          <div class="sc-row"><span>Year 2</span><span style="font-weight:600">$${s.totals.yr2.toLocaleString()}</span></div>
          <div class="sc-row"><span>Year 3</span><span style="font-weight:600">$${s.totals.yr3.toLocaleString()}</span></div>
          <div class="sc-row" style="margin-top:6px;border-top:0.5px solid rgba(0,0,0,.15);padding-top:6px">
            <span style="font-size:10px;opacity:.7">Initial capital growth</span>
            <span style="font-size:11px">$${s.totals.yr3_init.toLocaleString()}</span>
          </div>
          <div class="sc-row">
            <span style="font-size:10px;opacity:.7">Contribution FV</span>
            <span style="font-size:11px;color:${s.color}">+$${s.totals.yr3_contrib.toLocaleString()}</span>
          </div>
        </div>
      </div>`
    ).join("");
}

function renderScenarioTables(d){
  const scens=d.scenarios;
  function scenRowHTML(r, i, s) {
    const col = tickerColor(r.ticker, i);
    const multColor = r.mult_3yr >= 0 ? 'var(--green)' : 'var(--red)';
    const multSign  = r.mult_3yr >= 0 ? '+' : '';
    const retSign   = r.ann_r   >= 0 ? '+' : '';
    return '<tr>'
      + '<td><span class="ticker-cell" style="color:' + col + '">' + r.ticker + '</span></td>'
      + '<td>' + r.weight + '%</td>'
      + '<td>$' + r.init.toLocaleString() + '</td>'
      + '<td style="color:' + multColor + '">' + multSign + (r.mult_3yr*100).toFixed(0) + '%</td>'
      + '<td>' + retSign + r.ann_r + '%</td>'
      + '<td style="font-weight:600">$' + r.yr1.toLocaleString() + '</td>'
      + '<td style="font-weight:600">$' + r.yr2.toLocaleString() + '</td>'
      + '<td style="font-weight:600;color:' + s.color + '">$' + r.yr3.toLocaleString() + '</td>'
      + '</tr>';
  }

  document.getElementById("scenarioTables").innerHTML =
    Object.entries(scens).map(([key, s]) => {
      const rowsHTML = s.rows.map((r, i) => scenRowHTML(r, i, s)).join("");
      return '<div class="chart-card" style="margin-bottom:16px">'
        + '<h3 style="color:' + s.color + '">' + s.label + '</h3>'
        + '<div style="overflow-x:auto;margin-top:12px">'
        + '<table class="pos-table"><thead><tr>'
        + '<th>Ticker</th><th>Weight</th><th>Init Alloc</th>'
        + '<th>3yr Mult</th><th>Ann Equiv Ret</th>'
        + '<th>Year 1 Total</th><th>Year 2 Total</th><th>Year 3 Total</th>'
        + '</tr></thead><tbody>'
        + rowsHTML
        + '<tr style="background:var(--surface);font-weight:700">'
        + '<td colspan="5" style="font-weight:600">PORTFOLIO TOTAL</td>'
        + '<td>$' + s.totals.yr1.toLocaleString() + '</td>'
        + '<td>$' + s.totals.yr2.toLocaleString() + '</td>'
        + '<td style="color:' + s.color + '">$' + s.totals.yr3.toLocaleString() + '</td>'
        + '</tr></tbody></table></div></div>';
    }).join("");
}

// ── Smart Suggestions ─────────────────────────────────────────────────────────
async function runSmart(){
  if(tickers.length<1){ showStatus("Add tickers first.",true); return; }
  showStatus("Analysing portfolio concentration…");
  try{
    const res=await fetch("/api/smart",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({tickers,weights:tickers.map(()=>1/tickers.length)})
    });
    const data=await res.json();
    hideStatus();
    renderSmart(data);
  } catch(e){
    showStatus("Could not load suggestions.",true);
  }
}

function renderSmart(data){
  const panel=document.getElementById("smartPanel");
  // Warnings
  document.getElementById("smartWarnings").innerHTML=
    data.warnings.map(w=>`<div class="warning-item">${w}</div>`).join("");
  // Complements
  document.getElementById("smartComplements").innerHTML=
    data.complements.map(s=>`
      <div class="smart-card">
        <div class="smart-card-left">
          <div class="sc-ticker" style="color:${TICKER_COLORS[s.ticker]||'#1565c0'}">${s.ticker}</div>
          <div class="smart-desc">${s.desc}</div>
          <div class="smart-rationale">${s.rationale}</div>
          <button class="btn-add-ticker" onclick="addSmartTicker('${s.ticker}')">+ Add to portfolio</button>
        </div>
        <div class="smart-stats">
          <div class="smart-ret">${s.exp_return}</div>
          <div class="smart-vol">vol ${s.ann_vol}</div>
        </div>
      </div>`).join("");
  // Diversifiers
  document.getElementById("smartDiversifiers").innerHTML=
    data.diversifiers.map(s=>`
      <div class="smart-card">
        <div class="smart-card-left">
          <div class="sc-ticker" style="color:#37474f">${s.ticker}</div>
          <div class="smart-desc">${s.desc}</div>
          <div class="smart-rationale">${s.rationale}</div>
          <button class="btn-add-ticker" onclick="addSmartTicker('${s.ticker}')">+ Add to portfolio</button>
        </div>
        <div class="smart-stats">
          <div class="smart-ret" style="color:var(--muted)">${s.exp_return}</div>
          <div class="smart-vol">vol ${s.ann_vol}</div>
        </div>
      </div>`).join("");
  panel.className="smart-panel visible";
  panel.scrollIntoView({behavior:"smooth",block:"start"});
}

function addSmartTicker(t){
  if(!tickers.includes(t)){ tickers.push(t); renderChips(); }
}

// ── Init ──────────────────────────────────────────────────────────────────────
loadDefault();


