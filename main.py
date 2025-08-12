# main.py — AXO Referral Engine (stable, cached XRP updater)

import os, time, json, functools, threading

from typing import Any, Dict, Tuple, Optional



from pathlib import Path

from dotenv import load_dotenv

from flask import Flask, request, jsonify, session, render_template_string

import requests



# ------------------ Env ------------------

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")   # loads ADMIN_PIN, WALLET_SEED, etc.



app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-me-please")



ADMIN_PIN       = os.environ.get("ADMIN_PIN", "")

AXO_PRICE_USD   = float(os.environ.get("AXO_PRICE", "0.01"))

XRP_VAULT_ADDR  = os.environ.get("XRP_VAULT_ADDR", "")

WALLET_SEED     = os.environ.get("WALLET_SEED", "")



# ---------------- Settings (admin-editable in-memory) ----------------

SETTINGS: Dict[str, Any] = {

    "signup_bonus": 1000,

    "referral_reward": 300,

    "require_trustline": True,

    "axo_price_usd": AXO_PRICE_USD,

    "buy_enabled": True,

    "quick_signup_enabled": False,

    "fee_xrp": 0.25,

    "vault_addr": XRP_VAULT_ADDR,

    "daily_cap_axo": 0,

    "max_claims_per_wallet": 1,

    "rate_limit_claims_per_hour": 6,

    "whitelist_addresses": [],

    "blacklist_addresses": [],

    "airdrop_paused": False,

    "maintenance_mode": False,

}



# ---------------- Cached XRP price updater ----------------

PRICE_CACHE = {"xrp_usd": None, "updated": 0.0}

_PRICE_LOCK = threading.Lock()



def _try(fn, *a, **kw):

    try:

        return fn(*a, **kw)

    except Exception:

        return None



def _from_coingecko() -> float:

    r = requests.get(

        "https://api.coingecko.com/api/v3/simple/price",

        params={"ids": "ripple", "vs_currencies": "usd"},

        timeout=7,

        headers={"Accept": "application/json"},

    )

    r.raise_for_status()

    return float(r.json()["ripple"]["usd"])



def _from_paprika() -> float:

    r = requests.get("https://api.coinpaprika.com/v1/tickers/xrp-xrp", timeout=7)

    r.raise_for_status()

    return float(r.json()["quotes"]["USD"]["price"])



def _fetch_once() -> Optional[float]:

    p = _try(_from_coingecko)

    if p is None:

        p = _try(_from_paprika)

    return p



def _price_loop(interval_sec: int = 120) -> None:

    # initial

    p = _fetch_once()

    if p is not None:

        with _PRICE_LOCK:

            PRICE_CACHE["xrp_usd"] = p

            PRICE_CACHE["updated"] = time.time()

    # periodic

    while True:

        time.sleep(interval_sec)

        p = _fetch_once()

        if p is not None:

            with _PRICE_LOCK:

                PRICE_CACHE["xrp_usd"] = p

                PRICE_CACHE["updated"] = time.time()



def start_price_updater() -> None:

    t = threading.Thread(target=_price_loop, kwargs={"interval_sec": 120}, daemon=True)

    t.start()



start_price_updater()



def _get_latest_xrp_usd() -> Tuple[Optional[float], str]:

    with _PRICE_LOCK:

        p = PRICE_CACHE["xrp_usd"]

    if p is not None:

        return p, "cache"

    p = _fetch_once()

    if p is not None:

        with _PRICE_LOCK:

            PRICE_CACHE["xrp_usd"] = p

            PRICE_CACHE["updated"] = time.time()

        return p, "fresh"

    return None, "unavailable"



# ---------------- Auth helper ----------------

def admin_required(fn):

    @functools.wraps(fn)

    def wrap(*args, **kwargs):

        if not session.get("admin_authed"):

            return jsonify({"error": "unauthorized"}), 401

        return fn(*args, **kwargs)

    return wrap



# ---------------- Public API ----------------

@app.route("/api/market")

