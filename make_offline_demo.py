"""Build docs/demo/index.html: ONE self-contained page that replays real events with AtmosGuard's real verdicts.

    python make_offline_demo.py

The page needs no server, no internet and no libraries, so it works when the venue Wi-Fi does not. The verdicts are not
mocked: this script runs the actual pipeline (the trained station models in models/) over the CSVs in data/demo/ and
embeds the output. It also embeds the headline tables from results/summary.json if that file exists.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from atmos.config import load_settings, load_stations
from atmos.fusion import Pipeline
from atmos.schema import Reading

REPO = Path(__file__).resolve().parent
OUT = REPO / "docs" / "demo" / "index.html"


def run_event(csv: Path, station: str, settings: dict, stations: dict) -> list[dict]:
    df = pd.read_csv(csv, parse_dates=["timestamp"])
    pipe = Pipeline(settings, stations)
    pipe.load_models(station)
    out = []
    for t, a, b, c, flag in zip(df["timestamp"], df["temperature_c"], df["pressure_hpa"], df["humidity_pct"], df["noaa_flag"]):
        r = Reading(station_id=station, timestamp=t.to_pydatetime(), temperature_c=a, pressure_hpa=b, humidity_pct=c)
        v = pipe.process(r)
        out.append({"t": t.strftime("%Y-%m-%d %H:%M"), "T": r.temperature_c, "P": r.pressure_hpa, "RH": r.humidity_pct,
                    "v": v.verdict.value,
                    "c": v.confidence, "reason": v.reason, "flags": sorted({k.check.split(":")[0] for k in v.checks if k.flagged}),
                    "notices": v.notices, "noaa": int(flag)})
    return out


def main() -> int:
    settings = load_settings()
    stations = load_stations()
    demo_dir = REPO / "data" / "demo"
    stories = {}
    for line in (demo_dir / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| ") and ".csv" in line:
            f, sid, story = [x.strip() for x in line.strip("|").split("|")]
            stories[f] = (sid, story)
    events = []
    for f, (sid, story) in stories.items():
        samples = run_event(demo_dir / f, sid, settings, stations)
        counts = {k: sum(1 for s in samples if s["v"] == k) for k in ("VALID", "WEATHER", "SUSPECT", "FAULT")}
        events.append({"id": f.replace(".csv", ""), "station": sid, "story": story, "samples": samples, "counts": counts})
        print(f, counts)
    summary = None
    sp = REPO / "results" / "summary.json"
    if sp.exists():
        s = json.loads(sp.read_text(encoding="utf-8"))
        summary = {"note": s["note"], "phases": {k: {"title": v["title"], "subtitle": v["subtitle"], "headline": v["headline"]["rows"]}
                                                for k, v in s["phases"].items()}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(TEMPLATE.replace("__DATA__", json.dumps({"events": events, "summary": summary})), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AtmosGuard Replay</title>
<style>
:root{--bg:#fbfaf7;--card:#ffffff;--text:#16150f;--muted:#5b5a53;--line:rgba(60,60,50,.16);
--t:#2a78d6;--p:#eb6834;--rh:#1baf7a;--fault:#d03b3b;--suspect:#e6a10a;--weather:#4a3aa7;--valid:#8a8a80;--accent:#2a78d6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#12120f;--card:#1b1b17;--text:#f2f1ea;--muted:#b9b8ac;--line:rgba(220,220,200,.16);
--t:#3987e5;--p:#d95926;--rh:#199e70;--fault:#e25b5b;--suspect:#fab219;--weather:#9085e9;--valid:#8a8a80;--accent:#3987e5}}
:root[data-theme="dark"]{--bg:#12120f;--card:#1b1b17;--text:#f2f1ea;--muted:#b9b8ac;--line:rgba(220,220,200,.16);
--t:#3987e5;--p:#d95926;--rh:#199e70;--fault:#e25b5b;--suspect:#fab219;--weather:#9085e9;--valid:#8a8a80;--accent:#3987e5}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px}
.sub{color:var(--muted);margin:0 0 16px}
.banner{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--suspect);border-radius:8px;padding:10px 14px;margin:0 0 16px;font-size:14px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
select,button{font:inherit;color:var(--text);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer}
button.primary{background:var(--accent);color:#fff;border-color:transparent}
button:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.story{color:var(--muted);font-size:14px;margin:0 0 8px}
svg#chart{width:100%;height:auto;display:block}
.legend svg{width:14px;height:14px;flex:none}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin:6px 0}
.legend span{display:inline-flex;align-items:center;gap:6px}
.now{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.now div{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.now b{display:block;font-size:12px;color:var(--muted);font-weight:500}.now span{font-size:20px;font-variant-numeric:tabular-nums}
.verdict{font-weight:700}
.reason{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:14px;min-height:64px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}
.counts{font-size:13px;color:var(--muted)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.tabs button[aria-pressed="true"]{background:var(--accent);color:#fff;border-color:transparent}
</style>
</head>
<body>
<div class="wrap">
<h1>AtmosGuard replay of real events</h1>
<p class="sub">Real recorded weather from Indian airport stations (NOAA ISD). Nothing on this page is mocked: the verdicts and reasons are the output of the actual pipeline, run over these records.</p>
<div class="banner">Data are airport METAR records, not IMD AWS records. Whole degrees and whole hPa; humidity is derived from the dew point. Confidence is agreement between checks, not a probability. No fault is injected on this page.</div>

<div class="card">
  <div class="row">
    <label for="ev">Event</label><select id="ev"></select>
    <button class="primary" id="play" aria-label="Play or pause the replay">Play</button>
    <button id="step" aria-label="Step one reading">Step</button>
    <button id="all" aria-label="Show the whole event">Show all</button>
    <button id="theme" aria-label="Toggle dark and light">Light / dark</button>
  </div>
  <p class="story" id="story"></p>
  <div class="counts" id="counts"></div>
  <svg id="chart" viewBox="0 0 1000 610" role="img" aria-label="Temperature, pressure and humidity with verdict markers"></svg>
  <div class="legend" aria-hidden="true">
    <span><svg width="14" height="14"><circle cx="7" cy="7" r="3" fill="var(--valid)"/></svg>VALID (line only)</span>
    <span><svg width="14" height="14"><path d="M7 1 L13 12 L1 12 Z" fill="var(--weather)"/></svg>WEATHER (escalated)</span>
    <span><svg width="14" height="14"><path d="M7 1 L13 7 L7 13 L1 7 Z" fill="var(--suspect)"/></svg>SUSPECT</span>
    <span><svg width="14" height="14"><path d="M2 2 L12 12 M12 2 L2 12" stroke="var(--fault)" stroke-width="2.5"/></svg>FAULT</span>
  </div>
  <div class="now" id="now"></div>
  <div class="reason" id="reason"></div>
</div>

<h2>The evaluation these events sit inside</h2>
<div class="card" id="summary"></div>
<p class="sub" style="margin-top:12px">Full tables, protocol and limits: <code>results/REPORT.md</code>, <code>config/protocol.md</code>, <code>docs/WHAT_WE_DO_NOT_CLAIM.md</code>.</p>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const NS = 'http://www.w3.org/2000/svg';
const CH = [{k:'T',label:'Temperature (°C)',c:'--t'},{k:'P',label:'Pressure (hPa)',c:'--p'},{k:'RH',label:'Relative humidity (%)',c:'--rh'}];
let ev = D.events[0], upto = 0, timer = null;

function el(tag, attrs, parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e}
function marker(v,x,y,parent){
  const col = v==='FAULT'?'var(--fault)':v==='SUSPECT'?'var(--suspect)':'var(--weather)';
  if(v==='FAULT') el('path',{d:`M${x-6} ${y-6} L${x+6} ${y+6} M${x+6} ${y-6} L${x-6} ${y+6}`,stroke:col,'stroke-width':3,fill:'none'},parent);
  else if(v==='SUSPECT') el('path',{d:`M${x} ${y-7} L${x+7} ${y} L${x} ${y+7} L${x-7} ${y} Z`,fill:col,stroke:'var(--card)','stroke-width':1},parent);
  else el('path',{d:`M${x} ${y-7} L${x+7} ${y+6} L${x-7} ${y+6} Z`,fill:col,stroke:'var(--card)','stroke-width':1},parent);
}
function draw(){
  const svg=$('chart'); svg.innerHTML='';
  const S=ev.samples, n=S.length, W=1000, left=64, right=12, ph=150, gap=34, top=20;
  const xs=i=>left+(W-left-right)*(n<2?0:i/(n-1));
  CH.forEach((ch,ci)=>{
    const y0=top+ci*(ph+gap);
    const vals=S.map(s=>s[ch.k]).filter(v=>v!=null); let lo=Math.min(...vals), hi=Math.max(...vals); if(hi-lo<1){lo-=.5;hi+=.5}
    const pad=(hi-lo)*.08; lo-=pad; hi+=pad; const ys=v=>y0+ph-(v-lo)/(hi-lo)*ph;
    el('text',{x:left,y:y0-6,fill:css('--text'),'font-size':14,'font-weight':600},svg).textContent=ch.label;
    for(let g=0;g<=3;g++){const v=lo+(hi-lo)*g/3,y=ys(v);
      el('line',{x1:left,x2:W-right,y1:y,y2:y,stroke:css('--line')},svg);
      el('text',{x:left-8,y:y+4,'text-anchor':'end',fill:css('--muted'),'font-size':12},svg).textContent=v.toFixed(Math.abs(hi-lo)>20?0:1)}
    let d='',pen=false;
    for(let i=0;i<=upto;i++){const v=S[i][ch.k]; if(v==null){pen=false;continue} d+=(pen?'L':'M')+xs(i).toFixed(1)+' '+ys(v).toFixed(1)+' ';pen=true}
    el('path',{d,fill:'none',stroke:css(ch.c),'stroke-width':2.2,'stroke-linejoin':'round'},svg);
    for(let i=0;i<=upto;i++){const s=S[i]; if(s.v!=='VALID'&&s[ch.k]!=null) marker(s.v,xs(i),ys(s[ch.k]),svg)}
    if(upto<n) el('line',{x1:xs(upto),x2:xs(upto),y1:y0,y2:y0+ph,stroke:css('--accent'),'stroke-dasharray':'4 4'},svg);
  });
  const yb=top+3*(ph+gap)-14;
  [0,Math.floor((n-1)/2),n-1].forEach((i,k)=>el('text',{x:xs(i),y:yb+14,'text-anchor':k===0?'start':k===2?'end':'middle',fill:css('--muted'),'font-size':12},svg).textContent=S[i].t);
  const s=S[upto];
  $('now').innerHTML=`<div><b>Time (UTC)</b><span>${s.t}</span></div><div><b>Temperature</b><span>${s.T}</span></div><div><b>Pressure</b><span>${s.P}</span></div><div><b>Humidity</b><span>${s.RH==null?'—':s.RH}</span></div><div><b>Verdict</b><span class="verdict" style="color:${s.v==='FAULT'?'var(--fault)':s.v==='SUSPECT'?'var(--suspect)':s.v==='WEATHER'?'var(--weather)':'var(--text)'}">${s.v}</span></div><div><b>Confidence (agreement)</b><span>${s.c.toFixed(2)}</span></div>`;
  $('reason').textContent=s.reason+(s.notices&&s.notices.length?'  Notice: '+s.notices.join(' '):'')+(s.noaa?'  (NOAA flagged this value: '+(s.noaa===2?'erroneous':'suspect')+'.)':'');
}
function setEvent(i){ev=D.events[i];upto=0;stop();$('story').textContent=`${ev.station}: ${ev.story}`;const c=ev.counts;$('counts').textContent=`${ev.samples.length} readings: ${c.VALID} VALID, ${c.WEATHER} WEATHER, ${c.SUSPECT} SUSPECT, ${c.FAULT} FAULT`;draw()}
function stop(){if(timer){clearInterval(timer);timer=null;$('play').textContent='Play'}}
function tick(){if(upto>=ev.samples.length-1){stop();return}upto++;draw()}
D.events.forEach((e,i)=>{const o=document.createElement('option');o.value=i;o.textContent=e.id.replace(/_/g,' ');$('ev').appendChild(o)});
$('ev').onchange=e=>setEvent(+e.target.value);
$('play').onclick=()=>{if(timer){stop();return}if(upto>=ev.samples.length-1)upto=0;$('play').textContent='Pause';timer=setInterval(tick,90)};
$('step').onclick=()=>{stop();tick()};
$('all').onclick=()=>{stop();upto=ev.samples.length-1;draw()};
$('theme').onclick=()=>{const r=document.documentElement;const dark=(r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches);r.dataset.theme=dark?'light':'dark';draw()};
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
// summary
(function(){
  const box=$('summary'); const S=D.summary;
  if(!S){box.textContent='No evaluation summary embedded.';return}
  const names=Object.keys(S.phases); let cur=names[0];
  const tabs=document.createElement('div');tabs.className='tabs';box.appendChild(tabs);
  const body=document.createElement('div');box.appendChild(body);
  const note=document.createElement('p');note.className='sub';note.textContent=S.note;box.appendChild(note);
  function show(){
    tabs.innerHTML='';names.forEach(n=>{const b=document.createElement('button');b.textContent=n.replace('_',' ');b.setAttribute('aria-pressed',n===cur);b.onclick=()=>{cur=n;show()};tabs.appendChild(b)});
    const p=S.phases[cur];
    body.innerHTML=`<p class="story"><b>${p.title}</b><br>${p.subtitle}</p><table><tr><th>Question</th><th>Answer</th></tr>${p.headline.map(r=>`<tr><td>${r.question}</td><td>${r.answer}</td></tr>`).join('')}</table>`;
  }
  show();
})();
setEvent(0);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
