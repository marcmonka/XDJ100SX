"""
Signal Analyzer — live GPIO/ADC event viewer for XDJ-100SX Pico firmware.

Two execution modes:
  Web (TUI button): run_signal_analyzer_web(pi_client, stop_event, port)
  CLI (--analyze):  run_signal_analyzer_cli(pi_client)

All public functions take a pi_client as their first argument instead of
relying on a module-level global, following Dependency Inversion.
"""

from __future__ import annotations

import collections
import re
import sys
import threading
import time
from typing import Any, Callable

# ─── Pin map ─────────────────────────────────────────────────────────────────

SA_PIN_NAMES: dict[int, str] = {
     0: "EJECT",       1: "TRACK PREV",   2: "TRACK NEXT",   3: "SEARCH BACK",
     4: "SEARCH FWD",  5: "CUE",          6: "PLAY",         7: "JET",
     8: "ZIP",         9: "WAH",         10: "HOLD",         11: "TIME",
    12: "MSTR TEMPO",  14: "JOG A",       15: "LED CUE",     16: "LED PLAY",
    17: "LED INTL",    18: "LED CD",      19: "JOG B",       20: "BROWSE A",
    21: "BROWSE B",    22: "LOAD",
}
SA_BUTTON_PINS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 22]
SA_JOG_PINS    = [14, 19]
SA_BROWSE_PINS = [20, 21]
SA_LED_PINS    = [15, 16, 17, 18]
SA_ALL_PINS    = sorted(set(SA_BUTTON_PINS + SA_JOG_PINS + SA_BROWSE_PINS + SA_LED_PINS))

_BOUNCE_WINDOW_US = 50_000   # 50 ms: edges within this window on same pin = bounce
_WAVEFORM_LEN     = 40


# ─── Shared state ─────────────────────────────────────────────────────────────

class SAState:
    """Signal-analyzer state updated by a reader thread and read by display."""

    def __init__(self) -> None:
        self.lock             = threading.Lock()
        self.t_ref_us: int    = 0
        self.t_latest_us: int = 0
        self.running: bool    = False
        self.pin_state:    dict[int, int]    = {p: 1 for p in SA_ALL_PINS}
        self.pin_edges:    dict[int, int]    = {p: 0 for p in SA_ALL_PINS}
        self.pin_waveform: dict[int, Any]    = {
            p: collections.deque([1] * _WAVEFORM_LEN, maxlen=_WAVEFORM_LEN)
            for p in SA_ALL_PINS
        }
        self.bounce_count:  dict[int, int]   = {p: 0 for p in SA_BUTTON_PINS}
        self.bounce_max_us: dict[int, int]   = {p: 0 for p in SA_BUTTON_PINS}
        self._press_t0:    dict[int, int]    = {}
        self._press_n:     dict[int, int]    = {}
        self._press_last:  dict[int, int]    = {}
        self.jog_a_state = 1
        self.jog_b_state = 1
        self.jog_net     = 0
        self.adc_current  = 512
        self.adc_min      = 1023
        self.adc_max      = 0
        self.adc_sum      = 0.0
        self.adc_count    = 0
        self.adc_history: Any = collections.deque(maxlen=60)
        self.events: Any      = collections.deque(maxlen=20)

    def update_gpio(self, t_us: int, pin: int, val: int) -> None:
        with self.lock:
            if self.t_ref_us == 0:
                self.t_ref_us = t_us
            self.t_latest_us = t_us
            self.running = True
            if pin not in SA_ALL_PINS:
                return
            if val == self.pin_state.get(pin, 1):
                return
            self.pin_state[pin]  = val
            self.pin_edges[pin] += 1
            self.pin_waveform[pin].append(val)
            rel  = t_us - self.t_ref_us
            edge = "▔→▁" if val == 0 else "▁→▔"
            self.events.append((rel, pin, edge))
            if pin in SA_BUTTON_PINS:
                self._track_bounce(pin, t_us, val)
            if pin == 14:
                self.jog_a_state = val
                self.jog_net += 1 if val != self.jog_b_state else -1
            elif pin == 19:
                self.jog_b_state = val

    def _track_bounce(self, pin: int, t_us: int, val: int) -> None:
        if val == 0 and pin not in self._press_t0:
            self._press_t0[pin] = self._press_last[pin] = t_us
            self._press_n[pin]  = 1
            return
        if pin not in self._press_t0:
            return
        if t_us - self._press_last[pin] > _BOUNCE_WINDOW_US:
            del self._press_t0[pin], self._press_n[pin], self._press_last[pin]
            if val == 0:
                self._press_t0[pin] = self._press_last[pin] = t_us
                self._press_n[pin]  = 1
            return
        self._press_n[pin]    += 1
        self._press_last[pin]  = t_us
        if self._press_n[pin] > 2:
            dur = t_us - self._press_t0[pin]
            self.bounce_count[pin]  += 1
            self.bounce_max_us[pin]  = max(self.bounce_max_us.get(pin, 0), dur)

    def update_adc(self, t_us: int, val: int) -> None:
        with self.lock:
            if self.t_ref_us == 0:
                self.t_ref_us = t_us
            self.running     = True
            self.adc_current = val
            self.adc_min     = min(self.adc_min, val)
            self.adc_max     = max(self.adc_max, val)
            self.adc_sum    += val
            self.adc_count  += 1
            self.adc_history.append(val)

    def reset_counters(self) -> None:
        with self.lock:
            for p in SA_ALL_PINS:
                self.pin_edges[p] = 0
                cur = self.pin_state.get(p, 1)
                for _ in range(_WAVEFORM_LEN):
                    self.pin_waveform[p].append(cur)
            for p in SA_BUTTON_PINS:
                self.bounce_count[p] = 0
                self.bounce_max_us[p] = 0
            self._press_t0.clear(); self._press_n.clear(); self._press_last.clear()
            self.jog_net   = 0
            self.adc_min   = 1023; self.adc_max = 0
            self.adc_sum   = 0.0;  self.adc_count = 0
            self.adc_history.clear()
            self.events.clear()