def api_market():

    axo_usd = float(SETTINGS.get("axo_price_usd") or 0.01)

    xrp_usd, source = _get_latest_xrp_usd()

    xrp_val = float(xrp_usd or 0.0)

    axo_per_xrp = (xrp_val / axo_usd) if (axo_usd > 0 and xrp_val > 0) else 0.0

    return jsonify({

        "axo_usd": axo_usd,

        "xrp_usd": xrp_val,

        "axo_per_xrp": axo_per_xrp,

        "source": source,

        "t": int(time.time()),

    })



# ---------------- Admin API ----------------

@app.route("/api/admin/login", methods=["POST"])

def admin_login():

    pin = (request.json or {}).get("pin", "")

    if not ADMIN_PIN:

        return jsonify({"error": "ADMIN_PIN not configured"}), 500

    if pin == ADMIN_PIN:

        session["admin_authed"] = True

        return jsonify({"ok": True})

    return jsonify({"error": "bad_pin"}), 401



@app.route("/api/admin/logout", methods=["POST"])

def admin_logout():

    session.pop("admin_authed", None)

    return jsonify({"ok": True})



@app.route("/api/admin/config", methods=["GET"])

def admin_config():

    if not session.get("admin_authed"):

        return jsonify({"error": "unauthorized"}), 401

    return jsonify({"data": SETTINGS})



@app.route("/api/admin/config", methods=["POST"])

@admin_required

def admin_config_save():

    body = request.get_json(force=True, silent=True) or {}



    def as_bool(v):  return v if isinstance(v, bool) else str(v).lower() == "true"

    def as_float(v, d=0.0):

        try: return float(v)

        except: return d

    def as_int(v, d=0):

        try: return int(float(v))

        except: return d

    def as_list_csv(v):

        if not v: return []

        if isinstance(v, list): return v

        return [x.strip() for x in str(v).split(",") if x.strip()]



    SETTINGS.update({

        "signup_bonus": as_int(body.get("signup_bonus"), SETTINGS["signup_bonus"]),

        "referral_reward": as_int(body.get("referral_reward"), SETTINGS["referral_reward"]),

        "require_trustline": as_bool(body.get("require_trustline")),

        "axo_price_usd": as_float(body.get("axo_price_usd"), SETTINGS["axo_price_usd"]),

        "buy_enabled": as_bool(body.get("buy_enabled")),

        "quick_signup_enabled": as_bool(body.get("quick_signup_enabled")),

        "fee_xrp": as_float(body.get("fee_xrp"), SETTINGS["fee_xrp"]),

        "vault_addr": body.get("vault_addr", SETTINGS["vault_addr"]).strip(),

        "daily_cap_axo": as_int(body.get("daily_cap_axo"), SETTINGS["daily_cap_axo"]),

        "max_claims_per_wallet": as_int(body.get("max_claims_per_wallet"), SETTINGS["max_claims_per_wallet"]),

        "rate_limit_claims_per_hour": as_int(body.get("rate_limit_claims_per_hour"), SETTINGS["rate_limit_claims_per_hour"]),

        "whitelist_addresses": as_list_csv(body.get("whitelist_addresses")),

        "blacklist_addresses": as_list_csv(body.get("blacklist_addresses")),

        "airdrop_paused": as_bool(body.get("airdrop_paused")),

        "maintenance_mode": as_bool(body.get("maintenance_mode")),

    })

    return jsonify({"ok": True, "data": SETTINGS})



# ---------------- Pages (inline HTML) ----------------

