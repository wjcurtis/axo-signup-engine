# main.py — AXO Referral Engine (static homepage + APIs + Admin page)

# ------------------------------------------------------------------

# - Serves UI from:   dist/public/index.html

# - Static assets:    /assets/<file>   -> dist/public/assets/<file>

# - Public APIs:      /api/market, /api/subscribe

# - Admin APIs:       /api/admin/*  (+ Admin UI at /admin)

# ------------------------------------------------------------------



import os, time, json, functools, threading

from typing import Any, Dict, Tuple, Optional

from pathlib import Path



import requests

from dotenv import load_dotenv

from flask import (

    Flask, request, jsonify, session,

    send_from_directory, render_template_string

)



# ------------------ Env ------------------

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")  # loads ADMIN_PIN, WALLET_SEED, etc.



app = Flask(__name__)

app.secret_key   = os.environ.get("FLASK_SECRET_KEY", "change-me-please")

ADMIN_PIN        = os.environ.get("ADMIN_PIN", "")

AXO_PRICE_USD    = float(os.environ.get("AXO_PRICE", "0.01"))

XRP_VAULT_ADDR   = os.environ.get("XRP_VAULT_ADDR", "")

WALLET_SEED      = os.environ.get("WALLET_SEED", "")



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



threading.Thread(target=_price_loop, kwargs={"interval_sec": 120}, daemon=True).start()



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

@app.get("/api/market")

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



@app.post("/api/subscribe")

def subscribe_email():

    try:

        email = (request.get_json(silent=True) or {}).get("email", "").strip()

        if not email:

            return jsonify({"ok": False, "error": "no_email"}), 400

        with open(BASE_DIR / "emails.csv", "a", encoding="utf-8") as f:

            f.write(f"{int(time.time())},{email}\n")

        return jsonify({"ok": True})

    except Exception as e:

        return jsonify({"ok": False, "error": str(e)}), 500



# ---------------- Admin API ----------------

@app.post("/api/admin/login")

def admin_login():

    pin = (request.json or {}).get("pin", "")

    if not ADMIN_PIN:

        return jsonify({"error": "ADMIN_PIN not configured"}), 500

    if pin == ADMIN_PIN:

        session["admin_authed"] = True

        return jsonify({"ok": True})

    return jsonify({"error": "bad_pin"}), 401



@app.post("/api/admin/logout")

def admin_logout():

    session.pop("admin_authed", None)

    return jsonify({"ok": True})



@app.get("/api/admin/config")

def admin_config():

    if not session.get("admin_authed"):

        return jsonify({"error": "unauthorized"}), 401

    return jsonify({"data": SETTINGS})



@app.post("/api/admin/config")

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



# ---------- Admin page (styled UI) ----------

