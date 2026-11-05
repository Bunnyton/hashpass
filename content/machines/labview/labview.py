#!/usr/bin/python3
"""
hashpass standard lab viewer (spec docs/superpowers/specs/2026-11-05-визуализация-стендов-design.md).

Runs as root in the observer machine. Reads frames from mon0 (AF_PACKET), the host's status feed
/run/hp-lab/status.json, and forwards link/netem requests to /run/hp-lab/control.sock.
Serves the page and /api/state on 0.0.0.0:$LABVIEW_PORT (8080). Python 3 stdlib only.

A viewer of your own does the same with any tools: mon0 + /run/hp-lab are the whole contract.
"""
import collections
import http.client
import json
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IFACE = os.environ.get("LABVIEW_IFACE", "mon0")
PORT = int(os.environ.get("LABVIEW_PORT", "8080"))
FEED = "/run/hp-lab/status.json"
CONTROL = "/run/hp-lab/control.sock"
ETH_P_ALL = 0x0003
KEEP = 200

packets = collections.deque(maxlen=KEEP)
flows = {}           # (src, dst, proto) -> [frames, bytes, last ts]
total = {"frames": 0, "bytes": 0}
lock = threading.Lock()


def _mac(b):
    return ":".join(f"{x:02x}" for x in b)


def _ip(b):
    return socket.inet_ntoa(b)


def describe(frame):
    """Return (src, dst, proto, info) of an Ethernet frame."""
    if len(frame) < 14:
        return "?", "?", "?", ""
    dst, src, etype = frame[0:6], frame[6:12], struct.unpack("!H", frame[12:14])[0]
    body = frame[14:]
    if etype == 0x8100 and len(body) >= 4:
        etype, body = struct.unpack("!H", body[2:4])[0], body[4:]
    if etype == 0x0806 and len(body) >= 28:
        op = struct.unpack("!H", body[6:8])[0]
        spa, tpa = _ip(body[14:18]), _ip(body[24:28])
        info = f"кто {tpa}? скажи {spa}" if op == 1 else f"{spa} — это {_mac(body[8:14])}"
        return spa, tpa, "ARP", info
    if etype == 0x0800 and len(body) >= 20:
        ihl = (body[0] & 0x0F) * 4
        proto, s, d = body[9], _ip(body[12:16]), _ip(body[16:20])
        l4 = body[ihl:]
        if proto == 1 and len(l4) >= 1:
            kind = {0: "echo reply", 8: "echo request", 3: "unreachable", 11: "time exceeded"}
            return s, d, "ICMP", kind.get(l4[0], f"type {l4[0]}")
        if proto in (6, 17) and len(l4) >= 4:
            sp, dp = struct.unpack("!HH", l4[0:4])
            name = "TCP" if proto == 6 else "UDP"
            info = f"{sp} → {dp}"
            if proto == 6 and len(l4) >= 14:
                fl = l4[13]
                info += " " + "".join(c for c, bit in (("S", 2), ("A", 16), ("F", 1), ("R", 4), ("P", 8))
                                      if fl & bit)
            return s, d, f"{name}/{min(sp, dp) if min(sp, dp) < 1024 else dp}", info
        return s, d, f"IP/{proto}", ""
    if etype == 0x86DD:
        return _mac(src), _mac(dst), "IPv6", ""
    return _mac(src), _mac(dst), f"0x{etype:04x}", ""


def capture():
    """Read mon0 forever (it may appear a moment after the boot)."""
    while True:
        try:
            s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
            s.bind((IFACE, 0))
        except OSError:
            time.sleep(1)
            continue
        while True:
            frame = s.recv(65535)
            src, dst, proto, info = describe(frame)
            now = time.time()
            with lock:
                total["frames"] += 1
                total["bytes"] += len(frame)
                packets.append({"ts": now, "src": src, "dst": dst, "proto": proto,
                                "len": len(frame), "info": info})
                f = flows.setdefault((src, dst, proto), [0, 0, 0.0])
                f[0] += 1
                f[1] += len(frame)
                f[2] = now


