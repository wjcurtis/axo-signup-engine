import os

import json

import time

import pathlib

from typing import Any, Dict, Optional



import requests

from flask import (

    Flask, request, jsonify, send_from_directory,

    redirect, url_for, session, make_response

)



# ------------------ App & Config ------------------



app = Flask(__name__)



# Secret key for Flask sessions (needed for admin login).

# Prefer SECRET_KEY from env; otherwise derive a stable fallback from WALLET_SEED (masked) or a constant.

app.secret_key = os.environ.get("SECRET_KEY") or (

    ("sk_" + (os.environ.get("WALLET_SEED", "_")[:12])).encode("utf-8")

)



ADMIN_PIN = os.environ.get("ADMIN_PIN", "").strip()

WALLET_SEED = os.environ.get("WALLET_SEED", "").strip()

AXO_USD_FALLBACK = float(os.environ.get("AXO_USD_FALLBACK", "0.01"))



# Where the built frontend lives

ROOT = pathlib.Path(os.getcwd())

STATIC_ROOT = ROOT / "dist" / "public"

INDEX_FILE = STATIC_ROOT / "index.html"



print("STATIC_ROOT =", STATIC_ROOT)

print("INDEX_FILE exists? ->", INDEX_FILE.exists())



if not INDEX_FILE.exists():

    raise RuntimeError(f"index.html not found at {INDEX_FILE}")



# Small on-disk store for admin-configurable settings

DATA_DIR = ROOT / "data"

DATA_DIR.mkdir(exist_ok=True)

CONFIG_PATH = DATA_DIR / "config.json"

SIGNUPS_PATH = DATA_DIR / "signups.json"   # stub store for demo



DEFAULT_CONFIG: Dict[str, Any] = {

    "signup_bonus_axo": 1000,

    "referral_bonus_axo": 300,

    "banner": "",

    "maintenance": False,

    "last_updated": int(time.time())

}



def load_json(path: pathlib.Path, default: Any) -> Any:

    try:

        if path.exists():

            with path.open("r", encoding="utf-8") as f:

                return json.load(f)

    except Exception:

        pass

    return default



def save_json(path: pathlib.Path, data: Any) -> None:

    tmp = path.with_suffix(".json.tmp")

    with tmp.open("w", encoding="utf-8") as f:

        json.dump(data, f, ensure_ascii=False, indent=2)

    tmp.replace(path)



def get_config() -> Dict[str, Any]:

    cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG.copy())

    # ensure all keys

    changed = False

    for k, v in DEFAULT_CONFIG.items():

        if k not in cfg:

            cfg[k] = v

            changed = True

    if changed:

        cfg["last_updated"] = int(time.time())

        save_json(CONFIG_PATH, cfg)

    return cfg



def update_config(partial: Dict[str, Any]) -> Dict[str, Any]:

    cfg = get_config()

    cfg.update({k: v for k, v in partial.items() if k in DEFAULT_CONFIG})

    cfg["last_updated"] = int(time.time())

    save_json(CONFIG_PATH, cfg)

    return cfg



# --------------- Static / SPA routes ---------------



@app.route("/")

def serve_index():

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/assets/<path:filename>")

def serve_assets(filename: str):

    return send_from_directory(STATIC_ROOT / "assets", filename)



# Serve any non-API route as SPA (client routing)

@app.errorhandler(404)