ADMIN_HTML = r"""

<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8"/>

<meta name="viewport" content="width=device-width,initial-scale=1"/>

<title>AXO • Admin</title>

<style>

:root{--bg:#0f172a;--panel:#111827;--text:#e5e7eb;--muted:#94a3b8;--accent:#2563eb;--panelBorder:#1f2937}

*{box-sizing:border-box} html,body{height:100%}

body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial}

.wrap{max-width:940px;margin:40px auto;padding:0 16px}

h1{margin:0 0 16px;font-size:28px}

.card{background:var(--panel);border:1px solid var(--panelBorder);border-radius:12px;padding:16px}

.row{display:flex;gap:10px;align-items:center;margin:8px 0}

button{padding:8px 12px;border-radius:8px;border:1px solid #2a3a6a;background:#101936;color:#cbd5e1;cursor:pointer}

button.primary{background:linear-gradient(180deg,#3b82f6,#2563eb);color:#fff;border-color:#2b50a8}

input,textarea{width:100%;padding:10px;border-radius:8px;border:1px solid #374151;background:#0b1220;color:#e5e7eb;outline:none}

.kv{display:grid;grid-template-columns:260px 1fr;gap:8px;align-items:center;margin:10px 0}

.note{color:#94a3b8;font-size:12px}

.badge{display:inline-block;background:#0b1220;border:1px solid #334155;color:#a5b4fc;border-radius:999px;padding:4px 10px;font-size:12px}

hr{border:0;border-top:1px solid #1f2937;margin:14px 0}

</style>

</head>

<body>

  <div class="wrap">

    <h1>AXO • Admin</h1>



    <div class="card" id="loginCard" style="display:none">

      <div class="row"><span class="badge">Login required</span></div>

      <div class="kv">

        <label for="pin">Admin PIN</label>

        <input id="pin" type="password" placeholder="Enter ADMIN_PIN"/>

      </div>

      <div class="row">

        <button class="primary" id="loginBtn">Login</button>

      </div>

      <div class="note" id="loginMsg"></div>

    </div>



    <div class="card" id="panelCard" style="display:none">

      <div class="row" style="justify-content:space-between">

        <div class="badge">Config panel</div>

        <div>

          <button id="refreshBtn">Refresh config</button>

          <button id="logoutBtn">Logout</button>

          <button class="primary" id="saveBtn">Save changes</button>

        </div>

      </div>

      <hr/>

      <div class="kv"><label>Signup bonus (AXO)</label><input id="signup_bonus" type="number" step="1"/></div>

      <div class="kv"><label>Referral reward (AXO)</label><input id="referral_reward" type="number" step="1"/></div>

      <div class="kv"><label>Require trustline?</label><input id="require_trustline" type="checkbox"/></div>

      <div class="kv"><label>AXO price (USD)</label><input id="axo_price_usd" type="number" step="0.0001"/></div>

      <div class="kv"><label>Enable Buy flow?</label><input id="buy_enabled" type="checkbox"/></div>

      <div class="kv"><label>Quick signup?</label><input id="quick_signup_enabled" type="checkbox"/></div>

      <div class="kv"><label>Fee (XRP)</label><input id="fee_xrp" type="number" step="0.01"/></div>

      <div class="kv"><label>Vault address</label><input id="vault_addr" type="text"/></div>

      <div class="kv"><label>Daily cap (AXO)</label><input id="daily_cap_axo" type="number" step="1"/></div>

      <div class="kv"><label>Max claims / wallet</label><input id="max_claims_per_wallet" type="number" step="1"/></div>

      <div class="kv"><label>Claims / hour limit</label><input id="rate_limit_claims_per_hour" type="number" step="1"/></div>

      <div class="kv"><label>Whitelist (CSV)</label><textarea id="whitelist_addresses" rows="2" placeholder="rXXXX, rYYYY"></textarea></div>

      <div class="kv"><label>Blacklist (CSV)</label><textarea id="blacklist_addresses" rows="2" placeholder="rAAAA, rBBBB"></textarea></div>

      <div class="kv"><label>Airdrop paused?</label><input id="airdrop_paused" type="checkbox"/></div>

      <div class="kv"><label>Maintenance mode?</label><input id="maintenance_mode" type="checkbox"/></div>

      <hr/>

      <div class="note" id="msg"></div>

    </div>

  </div>



<script>

async function api(path, opts={}){

  const r = await fetch(path, {credentials:'same-origin', headers:{'Content-Type':'application/json'}, ...opts});

  const ct = r.headers.get('content-type')||'';

  const body = ct.includes('application/json') ? await r.json() : null;

  return {ok:r.ok, status:r.status, body};

}

function setVal(id, v){ const el = document.getElementById(id); if(el.type==='checkbox'){ el.checked = !!v; } else { el.value = (v ?? ''); } }

function getVal(id){ const el = document.getElementById(id); return (el.type==='checkbox') ? el.checked : el.value; }



async function loadConfig(){

  const res = await api('/api/admin/config');

  if(!res.ok){

    document.getElementById('panelCard').style.display='none';

    document.getElementById('loginCard').style.display='block';

    return;

  }

  const d = res.body.data || {};

  setVal('signup_bonus', d.signup_bonus);

  setVal('referral_reward', d.referral_reward);

  setVal('require_trustline', d.require_trustline);

  setVal('axo_price_usd', d.axo_price_usd);

  setVal('buy_enabled', d.buy_enabled);

  setVal('quick_signup_enabled', d.quick_signup_enabled);

  setVal('fee_xrp', d.fee_xrp);

  setVal('vault_addr', d.vault_addr);

  setVal('daily_cap_axo', d.daily_cap_axo);

  setVal('max_claims_per_wallet', d.max_claims_per_wallet);

  setVal('rate_limit_claims_per_hour', d.rate_limit_claims_per_hour);

  setVal('whitelist_addresses', (d.whitelist_addresses||[]).join(', '));

  setVal('blacklist_addresses', (d.blacklist_addresses||[]).join(', '));

  setVal('airdrop_paused', d.airdrop_paused);

  setVal('maintenance_mode', d.maintenance_mode);

  document.getElementById('loginCard').style.display='none';

  document.getElementById('panelCard').style.display='block';

}



async function saveConfig(){

  const body = {

    signup_bonus: Number(getVal('signup_bonus')),

    referral_reward: Number(getVal('referral_reward')),

    require_trustline: getVal('require_trustline'),

    axo_price_usd: Number(getVal('axo_price_usd')),

    buy_enabled: getVal('buy_enabled'),

    quick_signup_enabled: getVal('quick_signup_enabled'),

    fee_xrp: Number(getVal('fee_xrp')),

    vault_addr: getVal('vault_addr').trim(),

    daily_cap_axo: Number(getVal('daily_cap_axo')),

    max_claims_per_wallet: Number(getVal('max_claims_per_wallet')),

    rate_limit_claims_per_hour: Number(getVal('rate_limit_claims_per_hour')),

    whitelist_addresses: getVal('whitelist_addresses').split(',').map(s=>s.trim()).filter(Boolean),

    blacklist_addresses: getVal('blacklist_addresses').split(',').map(s=>s.trim()).filter(Boolean),

    airdrop_paused: getVal('airdrop_paused'),

    maintenance_mode: getVal('maintenance_mode')

  };

  const r = await api('/api/admin/config', {method:'POST', body: JSON.stringify(body)});

  document.getElementById('msg').textContent = r.ok ? 'Saved!' : ('Save failed: ' + (r.body && (r.body.error || JSON.stringify(r.body))));

  if(r.ok) loadConfig();

}



async function login(){

  const pin = document.getElementById('pin').value.trim();

  if(!pin){ document.getElementById('loginMsg').textContent='Enter PIN'; return; }

  const r = await api('/api/admin/login', {method:'POST', body: JSON.stringify({pin})});

  document.getElementById('loginMsg').textContent = r.ok ? 'OK' : 'Bad PIN';

  if(r.ok) loadConfig();

}



async function logout(){

  await api('/api/admin/logout', {method:'POST'});

  document.getElementById('panelCard').style.display='none';

  document.getElementById('loginCard').style.display='block';

}



document.getElementById('refreshBtn')?.addEventListener('click', loadConfig);

document.getElementById('saveBtn')?.addEventListener('click', saveConfig);

document.getElementById('loginBtn')?.addEventListener('click', login);

document.getElementById('logoutBtn')?.addEventListener('click', logout);



loadConfig();

</script>

</body>

</html>

"""



# ---------------- Serve homepage from dist/public ----------------

APP_DIR   = Path(__file__).resolve().parent

PUBLIC_DIR = APP_DIR / "dist" / "public"



@app.route("/")

def home():

    # Serve the compiled UI (index.html) from dist/public

    return send_from_directory(PUBLIC_DIR, "index.html")



@app.route("/assets/<path:fname>")

def assets(fname: str):

    return send_from_directory(PUBLIC_DIR / "assets", fname)



# Optional: quiet the favicon 404 spam; serve if present, else 204

@app.route("/favicon.ico")

def favicon():

    icon = PUBLIC_DIR / "favicon.ico"

    if icon.exists():

        return send_from_directory(PUBLIC_DIR, "favicon.ico")

    return ("", 204)



# Health probe (useful for Render)

@app.get("/healthz")

def healthz():

    return jsonify({"ok": True})



# ---------------- Admin page route ----------------

@app.route("/admin")

def admin_page():

    return render_template_string(ADMIN_HTML)



# ---------------- Entry point ----------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", "5000"))

    app.run(host="0.0.0.0", port=port, debug=False)