def feed():
    try:
        with open(FEED, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class _UnixConn(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(CONTROL)


def control(path, body):
    conn = _UnixConn("lab")
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, resp.read()
    except OSError as e:
        return 502, json.dumps({"ok": False, "error": f"канал управления недоступен: {e}"}).encode()
    finally:
        conn.close()


def state():
    with lock:
        top = sorted(flows.items(), key=lambda kv: -kv[1][2])[:50]
        return {"status": feed(), "total": dict(total), "packets": list(packets)[-60:],
                "flows": [{"src": k[0], "dst": k[1], "proto": k[2], "frames": v[0], "bytes": v[1],
                           "last": v[2]} for k, v in top]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, data, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            self._send(200, json.dumps(state(), ensure_ascii=False).encode())
        elif self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b'{"ok": false}')

    def do_POST(self):
        if self.path not in ("/api/link", "/api/netem"):
            self._send(404, b'{"ok": false}')
            return
        size = min(int(self.headers.get("Content-Length") or 0), 4096)
        code, data = control(self.path[4:], self.rfile.read(size))
        self._send(code, data)


PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Стенд</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--mut:#6b7385;--line:#d9dde5;--ok:#1f9d55;--warn:#d98e04;--bad:#d64545;--acc:#2f6fdb}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--fg:#e6e9ef;--mut:#8b93a5;--line:#333a46}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
header{padding:14px 20px;display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
h1{font-size:18px;margin:0}.mut{color:var(--mut)}
main{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:16px;padding:0 20px 20px}
@media (max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;overflow:auto}
h2{font-size:14px;margin:0 0 10px}
table{border-collapse:collapse;width:100%;font:12px ui-monospace,monospace}
td,th{text-align:left;padding:3px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
.m{display:inline-block;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:4px;min-width:150px;vertical-align:top}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.running{background:var(--ok)}.starting{background:var(--warn)}.stopped{background:var(--bad)}
.if{font:12px ui-monospace,monospace;margin-top:4px}.down{color:var(--bad)}
button{font:12px system-ui;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;padding:2px 7px;cursor:pointer}
.net{border-left:4px solid var(--acc);padding-left:10px;margin-bottom:12px}
#err{color:var(--bad)}
</style></head><body>
<header><h1 id="title">Стенд</h1><span class="mut" id="sum"></span><span id="err"></span></header>
<main>
<section class="card"><h2>Сети и машины</h2><div id="nets"></div></section>
<section class="card"><h2>Кто с кем говорит</h2><table id="flows"></table></section>
<section class="card" style="grid-column:1/-1"><h2>Последние пакеты (mon0)</h2><table id="pk"></table></section>
</main>
<script>
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const kb=n=>n>1048576?(n/1048576).toFixed(1)+" МБ":n>1024?(n/1024).toFixed(1)+" КБ":n+" Б";
let ctl=[];
async function post(p,b){const r=await fetch(p,{method:"POST",body:JSON.stringify(b)});const j=await r.json().catch(()=>({}));
 document.getElementById("err").textContent=j.ok?"":(j.error||"ошибка");tick();}
function link(m,n,s){post("/api/link",{machine:m,net:n,state:s})}
function netem(m,n){const d=prompt("Задержка, мс (0 — снять)","200");if(d===null)return;const l=prompt("Потери, %","0");if(l===null)return;
 post("/api/netem",{machine:m,net:n,delay_ms:parseInt(d)||0,loss_pct:parseInt(l)||0})}
function draw(st){
 const s=st.status;document.getElementById("sum").textContent=`кадров ${st.total.frames}, ${kb(st.total.bytes)}`;
 if(!s){document.getElementById("nets").innerHTML='<p class="mut">ленты статуса нет (/run/hp-lab)</p>';return}
 document.getElementById("title").textContent="Стенд "+s.lab;ctl=(s.observer&&s.observer.control)||[];
 let h="";for(const net of s.networks){h+=`<div class="net"><b>${esc(net.name)}</b> <span class="mut">${esc(net.subnet)}${net.gateway?" · шлюз "+esc(net.gateway):""}</span><div>`;
  for(const m of s.machines){for(const i of m.ifaces){if(i.net!==net.name)continue;
   const ne=i.netem.delay_ms||i.netem.loss_pct?` · ${i.netem.delay_ms} мс, ${i.netem.loss_pct}%`:"";
   let b="";if(ctl.includes("link"))b+=`<button onclick="link('${m.name}','${net.name}','${i.link==="up"?"down":"up"}')">${i.link==="up"?"выдернуть":"вставить"}</button> `;
   if(ctl.includes("netem"))b+=`<button onclick="netem('${m.name}','${net.name}')">задержка</button>`;
   h+=`<div class="m"><span class="dot ${esc(m.state)}"></span><b>${esc(m.name)}</b>${m.console?' <span class="mut">консоль</span>':""}${m.observer?' <span class="mut">наблюдатель</span>':""}
    <div class="if ${i.link}">${esc(i.iface)} ${esc(i.addr)} · кабель ${i.link==="up"?"вставлен":"выдернут"}${ne}</div>
    <div class="if mut">↓ ${kb(i.rx_bytes)} ↑ ${kb(i.tx_bytes)}</div><div>${b}</div></div>`}}
  h+="</div></div>"}
 const lone=s.machines.filter(m=>!m.ifaces.length);if(lone.length)h+=`<div class="mut">вне сетей: ${lone.map(m=>esc(m.name)).join(", ")}</div>`;
 document.getElementById("nets").innerHTML=h;}
function tables(st){
 document.getElementById("flows").innerHTML="<tr><th>откуда</th><th>куда</th><th>протокол</th><th>кадров</th><th>объём</th></tr>"+
  st.flows.map(f=>`<tr><td>${esc(f.src)}</td><td>${esc(f.dst)}</td><td>${esc(f.proto)}</td><td>${f.frames}</td><td>${kb(f.bytes)}</td></tr>`).join("");
 document.getElementById("pk").innerHTML="<tr><th>время</th><th>откуда</th><th>куда</th><th>протокол</th><th>байт</th><th></th></tr>"+
  st.packets.slice().reverse().map(p=>`<tr><td>${new Date(p.ts*1000).toLocaleTimeString()}</td><td>${esc(p.src)}</td><td>${esc(p.dst)}</td><td>${esc(p.proto)}</td><td>${p.len}</td><td>${esc(p.info)}</td></tr>`).join("");}
async function tick(){try{const st=await (await fetch("/api/state")).json();draw(st);tables(st)}catch(e){document.getElementById("err").textContent="просмотрщик не отвечает"}}
tick();setInterval(tick,1000);
</script></body></html>
"""


def main():
    threading.Thread(target=capture, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