def spa_on_404(_):

    # If path looks like an API, return real 404

    path = request.path.lstrip("/")

    if path.startswith("api/"):

        return jsonify({"error": "Not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:anypath>")

def spa_catch_all(anypath: str):

    if anypath.startswith("api/"):

        return jsonify({"error": "Not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



# ----------------- Public API: Market -----------------



def fetch_xrp_usd(timeout=6.0) -> Optional[float]:

    """

    Get XRP price in USD from CoinGecko.

    """

    try:

        r = requests.get(

            "https://api.coingecko.com/api/v3/simple/price",

            params={"ids": "ripple", "vs_currencies": "usd"},

            timeout=timeout,

            headers={"Accept": "application/json"}

        )

        if r.ok:

            data = r.json()

            return float(data.get("ripple", {}).get("usd") or 0.0)

    except Exception:

        pass

    return None



def fetch_axo_usd(timeout=6.0) -> Optional[float]:

    """

    AXO price: if you have a live source, put it here.

    For now we use AXO_USD_FALLBACK env (default 0.01).

    This keeps the UI live and the exchange rate correct.

    """

    return float(AXO_USD_FALLBACK or 0.01)



@app.route("/api/market")

def api_market():

    """

    Returns { axo_usd, xrp_usd, axo_per_xrp, source, t, cached_seconds }

    """

    t = int(time.time())

    axo_usd = fetch_axo_usd()

    xrp_usd = fetch_xrp_usd() or 0.0

    axo_per_xrp = (xrp_usd / axo_usd) if (axo_usd and xrp_usd) else 0.0



    return jsonify({

        "axo_usd": round(axo_usd, 6),

        "xrp_usd": round(xrp_usd, 6),

        "axo_per_xrp": round(axo_per_xrp, 6),

        "source": "coingecko+x_fallback",

        "cached_seconds": 0,

        "t": t

    })



# --------------- Admin Auth Helpers -------------------



def is_admin() -> bool:

    return bool(session.get("admin_ok") is True)



def require_admin():

    if not is_admin():

        return jsonify({"error": "admin_auth_required"}), 401



# --------------- Admin Web (PIN Lock) -----------------



ADMIN_PAGE_HTML = """

<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8" />

<meta name="viewport" content="width=device-width, initial-scale=1" />

<title>AXO Admin</title>

<style>

  :root { --bg:#0b0f14; --card:#141a22; --txt:#e9eef5; --mut:#93a1b2; --accent:#2d7df6; --bad:#e34f4f; --good:#19c37d; }

  html,body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, 'Helvetica Neue', Arial, 'Noto Sans', 'Apple Color Emoji','Segoe UI Emoji', 'Segoe UI Symbol';}

  a{color:var(--accent);text-decoration:none}

  .wrap{max-width:960px;margin:40px auto;padding:0 16px;}

  .card{background:var(--card);border-radius:12px;padding:20px;margin:16px 0;box-shadow:0 4px 14px rgba(0,0,0,.25)}

  h1{font-size:28px;margin:12px 0 4px}

  h2{font-size:20px;margin:6px 0 12px;color:var(--mut)}

  label{display:block;font-size:14px;color:var(--mut);margin:8px 0 4px}

  input,button,textarea,select{font-size:15px;padding:10px 12px;border-radius:10px;border:1px solid #2a3340;background:#0f141a;color:var(--txt);outline:none}

  button{background:var(--accent);border:none;color:#fff;cursor:pointer}

  button.secondary{background:#273142}

  .row{display:flex;gap:12px;flex-wrap:wrap}

  .row > *{flex:1 1 220px}

  .mut{color:var(--mut)}

  .ok{color:var(--good)} .bad{color:var(--bad)}

  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}

  .footer{margin-top:10px;font-size:12px;color:var(--mut)}

  .lock{max-width:460px;margin:80px auto;text-align:center}

</style>

</head>

<body>

<div class="wrap" id="app">

  <!-- Filled by JS -->

</div>



<script>

async function postJSON(url, body) {

  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});

  if (!r.ok) { throw new Error('HTTP '+r.status); }

  return await r.json().catch(()=> ({}));

}

async function getJSON(url) {

  const r = await fetch(url, {headers:{'Accept':'application/json'}});

  if (!r.ok) { throw new Error('HTTP '+r.status); }

  return await r.json();

}



async function render() {

  const root = document.getElementById('app');

  // Check login state

  const me = await getJSON('/api/admin/me').catch(()=>({admin:false}));

  if (!me.admin) {

    root.innerHTML = `

      <div class="lock card">

        <h1>Admin Login</h1>

        <p class="mut">Enter your PIN to access the AXO admin.</p>

        <div class="row">

          <input id="pin" type="password" placeholder="Admin PIN" />

          <button id="btnLogin">Unlock</button>

        </div>

      </div>`;

    document.getElementById('btnLogin').onclick = async () => {

      const pin = document.getElementById('pin').value.trim();

      try {

        const res = await postJSON('/api/admin/login', {pin});

        if (res.ok) location.reload();

      } catch(e) { alert('Login failed.'); }

    };

    return;

  }



  // Load config

  const cfg = await getJSON('/api/admin/config');



  root.innerHTML = `

    <div class="card">

      <h1>AXO Admin</h1>

      <div class="mut">Welcome. Use the controls below. <button class="secondary" id="btnLogout">Log out</button></div>

    </div>



    <div class="card">

      <h2>Bonuses</h2>

      <div class="row">

        <div><label>Signup Bonus (AXO)</label><input id="signup_bonus" type="number" value="${cfg.signup_bonus_axo}" /></div>

        <div><label>Referral Bonus (AXO)</label><input id="ref_bonus" type="number" value="${cfg.referral_bonus_axo}" /></div>

      </div>

      <div style="margin-top:10px"><button id="saveBonuses">Save Bonuses</button></div>

    </div>



    <div class="card">

      <h2>Banner / Maintenance</h2>

      <label>Banner message (optional)</label>

      <textarea id="banner" rows="2" placeholder="Short banner shown on the site...">${cfg.banner||''}</textarea>

      <div class="row" style="margin-top:8px">

        <div><label><input id="maint" type="checkbox" ${cfg.maintenance ? 'checked':''}/> Maintenance mode</label></div>

        <div><button id="saveSite">Save Site Settings</button></div>

      </div>

      <div class="footer">Last updated: ${new Date((cfg.last_updated||0)*1000).toLocaleString()}</div>

    </div>



    <div class="card">

      <h2>Utilities</h2>

      <div class="grid">

        <button id="btnCache">Rebuild market cache</button>

        <button id="btnExport">Export signups (CSV)</button>

        <button id="btnAward">Manual award (stub)</button>

      </div>

    </div>

  `;



  document.getElementById('btnLogout').onclick = async () => {

    await postJSON('/api/admin/logout', {});

    location.href = '/';

  };



  document.getElementById('saveBonuses').onclick = async () => {

    const signup = +document.getElementById('signup_bonus').value || 0;

    const ref = +document.getElementById('ref_bonus').value || 0;

    await postJSON('/api/admin/config', {signup_bonus_axo: signup, referral_bonus_axo: ref});

    alert('Saved.');

  };

  document.getElementById('saveSite').onclick = async () => {

    const banner = document.getElementById('banner').value;

    const maint = document.getElementById('maint').checked;

    await postJSON('/api/admin/config', {banner, maintenance: maint});

    alert('Saved.');

  };



  document.getElementById('btnCache').onclick = async () => {

    await getJSON('/api/admin/rebuild-cache').catch(()=>{});

    alert('Cache refresh requested.');

  };



  document.getElementById('btnExport').onclick = async () => {

    window.location.href = '/api/admin/export-signups';

  };



  document.getElementById('btnAward').onclick = async () => {

    const addr = prompt('Enter XRPL Address to award (stub demo):');

    const amt  = prompt('AXO amount:','100');

    if (addr && amt) {

      const res = await postJSON('/api/admin/award', {address: addr, axo: +amt});

      alert(res.ok ? 'Recorded (stub).' : 'Failed.');

    }

  };

}



render();

</script>

</body>

</html>

"""



def admin_required_json(fn):

    """

    Decorator for simple admin JSON routes.

    """

    from functools import wraps

    @wraps(fn)

    def _wrap(*args, **kwargs):

        if not is_admin():

            return jsonify({"error":"admin_auth_required"}), 401

        return fn(*args, **kwargs)

    return _wrap



@app.route("/admin", methods=["GET"])

def admin_page():

    """

    Serves the admin login screen or the dashboard after PIN.

    """

    # The page itself decides (via /api/admin/me) whether you're logged in.

    resp = make_response(ADMIN_PAGE_HTML)

    resp.headers["Content-Type"] = "text/html; charset=utf-8"

    return resp



# ---- Admin JSON endpoints ----



@app.route("/api/admin/me")

def admin_me():

    return jsonify({"admin": is_admin()})



@app.route("/api/admin/login", methods=["POST"])

def admin_login():

    data = request.get_json(force=True, silent=True) or {}

    pin = (data.get("pin") or "").strip()

    if not ADMIN_PIN:

        return jsonify({"error":"admin_pin_not_set_in_env"}), 500

    if pin == ADMIN_PIN:

        session["admin_ok"] = True

        return jsonify({"ok": True})

    return jsonify({"ok": False}), 401



@app.route("/api/admin/logout", methods=["POST"])

def admin_logout():

    session.pop("admin_ok", None)

    return jsonify({"ok": True})



@app.route("/api/admin/config", methods=["GET"])

@admin_required_json

def admin_get_config():

    return jsonify(get_config())



@app.route("/api/admin/config", methods=["POST"])

@admin_required_json

def admin_set_config():

    data = request.get_json(force=True, silent=True) or {}

    allowed = {k: v for k, v in data.items() if k in DEFAULT_CONFIG}

    cfg = update_config(allowed)

    return jsonify(cfg)



@app.route("/api/admin/rebuild-cache")

@admin_required_json

def admin_rebuild_cache():

    # This endpoint doesn't keep a cache yet, but it's here for parity.

    # You could expand to prefetch market data or clear any in-memory caches.

    return jsonify({"ok": True, "ts": int(time.time())})



@app.route("/api/admin/export-signups")

@admin_required_json

def admin_export_signups():

    rows = load_json(SIGNUPS_PATH, [])

    # Build CSV inline

    import io, csv

    buf = io.StringIO()

    w = csv.writer(buf)

    w.writerow(["ts","email","address","referral"])

    for r in rows:

        w.writerow([r.get("ts",""), r.get("email",""), r.get("address",""), r.get("referral","")])

    out = make_response(buf.getvalue())

    out.headers["Content-Type"] = "text/csv; charset=utf-8"

    out.headers["Content-Disposition"] = "attachment; filename=signups.csv"

    return out



@app.route("/api/admin/award", methods=["POST"])

@admin_required_json

def admin_award_stub():

    """

    Stub for manual awards. Records intent only.

    In a future pass, wire to your XRPL sender using WALLET_SEED.

    """

    data = request.get_json(force=True, silent=True) or {}

    address = (data.get("address") or "").strip()

    axo = float(data.get("axo") or 0)

    if not address or axo <= 0:

        return jsonify({"ok": False, "error": "invalid_params"}), 400

    log = load_json(DATA_DIR / "awards.json", [])

    log.append({"ts": int(time.time()), "address": address, "axo": axo, "by": "admin"})

    save_json(DATA_DIR / "awards.json", log)

    return jsonify({"ok": True})



# --------- (Optional) Public signup endpoint (stub) ---------

# If your index.html later POSTs to record signups, this will keep a local ledger.

@app.route("/api/signup", methods=["POST"])

def api_signup():

    data = request.get_json(force=True, silent=True) or {}

    email = (data.get("email") or "").strip()

    address = (data.get("address") or "").strip()

    referral = (data.get("referral") or "").strip()

    rows = load_json(SIGNUPS_PATH, [])

    rows.append({"ts": int(time.time()), "email": email, "address": address, "referral": referral})

    save_json(SIGNUPS_PATH, rows)

    return jsonify({"ok": True})