INDEX_HTML = r"""

<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8"/>

<meta name="viewport" content="width=device-width,initial-scale=1"/>

<title>AXO — XRPL Signup & Referral Engine</title>

<style>

:root{--bg:#0f172a;--panel:#111827;--text:#e5e7eb;--muted:#94a3b8;--accent:#2563eb;--panelBorder:#1f2937}

*{box-sizing:border-box} html,body{height:100%}

body{margin:0;background:radial-gradient(1200px 600px at 50% -10%,#33415533,transparent),var(--bg);color:var(--text);font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial}

.light body,.light{background:#ffffff;color:#111827}

.topbar{position:fixed;top:12px;left:12px;right:12px;display:flex;justify-content:space-between;z-index:10}

.iconbtn{border:1px solid #e5e7eb;padding:8px 12px;border-radius:14px;cursor:pointer;background:#ffffff;color:#111827;box-shadow:0 2px 6px #0003}

.iconbtn:hover{transform:translateY(-1px)}

.wrap{max-width:880px;margin:80px auto 40px;padding:0 16px}

h1{margin:10px 0 4px;font-size:64px;line-height:1;text-align:center}

.sub{margin:0 0 16px;text-align:center;color:#94a3b8;font-size:16px;letter-spacing:.12em;font-weight:700}

.card{background:var(--panel);border:1px solid var(--panelBorder);border-radius:14px;padding:18px;box-shadow:0 12px 30px #0007}

.section{border:1px dashed #2b3344;border-radius:12px;margin:12px 0;padding:14px}

.row{display:flex;gap:10px;align-items:center;justify-content:center}

.row input{flex:1;max-width:460px;padding:10px 12px;border-radius:10px;border:1px solid #374151;background:#0b1220;color:#e5e7eb;outline:none}

button{padding:10px 14px;border-radius:10px;border:1px solid #2a3a6a;background:#101936;color:#cbd5e1;cursor:pointer}

.primary{background:linear-gradient(180deg,#3b82f6,#2563eb);border-color:#2b50a8;color:#fff}

.note{color:#94a3b8;font-size:12px;margin-left:8px}

.kv{display:flex;gap:6px;align-items:center;justify-content:center;margin-top:6px;font-size:12px;color:#a5b4fc}

.center{display:flex;justify-content:center}

.light .card{background:#f7f7fb;border-color:#e5e7eb}

.light .row input{background:#ffffff;color:#111827;border-color:#d1d5db}

</style>

</head>

<body class="" id="root">

  <div class="topbar">

    <button class="iconbtn" id="themeBtn" title="Toggle theme">🌗</button>

    <button class="iconbtn" id="adminBtn" title="Admin">🚀</button>

  </div>

  <div class="wrap">

    <h1>AXO</h1>

    <div class="sub"><strong>XRPL Signup & Referral Engine</strong></div>

    <div class="card">

      <div class="section">

        <div class="row"><strong>1. Connect XUMM Wallet</strong></div>

        <div class="row" style="margin-top:8px">

          <input id="addr" placeholder="Enter your XRPL r-address (r...)">

          <button>Verify</button>

        </div>

        <div class="row"><span class="note">We’ll verify your wallet and prepare your bonus.</span></div>

      </div>

      <div class="section">

        <div class="row"><strong>2. Set AXO Trust Line</strong> <span class="note">Required before claiming bonus.</span></div>

        <div class="row" style="margin-top:8px"><button>Open in XUMM</button></div>

      </div>

      <div class="section">

        <div class="row"><strong>3. Claim Signup Bonus</strong></div>

        <div class="row" style="margin-top:8px">

          <input id="ref" placeholder="Referral code (optional — r‑addr)">

          <button class="primary">Claim 1000 AXO</button>

        </div>

        <div class="row"><span class="note">Referral reward: 300 AXO (auto when referral is valid).</span></div>

      </div>

      <div class="section">

        <div class="row"><strong>4. Purchase AXO with XRP (optional)</strong></div>

        <div class="row" style="margin-top:8px"><button>Open Purchase Flow</button></div>

      </div>

      <div class="section">

        <div class="row"><strong>Live Market Data</strong></div>

        <div class="row" style="margin-top:8px">

          <div id="m_axo" class="kv">AXO Price (USD): 0.0000</div>

          <div id="m_xrp" class="kv">XRP Price (USD): 0.0000</div>

          <div id="m_rate" class="kv">1 XRP = 0 AXO</div>

        </div>

        <div class="kv" id="m_src">Source • --:--:--</div>

      </div>

    </div>

  </div>

<script>

(function(){

  // Theme toggle (button is white by design)

  const root = document.getElementById('root');

  const themeBtn = document.getElementById('themeBtn');

  themeBtn.onclick = () => {

    root.classList.toggle('light');

    localStorage.setItem('theme', root.classList.contains('light') ? 'light' : 'dark');

  };

  const saved = localStorage.getItem('theme');

  if(saved === 'light'){ root.classList.add('light'); }



  // Admin

  document.getElementById('adminBtn').onclick = () => { location.href = '/admin'; };



  // Live Market refresher

  async function refreshMarket(){

    try{

      const r = await fetch('/api/market', {cache:'no-store'});

      const j = await r.json();

      const axo = Number(j.axo_usd || 0).toFixed(4);

      const xrp = Number(j.xrp_usd || 0).toFixed(4);

      const rate = Number(j.axo_per_xrp || 0).toFixed(2);

      const ts = new Date((j.t||0)*1000).toLocaleTimeString();

      document.getElementById('m_axo').textContent = `AXO Price (USD): ${axo}`;

      document.getElementById('m_xrp').textContent = `XRP Price (USD): ${xrp}`;

      document.getElementById('m_rate').textContent = `1 XRP = ${rate} AXO`;

      document.getElementById('m_src').textContent  = `source: ${j.source} • ${ts}`;

    }catch(e){}

    setTimeout(refreshMarket, 60000);

  }

  refreshMarket();

})();

</script>

</body>

</html>

"""