# ─── Protocol parsing ─────────────────────────────────────────────────────────

def parse_line(line: str) -> tuple | None:
    """Parse one SA: protocol line from Pico Core 1."""
    if not line.startswith("SA:"):
        return None
    if line == "SA:START":
        return ("start",)
    if "ADC=" in line:
        m = re.search(r'ADC=(\d+).*T=(\d+)', line)
        if m:
            return ("adc", int(m.group(1)), int(m.group(2)))
        return None
    m = re.search(r'T=(\d+),P=(\d+),V=(\d+)', line)
    if m:
        return ("gpio", int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def open_channel(pi_client: Any) -> Any:
    """Open an SSH channel that streams /dev/ttyACM0 from the Pi."""
    transport = pi_client._ssh.get_transport()
    assert transport
    ch = transport.open_session()
    ch.set_combine_stderr(True)
    ch.exec_command("stty -F /dev/ttyACM0 115200 raw -echo 2>/dev/null; cat /dev/ttyACM0")
    return ch


# ─── Web server (SSE) ─────────────────────────────────────────────────────────

# Embedded HTML — kept in one place so the web UI and the Python server stay in sync.
_WEB_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>XDJ Signal Analyzer</title>
<style>
:root{--bg:#0d1117;--bg2:#161b22;--bg3:#21262d;--brd:#30363d;--txt:#c9d1d9;--dim:#6e7681;--blue:#58a6ff;--grn:#3fb950;--yel:#d29922;--red:#f85149;--cyan:#39c5cf;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--txt);font-family:'SF Mono','Fira Code','Cascadia Code',monospace;font-size:13px;overflow:hidden;height:100vh;display:flex;flex-direction:column;}
header{background:var(--bg2);border-bottom:1px solid var(--brd);padding:7px 16px;display:flex;align-items:center;gap:14px;flex-shrink:0;}
header h1{color:var(--blue);font-size:13px;font-weight:bold;}
#status{font-size:12px;}#elapsed,#evcount{color:var(--dim);font-size:12px;}
.hbtn{background:var(--bg3);border:1px solid var(--brd);color:var(--txt);padding:2px 10px;cursor:pointer;border-radius:3px;font-family:inherit;font-size:11px;margin-left:4px;}
.hbtn:hover{border-color:var(--blue);}
.fbar{background:var(--bg2);border-bottom:1px solid var(--brd);padding:5px 12px;display:flex;gap:6px;align-items:center;flex-shrink:0;}
.fbtn{background:var(--bg3);border:1px solid var(--brd);color:var(--dim);padding:2px 12px;cursor:pointer;border-radius:3px;font-family:inherit;font-size:12px;}
.fbtn.on{background:#1f6feb;border-color:#388bfd;color:#e6edf3;}
.hint{color:var(--dim);font-size:11px;margin-left:8px;}
.main{display:grid;grid-template-columns:1fr 270px;grid-template-rows:1fr 160px;flex:1;min-height:0;}
.tbl-wrap{overflow-y:auto;border-right:1px solid var(--brd);}
table{width:100%;border-collapse:collapse;}
thead th{position:sticky;top:0;background:var(--bg2);color:var(--dim);text-align:left;padding:4px 8px;border-bottom:1px solid var(--brd);font-weight:bold;font-size:11px;text-transform:uppercase;white-space:nowrap;}
tbody tr{border-bottom:1px solid var(--brd)22;}
tbody tr:hover{background:#ffffff09;}
tbody tr.sel{background:#1f6feb18;}
tbody td{padding:3px 8px;white-space:nowrap;}
.c-pin{color:var(--cyan);font-weight:bold;}.c-name{color:var(--dim);}
.c-hi{color:var(--grn);}.c-lo{color:var(--yel);}
.c-ed{color:var(--txt);}.c-bc{color:var(--red);}.c-dim{color:var(--dim);}
.wf{letter-spacing:-1px;}
.rpanel{display:flex;flex-direction:column;border-left:1px solid var(--brd);}
.rsec{padding:10px 12px;border-bottom:1px solid var(--brd);flex-shrink:0;}
.rsec.grow{flex:1;overflow:hidden;}
.rtitle{color:var(--cyan);font-size:10px;font-weight:bold;margin-bottom:6px;letter-spacing:.5px;}
.rcontent{font-size:12px;line-height:1.7;}
#adc-bar-bg{background:var(--bg3);border-radius:2px;height:8px;margin:5px 0;}
#adc-bar{height:8px;border-radius:2px;transition:width .06s;}
#adc-nums{color:var(--dim);font-size:11px;}
#adc-spark{color:var(--cyan);letter-spacing:-1px;font-size:11px;}
.log-wrap{grid-column:1/-1;border-top:1px solid var(--brd);overflow-y:auto;font-size:11px;}
.log-wrap::-webkit-scrollbar{width:4px;}.log-wrap::-webkit-scrollbar-thumb{background:var(--brd);}
.ev{display:flex;gap:10px;padding:1px 12px;}.ev:hover{background:#ffffff06;}
.ev-t{color:var(--dim);min-width:65px;}.ev-p{color:var(--cyan);min-width:36px;}
.ev-n{color:var(--dim);min-width:96px;}.ev-hi{color:var(--grn);}.ev-lo{color:var(--yel);}
.ev-bc{color:var(--red);font-size:10px;}.ev-err{color:var(--red);}
</style></head><body>
<header>
  <h1>⬡ XDJ Signal Analyzer</h1>
  <span id="status" style="color:#d29922">● connecting…</span>
  <span id="elapsed">00:00:00</span>│
  <span id="evcount">0 events</span>
  <span style="margin-left:auto">
    <button class="hbtn" onclick="resetAll()">Reset</button>
    <button class="hbtn" onclick="clearLog()">Clear Log</button>
  </span>
</header>
<div class="fbar">
  <button class="fbtn on" id="fb-all"     onclick="setFilter('all',this)">ALL</button>
  <button class="fbtn"    id="fb-buttons" onclick="setFilter('buttons',this)">BUTTONS</button>
  <button class="fbtn"    id="fb-jog"     onclick="setFilter('jog',this)">JOG</button>
  <button class="fbtn"    id="fb-leds"    onclick="setFilter('leds',this)">LEDs</button>
  <span class="hint">click row to inspect · SSE live stream</span>
</div>
<div class="main">
  <div class="tbl-wrap"><table>
    <thead><tr><th>PIN</th><th>NAME</th><th>STATE</th><th>EDGES</th><th>BOUNCE</th><th>MAX µs</th><th>WAVEFORM</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table></div>
  <div class="rpanel">
    <div class="rsec" id="det-sec">
      <div class="rtitle">━ SELECTED PIN ━━━━━━━━━━━━━━━━━━━━━━</div>
      <div class="rcontent" id="det" style="color:var(--dim)">↑ click a row</div>
    </div>
    <div class="rsec">
      <div class="rtitle">━ JOG QUADRATURE ━━━━━━━━━━━━━━━━━━━</div>
      <div class="rcontent" id="jog"></div>
    </div>
    <div class="rsec grow">
      <div class="rtitle">━ PITCH ADC  GP26 ━━━━━━━━━━━━━━━━━━━</div>
      <div id="adc-bar-bg"><div id="adc-bar" style="width:50%;background:var(--blue)"></div></div>
      <div id="adc-nums"></div>
      <div id="adc-spark"></div>
    </div>
  </div>
  <div class="log-wrap"><div id="evlog"></div></div>
</div>
<script>
const PIN_NAMES   = %%PIN_NAMES%%;
const BTN_PINS    = %%BTN_PINS%%;
const JOG_PINS    = %%JOG_PINS%%;
const LED_PINS    = %%LED_PINS%%;
const ALL_PINS    = %%ALL_PINS%%;
const HOST        = "%%HOST%%";
const FILTERS     = {all:ALL_PINS, buttons:BTN_PINS, jog:JOG_PINS, leds:LED_PINS};
let filter = ALL_PINS, selPin = null, jogNet = 0, evCount = 0, logCount = 0, tRef = null;
const t0 = Date.now();
const pins = {};
ALL_PINS.forEach(p => pins[p] = {val:1,edges:0,bounce:0,bm:0,wf:Array(24).fill(1)});

function buildTable() {
  const tb = document.getElementById('tbody');
  tb.innerHTML = '';
  filter.forEach(pin => {
    const tr = document.createElement('tr');
    tr.id = 'r'+pin; tr.onclick = ()=>selRow(pin);
    tr.innerHTML = '<td class="c-pin">GP'+String(pin).padStart(2,'0')+'</td>'
      +'<td class="c-name">'+(PIN_NAMES[pin]||'?')+'</td>'
      +'<td id="st'+pin+'" class="c-hi">▔ HI</td>'
      +'<td id="ed'+pin+'" class="c-ed">0</td>'
      +'<td id="bc'+pin+'" class="c-dim">—</td>'
      +'<td id="bm'+pin+'" class="c-dim">—</td>'
      +'<td id="wf'+pin+'" class="wf c-hi">'+'▔'.repeat(24)+'</td>';
    tb.appendChild(tr);
  });
}
buildTable();

function updRow(pin) {
  const p = pins[pin];
  const st = document.getElementById('st'+pin); if(!st)return;
  st.textContent = p.val?'▔ HI':'▁ LO'; st.className = p.val?'c-hi':'c-lo';
  document.getElementById('ed'+pin).textContent = p.edges;
  const bc=document.getElementById('bc'+pin);
  bc.textContent=p.bounce||'—'; bc.className=p.bounce?'c-bc':'c-dim';
  const bm=document.getElementById('bm'+pin);
  bm.textContent=p.bm||'—'; bm.className=p.bm?'c-bc':'c-dim';
  const wf=document.getElementById('wf'+pin);
  wf.textContent=p.wf.map(v=>v?'▔':'▁').join(''); wf.className='wf '+(p.val?'c-hi':'c-lo');
}
function selRow(pin) {
  selPin=pin;
  document.querySelectorAll('tbody tr').forEach(r=>r.classList.remove('sel'));
  const r=document.getElementById('r'+pin); if(r)r.classList.add('sel');
  updDet();
}
function updDet() {
  if(selPin===null)return;
  const p=pins[selPin], name=PIN_NAMES[selPin]||('GP'+selPin);
  const sc=p.val?'var(--grn)':'var(--yel)';
  const bc=p.bounce?`<span style="color:var(--red)">⚡ ×${p.bounce} max ${p.bm}µs</span>`:'<span style="color:var(--dim)">no bounce</span>';
  const wf=p.wf.map(v=>v?'▔':'▁').join('');
  document.getElementById('det').innerHTML=
    `<div style="color:var(--cyan);font-weight:bold">GP${String(selPin).padStart(2,'0')} ${name}</div>`
    +`<div><span style="color:${sc}">${p.val?'▔ HIGH':'▁ LOW'}</span> &nbsp;edges:<b>${p.edges}</b>&nbsp;${bc}</div>`
    +`<div style="color:${sc};letter-spacing:-1px;margin-top:4px;font-size:12px">${wf}</div>`;
}
function updJog() {
  const a=pins[14]||{val:1,wf:[],edges:0}, b=pins[19]||{val:1,wf:[],edges:0};
  const nc=jogNet>0?'var(--grn)':jogNet<0?'var(--yel)':'var(--dim)';
  document.getElementById('jog').innerHTML=
    `<div><span style="color:var(--grn)">A GP14</span> <span style="color:var(--grn);letter-spacing:-1px">${a.wf.map(v=>v?'▔':'▁').join('')}</span> <span style="color:var(--dim)">e:</span>${a.edges}</div>`
    +`<div><span style="color:var(--yel)">B GP19</span> <span style="color:var(--yel);letter-spacing:-1px">${b.wf.map(v=>v?'▔':'▁').join('')}</span> <span style="color:var(--dim)">e:</span>${b.edges}</div>`
    +`<div style="margin-top:4px">Net: <span style="color:${nc}">${jogNet>=0?'CW':'CCW'} ${Math.abs(jogNet)}</span></div>`;
}
function updADC(d) {
  const center=Math.abs(d.val-512)<=8;
  const pct=d.val/1023*100;
  document.getElementById('adc-bar').style.width=pct+'%';
  document.getElementById('adc-bar').style.background=center?'var(--grn)':'var(--yel)';
  const cs=center?'<span style="color:var(--grn)">● CENTER</span>'
    :`<span style="color:var(--yel)">${d.val-512>0?'+':''}${d.val-512} off</span>`;
  document.getElementById('adc-nums').innerHTML=
    `<span style="color:var(--dim)">val:</span>${d.val} ${cs} `
    +`<span style="color:var(--dim)">min:${d.min} max:${d.max} mean:${d.mean.toFixed(1)}</span>`;
  if(d.hist&&d.hist.length>1){
    const mn=Math.min(...d.hist),mx=Math.max(...d.hist),rng=mx-mn||1;
    const ch=' ▁▂▃▄▅▆▇█';
    document.getElementById('adc-spark').textContent=d.hist.slice(-44).map(v=>ch[Math.round((v-mn)*8/rng)]).join('');
  }
}
function setFilter(name,btn) {
  filter=FILTERS[name]||ALL_PINS;
  document.querySelectorAll('.fbtn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  buildTable(); filter.forEach(updRow);
}
function clearLog(){document.getElementById('evlog').innerHTML='';logCount=0;tRef=null;}
function resetAll(){
  ALL_PINS.forEach(p=>{pins[p]={val:pins[p]?.val??1,edges:0,bounce:0,bm:0,wf:Array(24).fill(pins[p]?.val??1)};updRow(p);});
  evCount=0;jogNet=0;document.getElementById('evcount').textContent='0 events';
  clearLog();updDet();updJog();
}
function addLog(ev) {
  if(!filter.includes(ev.pin))return;
  if(!tRef&&ev.t>0)tRef=ev.t;
  const rel=tRef?((ev.t-tRef)/1e6).toFixed(3):'0.000';
  const edge=ev.val?'<span class="ev-hi">▁→▔</span>':'<span class="ev-lo">▔→▁</span>';
  const bc=ev.bounce>0?`<span class="ev-bc"> ⚡×${ev.bounce}</span>`:'';
  const div=document.createElement('div'); div.className='ev';
  div.innerHTML=`<span class="ev-t">${rel}s</span><span class="ev-p">GP${String(ev.pin).padStart(2,'0')}</span>`
    +`<span class="ev-n">${PIN_NAMES[ev.pin]||''}</span>${edge}${bc}`;
  const log=document.getElementById('evlog'); log.appendChild(div);
  logCount++; if(logCount>500)log.removeChild(log.firstChild);
  log.parentElement.scrollTop=log.parentElement.scrollHeight;
}
setInterval(()=>{
  const el=Math.floor((Date.now()-t0)/1000);
  document.getElementById('elapsed').textContent=
    String(Math.floor(el/3600)).padStart(2,'0')+':'+String(Math.floor((el%3600)/60)).padStart(2,'0')+':'+String(el%60).padStart(2,'0');
},1000);
function connect() {
  const es=new EventSource('/stream');
  es.onopen=()=>{document.getElementById('status').textContent='● '+HOST;document.getElementById('status').style.color='var(--grn)';};
  es.onmessage=e=>{
    const ev=JSON.parse(e.data);
    if(ev.type==='gpio'){
      const prev=pins[ev.pin]||{};
      pins[ev.pin]={val:ev.val,edges:ev.edges,bounce:ev.bounce,bm:ev.bounce_max_us,wf:ev.wf};
      if(ev.pin===19&&prev.val!==undefined&&ev.val===0&&prev.val===1)
        jogNet+=(pins[14]?.val===0)?1:-1;
      updRow(ev.pin);
      if(ev.pin===selPin)updDet();
      if(ev.pin===14||ev.pin===19)updJog();
      if(ev.t>0){evCount++;document.getElementById('evcount').textContent=evCount+' events';addLog(ev);}
    } else if(ev.type==='adc'){
      updADC(ev);
    } else if(ev.type==='error'){
      const div=document.createElement('div');div.className='ev ev-err';
      div.textContent='⚠ '+ev.msg;document.getElementById('evlog').appendChild(div);
      document.getElementById('status').textContent='⚠ disconnected';
      document.getElementById('status').style.color='var(--red)';
      es.close();setTimeout(connect,3000);
    }
  };
  es.onerror=()=>{
    document.getElementById('status').textContent='● reconnecting…';
    document.getElementById('status').style.color='var(--yel)';
    es.close();setTimeout(connect,3000);
  };
}
updJog();connect();
</script></body></html>"""


def run_signal_analyzer_web(pi_client: Any, stop_event: threading.Event, port: int) -> None:
    """HTTP + SSE server that streams GPIO/ADC events to a browser page.

    Blocks until stop_event is set — run in a daemon thread.
    """
    import json as _json
    import http.server
    import socketserver

    state   = SAState()
    clients: list = []
    clock   = threading.Lock()

    def _broadcast(msg: dict) -> None:
        data = ("data: " + _json.dumps(msg) + "\n\n").encode()
        with clock:
            dead = []
            for w in list(clients):
                try:
                    w.write(data); w.flush()
                except Exception:
                    dead.append(w)
            for w in dead:
                clients.remove(w)

    def _reader() -> None:
        try:
            ch  = open_channel(pi_client)
            buf = b""
            while not stop_event.is_set():
                if ch.recv_ready():
                    buf += ch.recv(4096)
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        parsed = parse_line(raw.decode(errors="replace").strip())
                        if not parsed:
                            continue
                        if parsed[0] == "gpio":
                            t_us, pin, val = parsed[1], parsed[2], parsed[3]
                            state.update_gpio(t_us, pin, val)
                            with state.lock:
                                _broadcast({
                                    "type": "gpio", "pin": pin, "val": val, "t": t_us,
                                    "name": SA_PIN_NAMES.get(pin, f"GP{pin}"),
                                    "edges": state.pin_edges.get(pin, 0),
                                    "bounce": state.bounce_count.get(pin, 0),
                                    "bounce_max_us": state.bounce_max_us.get(pin, 0),
                                    "wf": list(state.pin_waveform.get(pin, []))[-24:],
                                })
                        elif parsed[0] == "adc":
                            state.update_adc(parsed[2], parsed[1])
                            with state.lock:
                                n = state.adc_count or 1
                                _broadcast({
                                    "type": "adc",
                                    "val": state.adc_current, "min": state.adc_min,
                                    "max": state.adc_max,     "mean": state.adc_sum / n,
                                    "hist": list(state.adc_history)[-44:],
                                })
                elif ch.exit_status_ready():
                    _broadcast({"type": "error", "msg": "Serial stream closed — Pico disconnected?"})
                    break
                else:
                    time.sleep(0.01)
            ch.close()
        except Exception as exc:
            _broadcast({"type": "error", "msg": str(exc)})

    threading.Thread(target=_reader, daemon=True).start()

    html = (_WEB_HTML
            .replace("%%PIN_NAMES%%", _json.dumps({str(k): v for k, v in SA_PIN_NAMES.items()}))
            .replace("%%BTN_PINS%%",  _json.dumps(SA_BUTTON_PINS))
            .replace("%%JOG_PINS%%",  _json.dumps(SA_JOG_PINS + SA_BROWSE_PINS))
            .replace("%%LED_PINS%%",  _json.dumps(SA_LED_PINS))
            .replace("%%ALL_PINS%%",  _json.dumps(SA_ALL_PINS))
            .replace("%%HOST%%",      pi_client.host))
    html_b = html.encode()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_b)))
                self.end_headers()
                self.wfile.write(html_b)

            elif self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with state.lock:
                    for pin in SA_ALL_PINS:
                        snap = {
                            "type": "gpio", "pin": pin,
                            "val": state.pin_state.get(pin, 1), "t": 0,
                            "name": SA_PIN_NAMES.get(pin, f"GP{pin}"),
                            "edges": state.pin_edges.get(pin, 0),
                            "bounce": state.bounce_count.get(pin, 0),
                            "bounce_max_us": state.bounce_max_us.get(pin, 0),
                            "wf": list(state.pin_waveform.get(pin, []))[-24:],
                        }
                        self.wfile.write(("data: " + _json.dumps(snap) + "\n\n").encode())
                self.wfile.flush()
                with clock:
                    clients.append(self.wfile)
                try:
                    while not stop_event.is_set():
                        time.sleep(1)
                        self.wfile.write(b": ka\n\n")
                        self.wfile.flush()
                except Exception:
                    pass
                finally:
                    with clock:
                        try: clients.remove(self.wfile)
                        except ValueError: pass
            else:
                self.send_error(404)

    class _Server(socketserver.TCPServer):
        allow_reuse_address = True

    with _Server(("", port), _Handler) as srv:
        srv.timeout = 0.5
        while not stop_event.is_set():
            srv.handle_request()


# ─── CLI dashboard (Textual) ──────────────────────────────────────────────────

def run_signal_analyzer_cli(pi_client: Any) -> None:
    """Launch the full Textual signal analyzer dashboard (--analyze flag)."""
    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Button, DataTable, Footer, RichLog, Static
        from textual import work as _tw
        from rich.text import Text
    except ImportError:
        print("textual not installed — run: pip install textual", file=sys.stderr)
        return

    chk = pi_client.exec("ls /dev/ttyACM0 2>/dev/null || echo MISSING")
    if "MISSING" in chk["stdout"]:
        print("/dev/ttyACM0 not found — Pico not connected or firmware not flashed", file=sys.stderr)
        return

    state  = SAState()
    stop   = threading.Event()

    FILTER_GROUPS: dict[str, list[int]] = {
        "g-all":     SA_ALL_PINS,
        "g-buttons": SA_BUTTON_PINS,
        "g-jog":     SA_JOG_PINS + SA_BROWSE_PINS,
        "g-leds":    SA_LED_PINS,
    }

    class SignalAnalyzerApp(App):  # type: ignore[misc]
        TITLE = "XDJ Signal Analyzer"
        CSS = """
        Screen { background: #0d1117; color: #c9d1d9; }
        #hdr { height: 1; padding: 0 2; background: #161b22; color: #58a6ff; content-align: left middle; }
        #fbar { height: 3; padding: 0 1; background: #161b22; border-bottom: solid #30363d; align: left middle; }
        .gbtn { height: 1; min-width: 11; border: solid #30363d; margin-right: 1; background: #21262d; color: #8b949e; }
        .gbtn.-on { background: #1f6feb; color: #e6edf3; border: solid #388bfd; }
        #fhint { color: #6e7681; margin-left: 2; }
        #body { height: 1fr; }
        #left  { width: 58; border-right: solid #21262d; }
        DataTable { height: 1fr; }
        DataTable > .datatable--header { background: #161b22; color: #8b949e; text-style: bold; }
        DataTable > .datatable--cursor { background: #1f6feb33; }
        DataTable > .datatable--zebra-stripe { background: #161b2244; }
        #right { width: 1fr; padding: 0; }
        #detail { height: 7; border-bottom: solid #21262d; padding: 1 2; background: #161b22; }
        #jog    { height: 8; border-bottom: solid #21262d; padding: 1 2; background: #0d1117; }
        #adc    { height: 1fr; padding: 1 2; background: #161b22; }
        #evlog  { height: 8; border-top: solid #21262d; }
        """

        BINDINGS = [
            Binding("q",     "quit",        "Quit"),
            Binding("r",     "reset_all",   "Reset"),
            Binding("l",     "clear_log",   "Clear log"),
            Binding("space", "toggle_pin",  "Toggle"),
            Binding("i",     "isolate_pin", "Isolate"),
            Binding("a",     "show_all",    "All"),
            Binding("1",     "grp1",        "Buttons"),
            Binding("2",     "grp2",        "Jog"),
            Binding("3",     "grp3",        "LEDs"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._t0         = time.time()
            self._visible:   set[int] = set(SA_ALL_PINS)
            self._last_chk:  dict[int, str] = {}

        def compose(self) -> ComposeResult:
            yield Static("", id="hdr")
            with Horizontal(id="fbar"):
                yield Button("ALL",     id="g-all",     classes="gbtn -on")
                yield Button("BUTTONS", id="g-buttons", classes="gbtn")
                yield Button("JOG",     id="g-jog",     classes="gbtn")
                yield Button("LEDs",    id="g-leds",    classes="gbtn")
                yield Static(
                    "  ↑↓ select   [bold]Space[/]:toggle   [bold]I[/]:isolate   "
                    "[bold]A[/]:all   [bold]1-3[/]:group   [bold]R[/]:reset   [bold]L[/]:clear log",
                    id="fhint",
                )
            with Horizontal(id="body"):
                with Vertical(id="left"):
                    yield DataTable(id="tbl", cursor_type="row", zebra_stripes=True)
                with Vertical(id="right"):
                    yield Static("", id="detail")
                    yield Static("", id="jog")
                    yield Static("", id="adc")
            yield RichLog(id="evlog", highlight=True, markup=True, max_lines=500)
            yield Footer()

        def on_mount(self) -> None:
            self._rebuild_table()
            self.set_interval(0.15, self._tick)
            self._start_reader()

        def on_worker_state_changed(self, event: object) -> None:
            pass  # suppress app exit on unhandled worker exception

        @_tw(thread=True)
        def _start_reader(self) -> None:
            try:
                evlog   = self.query_one("#evlog", RichLog)
                channel = open_channel(pi_client)
                buf     = b""
                while not stop.is_set():
                    if channel.recv_ready():
                        buf += channel.recv(4096)
                        while b"\n" in buf:
                            raw, buf = buf.split(b"\n", 1)
                            parsed = parse_line(raw.decode(errors="replace").strip())
                            if parsed is None:
                                continue
                            if parsed[0] == "gpio":
                                t_us, pin, val = parsed[1], parsed[2], parsed[3]
                                state.update_gpio(t_us, pin, val)
                                if pin in self._visible:
                                    self.call_from_thread(self._log_gpio, t_us, pin, val)
                            elif parsed[0] == "adc":
                                state.update_adc(parsed[2], parsed[1])
                    elif channel.exit_status_ready():
                        self.call_from_thread(
                            evlog.write, "[red]⚠ Serial stream closed — Pico disconnected?[/]"
                        )
                        break
                    else:
                        time.sleep(0.01)
                channel.close()
            except Exception as exc:
                try:
                    self.call_from_thread(
                        self.query_one("#evlog", RichLog).write,
                        f"[red bold]Reader error:[/] [red]{exc}[/]",
                    )
                except Exception:
                    pass

        def _log_gpio(self, t_us: int, pin: int, val: int) -> None:
            name  = SA_PIN_NAMES.get(pin, f"GP{pin}")
            edge  = "[green]▁→▔[/]" if val else "[yellow]▔→▁[/]"
            rel_s = (t_us - state.t_ref_us) / 1_000_000 if state.t_ref_us else 0.0
            with state.lock:
                bc = state.bounce_count.get(pin, 0)
            bc_s = f"  [red bold]⚡ bounce ×{bc}[/]" if bc else ""
            self.query_one("#evlog", RichLog).write(
                f"[dim]{rel_s:9.3f}s[/]  [cyan]GP{pin:02d}[/]  {name:<14}  {edge}{bc_s}"
            )

        def _rebuild_table(self) -> None:
            tbl = self.query_one("#tbl", DataTable)
            tbl.clear(columns=True)
            tbl.add_column("PIN",     key="pin",  width=6)
            tbl.add_column("NAME",    key="name", width=14)
            tbl.add_column("STATE",   key="st",   width=6)
            tbl.add_column("EDGES",   key="ed",   width=7)
            tbl.add_column("BOUNCE",  key="bc",   width=8)
            tbl.add_column("MAX µs",  key="bm",   width=9)
            tbl.add_column("WAVEFORM (last 24)", key="wf", width=26)
            self._last_chk.clear()
            for pin in sorted(p for p in SA_ALL_PINS if p in self._visible):
                tbl.add_row(
                    f"GP{pin:02d}", SA_PIN_NAMES.get(pin, "?"),
                    "▔ HI", "0", "—", "—", "▔" * 24,
                    key=str(pin),
                )

        def _tick(self) -> None:
            el = time.time() - self._t0
            hh = int(el)//3600; mm = (int(el)%3600)//60; ss = int(el)%60
            with state.lock:
                tot = sum(state.pin_edges.values())
            self.query_one("#hdr", Static).update(
                f"[bold cyan]XDJ Signal Analyzer[/]  │  [green]{pi_client.host}[/]  │  "
                f"[dim]{hh:02d}:{mm:02d}:{ss:02d}[/]  │  total events: [bold]{tot}[/]"
            )
            self._update_table()
            self._update_right()

        def _update_table(self) -> None:
            tbl  = self.query_one("#tbl", DataTable)
            pins = sorted(p for p in SA_ALL_PINS if p in self._visible)
            with state.lock:
                snap = {
                    p: (
                        state.pin_state.get(p, 1),
                        state.pin_edges.get(p, 0),
                        state.bounce_count.get(p, 0),
                        state.bounce_max_us.get(p, 0),
                        list(state.pin_waveform.get(p, []))[-24:],
                    )
                    for p in pins
                }
            for pin in pins:
                s_, ed, bc, bm, wf = snap[pin]
                chk = f"{s_},{ed},{bc}"
                if self._last_chk.get(pin) == chk:
                    continue
                self._last_chk[pin] = chk
                rk   = str(pin)
                st_c = "green" if s_ else "yellow"
                ed_c = "bold white" if ed > 0 else "dim"
                bc_c = "red bold" if bc > 0 else "dim"
                wf_s = "".join("▔" if x else "▁" for x in wf)
                try:
                    tbl.update_cell(rk, "st", Text("▔ HI" if s_ else "▁ LO", style=st_c), update_width=False)
                    tbl.update_cell(rk, "ed", Text(str(ed), style=ed_c),                   update_width=False)
                    tbl.update_cell(rk, "bc", Text(str(bc) if bc else "—", style=bc_c),    update_width=False)
                    tbl.update_cell(rk, "bm", Text(str(bm) if bm else "—", style="red" if bm else "dim"), update_width=False)
                    tbl.update_cell(rk, "wf", Text(wf_s, style=st_c),                      update_width=False)
                except Exception:
                    pass

        def _update_right(self) -> None:
            tbl = self.query_one("#tbl", DataTable)
            sel_pin: int | None = None
            try:
                rk = tbl.cursor_row_key
                if rk is not None:
                    sel_pin = int(str(rk))
            except Exception:
                pass

            if sel_pin is not None and sel_pin in self._visible:
                with state.lock:
                    s_   = state.pin_state.get(sel_pin, 1)
                    ed   = state.pin_edges.get(sel_pin, 0)
                    bc   = state.bounce_count.get(sel_pin, 0)
                    bm   = state.bounce_max_us.get(sel_pin, 0)
                    wf   = list(state.pin_waveform.get(sel_pin, []))
                name = SA_PIN_NAMES.get(sel_pin, f"GP{sel_pin}")
                st_c = "green" if s_ else "yellow"
                wf_s = "".join("▔" if x else "▁" for x in wf)
                bc_s = (f"[red]⚡ bounce ×{bc}   longest: {bm} µs[/]"
                        if bc else "[dim]no bounce detected[/]")
                self.query_one("#detail", Static).update(
                    f"[bold cyan]━━ GP{sel_pin:02d}  {name} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]\n"
                    f"  [{st_c}]{'▔ HIGH' if s_ else '▁ LOW '}[/]   edges: [bold]{ed}[/]   {bc_s}\n\n"
                    f"  [{st_c}]{wf_s}[/]"
                )
            else:
                self.query_one("#detail", Static).update(
                    "[dim]  ↑↓ navigate the table to inspect a pin[/]"
                )

            with state.lock:
                wf_a = list(state.pin_waveform.get(14, []))
                wf_b = list(state.pin_waveform.get(19, []))
                a_ed = state.pin_edges.get(14, 0)
                b_ed = state.pin_edges.get(19, 0)
                net  = state.jog_net
            wf_a_s = "".join("▔" if x else "▁" for x in wf_a)
            wf_b_s = "".join("▔" if x else "▁" for x in wf_b)
            nc  = "green" if net > 0 else ("yellow" if net < 0 else "dim")
            ds  = "CW" if net >= 0 else "CCW"
            self.query_one("#jog", Static).update(
                f"[bold cyan]━━ JOG QUADRATURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]\n"
                f"  [green]A GP14[/]  [green]{wf_a_s}[/]  [dim]edges:[/] [bold]{a_ed}[/]\n"
                f"  [yellow]B GP19[/]  [yellow]{wf_b_s}[/]  [dim]edges:[/] [bold]{b_ed}[/]\n\n"
                f"  Net: [{nc}]{ds} {abs(net):5d}[/] ticks   "
                f"[dim]A:{a_ed}  B:{b_ed}  diff:{abs(a_ed - b_ed)}[/]"
            )

            with state.lock:
                av    = state.adc_current
                amin  = state.adc_min   if state.adc_count > 0 else 512
                amax  = state.adc_max   if state.adc_count > 0 else 512
                amean = (state.adc_sum / state.adc_count) if state.adc_count > 0 else 512.0
                hist  = list(state.adc_history)
                cnt   = state.adc_count
            center = abs(av - 512) <= 8
            adc_c  = "green" if center else "yellow"
            blen   = 34
            filled = max(0, min(blen, av * blen // 1024))
            bar    = "█" * filled + "░" * (blen - filled)
            spc    = " ▁▂▃▄▅▆▇█"
            if hist and cnt > 1:
                mn, mx = min(hist), max(hist); rng = mx - mn or 1
                spark  = "".join(spc[int((v - mn) * 8 // rng)] for v in hist[-44:])
            else:
                spark  = "[dim](waiting for samples…)[/]"
            jitter = (amax - amin) // 2 if cnt > 0 else 0
            ctr_s  = "[green]● CENTER[/]" if center else f"[yellow]{av - 512:+d} off center[/]"
            self.query_one("#adc", Static).update(
                f"[bold cyan]━━ PITCH ADC  GP26/ADC0 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]\n\n"
                f"  [{adc_c}][{bar}][/]  [{adc_c}]{av:4d}[/]  {ctr_s}\n\n"
                f"  [dim]min:[/][cyan]{amin}[/]  [dim]max:[/][cyan]{amax}[/]  "
                f"[dim]mean:[/][cyan]{amean:.1f}[/]  "
                f"[dim]jitter:[/][{'green' if jitter < 5 else 'yellow'}]±{jitter}[/]\n\n"
                f"  [cyan]{spark}[/]"
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            bid = event.button.id
            if bid not in FILTER_GROUPS:
                return
            for fid in FILTER_GROUPS:
                self.query_one(f"#{fid}", Button).remove_class("-on")
            event.button.add_class("-on")
            new = set(FILTER_GROUPS[bid])
            if new != self._visible:
                self._visible = new
                self._rebuild_table()

        def action_toggle_pin(self) -> None:
            tbl = self.query_one("#tbl", DataTable)
            try:
                pin = int(str(tbl.cursor_row_key))
            except Exception:
                return
            if pin in self._visible:
                self._visible.discard(pin)
            else:
                self._visible.add(pin)
            self._rebuild_table()

        def action_isolate_pin(self) -> None:
            tbl = self.query_one("#tbl", DataTable)
            try:
                pin = int(str(tbl.cursor_row_key))
            except Exception:
                return
            self._visible = {pin}
            for fid in FILTER_GROUPS:
                self.query_one(f"#{fid}", Button).remove_class("-on")
            self._rebuild_table()

        def action_show_all(self) -> None:
            self._visible = set(SA_ALL_PINS)
            for fid in FILTER_GROUPS:
                self.query_one(f"#{fid}", Button).remove_class("-on")
            self.query_one("#g-all", Button).add_class("-on")
            self._rebuild_table()

        def action_grp1(self) -> None:
            self.query_one("#g-buttons", Button).press()

        def action_grp2(self) -> None:
            self.query_one("#g-jog", Button).press()

        def action_grp3(self) -> None:
            self.query_one("#g-leds", Button).press()

        def action_clear_log(self) -> None:
            log = self.query_one("#evlog", RichLog)
            log.clear()
            log.write("[dim]── log cleared ──[/]")

        def action_reset_all(self) -> None:
            state.reset_counters()
            self._t0 = time.time()
            self._last_chk.clear()
            log = self.query_one("#evlog", RichLog)
            log.clear()
            log.write("[dim]── counters reset ──[/]")

        def on_unmount(self) -> None:
            stop.set()

    SignalAnalyzerApp().run()
    stop.set()