# Minimal admin screen kept as-is; your existing frontend JS calls these endpoints.

ADMIN_HTML = r"""

<!doctype html>

<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>

<title>AXO Admin</title>

<style>

:root{--bg:#0f172a;--panel:#111827;--text:#e5e7eb;--muted:#9ca3af;--accent:#2563eb}

body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial}

.wrap{max-width:1000px;margin:40px auto;padding:16px}

.card{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:18px}

.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}

label{font-size:12px;color:#9ca3af;margin-bottom:6px;display:block}

input,select,textarea{width:100%;padding:10px;border-radius:10px;border:1px solid #374151;background:#0b1220;color:#e5e7eb}

.actions{display:flex;gap:10px;justify-content:flex-end;margin-top:16px}

button{padding:10px 14px;border-radius:10px;border:1px solid #2a3a6a;background:#101936;color:#cbd5e1;cursor:pointer}

button.primary{background:linear-gradient(180deg,#3b82f6,#2563eb);border-color:#2b50a8;color:#fff}

.hint{color:#94a3b8;font-size:12px;margin-top:6px}

.ok{color:#10b981}.err{color:#f87171}

</style></head>

<body>

<div class="wrap">

  <div id="pinCard" class="card" style="display:none">

    <h2>Enter Admin PIN</h2>

    <label>PIN</label>

    <input id="pin" type="password" placeholder="••••••"/>

    <div class="actions">

      <button onclick="login()">Unlock</button>

      <button onclick="location.href='/'">Back</button>

    </div>

    <div id="pinMsg" class="hint"></div>

  </div>



  <div id="adminCard" class="card" style="display:none">

    <h2>AXO Admin</h2>

    <div class="grid">

      <div><label>Signup Bonus (AXO)</label><input id="signup_bonus" type="number"></div>

      <div><label>Referral Reward (AXO)</label><input id="referral_reward" type="number"></div>

      <div><label>Require TrustLine</label><select id="require_trustline"><option>true</option><option>false</option></select></div>



      <div><label>AXO Price (USD)</label><input id="axo_price_usd" type="number" step="0.0001"></div>

      <div><label>Buy Flow Enabled</label><select id="buy_enabled"><option>true</option><option>false</option></select></div>

      <div><label>Quick Signup Enabled</label><select id="quick_signup_enabled"><option>false</option><option>true</option></select></div>



      <div><label>Flat Fee (XRP)</label><input id="fee_xrp" type="number" step="0.000001"></div>

      <div><label>Vault Address</label><input id="vault_addr" placeholder="r..."></div>

      <div></div>



      <div><label>Daily Cap (AXO)</label><input id="daily_cap_axo" type="number"></div>

      <div><label>Max Claims / Wallet</label><input id="max_claims_per_wallet" type="number"></div>

      <div><label>Claims / Hour</label><input id="rate_limit_claims_per_hour" type="number"></div>



      <div><label>Whitelist (comma r-...)</label><textarea id="whitelist_addresses"></textarea></div>

      <div><label>Blacklist (comma r-...)</label><textarea id="blacklist_addresses"></textarea></div>

      <div>

        <label>Airdrop Paused</label><select id="airdrop_paused"><option>false</option><option>true</option></select>

        <label style="margin-top:10px;display:block">Maintenance</label><select id="maintenance_mode"><option>false</option><option>true</option></select>

      </div>

    </div>

    <div class="actions">

      <button onclick="logoutAndHome()">Close</button>

      <button class="primary" onclick="saveAndExit()">Save</button>

    </div>

    <div id="msg" class="hint"></div>

  </div>

</div>

<script>

async function isAuthed(){ const r = await fetch('/api/admin/config'); return r.status===200; }

async function show(){ if(await isAuthed()){ await load(); adminCard.style.display=''; } else { pinCard.style.display=''; } }

async function login(){

  const pin = document.getElementById('pin').value.trim();

  const r = await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin})});

  const m = document.getElementById('pinMsg');

  if(r.ok){ m.textContent='Unlocked.'; m.className='hint ok'; location.reload(); }

  else     { m.textContent='Invalid PIN.'; m.className='hint err'; }

}

async function logout(){ await fetch('/api/admin/logout',{method:'POST'}); }

async function logoutAndHome(){ await logout(); location.href='/'; }

async function saveAndExit(){ const ok = await save(true); await logout(); location.href='/'; }



async function load(){

  const r = await fetch('/api/admin/config'); if(!r.ok) return;

  const s = (await r.json()).data || {};

  for (const k of ['signup_bonus','referral_reward','require_trustline','axo_price_usd','buy_enabled','quick_signup_enabled','fee_xrp','vault_addr','daily_cap_axo','max_claims_per_wallet','rate_limit_claims_per_hour','whitelist_addresses','blacklist_addresses','airdrop_paused','maintenance_mode']){

    const el = document.getElementById(k); if(!el) continue;

    if (el.tagName==='SELECT') el.value = String(s[k]);

    else if (el.tagName==='TEXTAREA') el.value = (s[k]||[]).join(', ');

    else el.value = s[k] ?? '';

  }

}

async function save(silent=false){

  const v = id => document.getElementById(id).value;

  const body = {

    signup_bonus:Number(v('signup_bonus')||0),

    referral_reward:Number(v('referral_reward')||0),

    require_trustline:(v('require_trustline')==='true'),

    axo_price_usd:Number(v('axo_price_usd')||0.01),

    buy_enabled:(v('buy_enabled')==='true'),

    quick_signup_enabled:(v('quick_signup_enabled')==='true'),

    fee_xrp:Number(v('fee_xrp')||0),

    vault_addr:v('vault_addr').trim(),

    daily_cap_axo:Number(v('daily_cap_axo')||0),

    max_claims_per_wallet:Number(v('max_claims_per_wallet')||1),

    rate_limit_claims_per_hour:Number(v('rate_limit_claims_per_hour')||1),

    whitelist_addresses:v('whitelist_addresses'),

    blacklist_addresses:v('blacklist_addresses'),

    airdrop_paused:(v('airdrop_paused')==='true'),

    maintenance_mode:(v('maintenance_mode')==='true'),

  };

  const r = await fetch('/api/admin/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

  if (silent) return r.ok;

  const el = document.getElementById('msg');

  el.textContent = r.ok ? 'Saved.' : 'Save failed';

  el.className = 'hint ' + (r.ok?'ok':'err');

  return r.ok;

}

const pinCard=document.getElementById('pinCard'); const adminCard=document.getElementById('adminCard'); show();

</script>

</body></html>

"""



# ---------------- Routes to render pages ----------------

@app.route("/")

def home():

    return render_template_string(INDEX_HTML)



@app.route("/admin")

def admin_page():

    return render_template_string(ADMIN_HTML)



# ---------------- Entrypoint ----------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", "8080"))

    # Use ASCII-only logs to avoid cp1252 console issues on Windows

    os.environ["PYTHONIOENCODING"] = "utf-8"

    app.run(host="0.0.0.0", port=port)