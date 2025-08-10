# main.py — AXO Utility Hub (Flask + SPA + Embedded Admin UI)

# Fixes: ADMIN_PIN recognition + cookie/session policy so admin login works reliably.



import os, time, threading

from typing import Any, Dict, Set

import requests

from flask import (

    Flask, jsonify, request, send_from_directory, session, make_response,

    render_template_string

)



# ------------------ App & Session ------------------

app = Flask(__name__)



# You already set this in Render → Environment

app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))



# Ensure the session cookie behaves well on Render:

app.config.update(

    SESSION_COOKIE_SAMESITE="Lax",   # cookie sent on same-site fetches

    SESSION_COOKIE_SECURE=True,      # HTTPS only (Render uses HTTPS)

    SESSION_COOKIE_NAME="axo_admin_sess"

)



# ------------------ Admin PIN (env) ------------------

# Accept either ADMIN_PIN or ADMIN_PASSWORD; trim whitespace just in case.

ADMIN_PIN = (os.environ.get("ADMIN_PIN") or os.environ.get("ADMIN_PASSWORD") or "0000").strip()



# ------------------ Static SPA ------------------

STATIC_ROOT = os.path.join(os.getcwd(), "dist", "public")

INDEX_FILE = os.path.join(STATIC_ROOT, "index.html")

if not os.path.exists(INDEX_FILE):

    raise RuntimeError("index.html not found at " + INDEX_FILE)



@app.route("/")

def root():

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/assets/<path:filename>")

def assets(filename: str):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)



# ------------------ State (in-memory; resets on deploy) ------------------

STATE_LOCK = threading.Lock()

SETTINGS: Dict[str, Any] = {

    "signup_bonus": 1000,

    "referral_reward": 300,

    "axo_price_usd": float(os.environ.get("AXO_PRICE_USD", os.environ.get("AXO_PRICE", "0.01")) or 0.01),

    "fee_xrp": 0.25,

    "vault_addr": (os.environ.get("XRPL_VAULT_ADDR") or os.environ.get("XRP_VAULT_ADDR") or "").strip()

}

BLOCKED: Set[str] = set()

CLAIMED: Set[str] = set()  # one-time signup bonus enforcement



def admin_authed() -> bool:

    return bool(session.get("is_admin"))



# ------------------ Market API ------------------

def fetch_xrp_usd(timeout: float = 6.0) -> float:

    try:

        r = requests.get(

            "https://api.coingecko.com/api/v3/simple/price",

            params={"ids": "ripple", "vs_currencies": "usd"},

            timeout=timeout

        )

        if r.ok:

            return float(r.json().get("ripple", {}).get("usd", 0) or 0.0)

    except Exception:

        pass

    return 0.0



@app.get("/api/market")

def api_market():

    with STATE_LOCK:

        axo = float(SETTINGS["axo_price_usd"])

    xrp = fetch_xrp_usd()

    axo_per_xrp = (xrp/axo) if (axo > 0 and xrp > 0) else 0.0

    payload = {

        "axo_usd": round(axo, 6),

        "xrp_usd": round(xrp, 6),

        "axo_per_xrp": round(axo_per_xrp, 6) if axo_per_xrp else 0,

        "source": "coingecko",

        "ts": int(time.time())

    }

    resp = make_response(jsonify(payload))

    resp.headers["Cache-Control"] = "no-store"

    return resp



# ------------------ Admin (UI + Auth + Config) ------------------

@app.get("/admin")

def admin_ui():

    return render_template_string(ADMIN_HTML)



@app.post("/api/admin/login")

def admin_login():

    data = request.get_json(silent=True) or {}

    pin = str(data.get("pin", "")).strip()

    if pin == ADMIN_PIN and len(pin) > 0:

        session["is_admin"] = True

        session.permanent = False

        resp = make_response(jsonify({"ok": True}))

        resp.headers["Cache-Control"] = "no-store"

        return resp

    return jsonify({"ok": False, "error": "Invalid PIN"}), 401



@app.post("/api/admin/logout")

def admin_logout():

    session.pop("is_admin", None)

    resp = make_response(jsonify({"ok": True}))

    resp.headers["Cache-Control"] = "no-store"

    return resp



@app.get("/api/admin/config")

def admin_get_config():

    if not admin_authed():

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    with STATE_LOCK:

        data = {"ok": True, "data": SETTINGS, "blacklist": sorted(BLOCKED)}

    resp = make_response(jsonify(data))

    resp.headers["Cache-Control"] = "no-store"

    return resp



@app.post("/api/admin/config")

def admin_set_config():

    if not admin_authed():

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}

    with STATE_LOCK:

        if "signup_bonus" in body:    SETTINGS["signup_bonus"] = int(body["signup_bonus"])

        if "referral_reward" in body: SETTINGS["referral_reward"] = int(body["referral_reward"])

        if "axo_price_usd" in body:   SETTINGS["axo_price_usd"] = float(body["axo_price_usd"])

        if "fee_xrp" in body:         SETTINGS["fee_xrp"] = float(body["fee_xrp"])

        if "vault_addr" in body:      SETTINGS["vault_addr"] = str(body["vault_addr"]).strip()

    # Force re-login next time:

    session.pop("is_admin", None)

    resp = make_response(jsonify({"ok": True, "data": SETTINGS}))

    resp.headers["Cache-Control"] = "no-store"

    return resp



# ------------------ Admin: Blacklist & Manual Transfer (stub) ------------------

@app.post("/api/admin/blacklist/add")

def admin_bl_add():

    if not admin_authed():

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    w = str((request.get_json(silent=True) or {}).get("wallet","")).strip()

    if not (w and w.startswith("r")):

        return jsonify({"ok": False, "error": "Invalid wallet"}), 400

    with STATE_LOCK:

        BLOCKED.add(w)

        bl = sorted(BLOCKED)

    return jsonify({"ok": True, "blacklist": bl})



@app.post("/api/admin/blacklist/remove")

def admin_bl_remove():

    if not admin_authed():

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    w = str((request.get_json(silent=True) or {}).get("wallet","")).strip()

    with STATE_LOCK:

        BLOCKED.discard(w)

        bl = sorted(BLOCKED)

    return jsonify({"ok": True, "blacklist": bl})



@app.post("/api/admin/transfer")

def admin_transfer():

    if not admin_authed():

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}

    to = str(body.get("to","")).strip()

    amt = float(body.get("amount_axo", 0))

    if not (to and to.startswith("r")):

        return jsonify({"ok": False, "error": "Invalid r-address"}), 400

    if amt <= 0:

        return jsonify({"ok": False, "error": "Amount must be > 0"}), 400

    if to in BLOCKED:

        return jsonify({"ok": False, "error": "Wallet is blacklisted"}), 403

    # Stub success (no on-ledger send here)

    return jsonify({"ok": True, "txid": "demo-transfer", "to": to, "amount_axo": amt, "real": False})



# ------------------ Signup Flow ------------------

@app.post("/api/signup/prepare")

def signup_prepare():

    data = request.get_json(silent=True) or {}

    wallet = (data.get("address") or "").strip()

    if not (wallet and wallet.startswith("r") and len(wallet) > 20):

        return jsonify({"ok": False, "error": "Invalid XRPL address"}), 400

    with STATE_LOCK:

        if wallet in BLOCKED:

            return jsonify({"ok": False, "error": "Wallet blocked"}), 403

    session["wallet"] = wallet

    session["ref"] = (data.get("ref") or "").strip()

    return jsonify({"ok": True})



@app.post("/api/signup/claim")

def signup_claim():

    body = request.get_json(silent=True) or {}

    wallet = (body.get("address") or session.get("wallet") or "").strip()

    ref    = (body.get("ref") or session.get("ref") or "").strip()

    if not (wallet and wallet.startswith("r")):

        return jsonify({"ok": False, "error": "address required"}), 400



    with STATE_LOCK:

        if wallet in BLOCKED:

            return jsonify({"ok": False, "error": "Wallet blocked"}), 403

        if wallet in CLAIMED:

            return jsonify({"ok": False, "error": "Signup bonus already claimed"}), 409

        bonus = int(SETTINGS["signup_bonus"])

        ref_reward = int(SETTINGS["referral_reward"])

        fee_xrp = float(SETTINGS["fee_xrp"])

        vault = str(SETTINGS["vault_addr"]).strip()



    if fee_xrp > 0 and not vault:

        return jsonify({"ok": False, "error": "Vault not configured for fee"}), 500



    with STATE_LOCK:

        CLAIMED.add(wallet)



    out = {

        "ok": True,

        "awarded_axo": bonus,

        "ref_awarded_axo": 0,

        "fee_xrp": fee_xrp,

        "note": "Demo mode (no on-ledger tx)"

    }

    if ref and ref != wallet and ref.startswith("r") and ref not in BLOCKED and ref_reward > 0:

        out["ref_awarded_axo"] = ref_reward

    return jsonify(out)



# ------------------ Health & SPA catch-all ------------------

@app.get("/api/hello")

def api_hello():

    return jsonify({"message": "Hello from AXO API"})



@app.errorhandler(404)

def not_found(_):

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catchall(unused=None):

    if unused and unused.startswith("api/"):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



# ------------------ Embedded Admin HTML (now with credentials:'same-origin') ------------------

ADMIN_HTML = r"""

<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8"/>

<meta name="viewport" content="width=device-width,initial-scale=1"/>

<title>AXO Admin</title>

<style>

:root{--bg:#0f172a;--panel:#111827;--text:#e5e7eb;--muted:#9ca3af;--accent:#2563eb}

*{box-sizing:border-box}

body{margin:0;background:radial-gradient(1200px 600px at 50% -10%,#33415533,transparent),var(--bg);color:var(--text);font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial}

.wrap{max-width:1100px;margin:40px auto;padding:20px}

.card{background:var(--panel);border-radius:14px;padding:22px;box-shadow:0 12px 30px #0007;border:1px solid #1f2937}

h1{margin:0 0 16px;font-size:28px;letter-spacing:.4px}

h2{margin:24px 0 8px;font-size:16px;color:#cbd5e1}

.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}

label{display:block;font-size:13px;color:var(--muted);margin:0 0 6px}

input,select,textarea{width:100%;padding:12px 14px;border:1px solid #374151;border-radius:10px;background:#0b1220;color:#e5e7eb;outline:none}

.row{margin:10px 0}

.actions{display:flex;gap:12px;justify-content:flex-end;margin-top:18px}

button{padding:10px 16px;border-radius:10px;border:1px solid #2a3a6a;background:#101936;color:#cbd5e1;cursor:pointer}

button.primary{background:linear-gradient(180deg,#3b82f6,#2563eb);border-color:#2b50a8;color:white}

.pin{max-width:420px;margin:80px auto 0}

.pin h2{font-weight:600;font-size:22px;margin:0 0 10px}

.hint{color:#94a3b8;font-size:13px;margin-top:6px}

.ok{color:#10b981}.err{color:#f87171}

.tag{padding:6px 10px;border-radius:100px;border:1px solid #374151;background:#0b1220;margin:4px 6px 0 0;display:inline-block}

.kv{display:grid;grid-template-columns:220px 1fr;gap:10px;align-items:center}

</style>

</head>

<body>

<div class="wrap">

  <!-- PIN -->

  <div id="pinCard" class="card pin" style="display:none">

    <h2>Enter Admin PIN</h2>

    <div class="row">

      <label for="pin">PIN</label>

      <input id="pin" type="password" placeholder="••••••"/>

    </div>

    <div class="actions">

      <button onclick="login()">Unlock</button>

      <button onclick="goHome()">Back</button>

    </div>

    <div id="pinMsg" class="hint"></div>

  </div>



  <!-- Admin -->

  <div id="adminCard" class="card" style="display:none">

    <h1>AXO Admin</h1>



    <h2>Incentives</h2>

    <div class="grid">

      <div><label>Signup Bonus (AXO)</label><input id="signup_bonus" type="number" min="0" step="1"></div>

      <div><label>Referral Reward (AXO)</label><input id="referral_reward" type="number" min="0" step="1"></div>

      <div><label>AXO Static Price (USD)</label><input id="axo_price_usd" type="number" min="0" step="0.0001"></div>

    </div>



    <h2>Fees & Vault</h2>

    <div class="grid">

      <div><label>Flat Fee (XRP) per claim</label><input id="fee_xrp" type="number" min="0" step="0.000001"></div>

      <div class="kv"><label>Vault Address (r‑...)</label><input id="vault_addr" placeholder="r........"/></div>

      <div></div>

    </div>

    <div class="hint">XRPL network fee comes out first from the flat fee; remainder goes to the vault. XRP never leaves the vault. AXO payouts are sent from the vault.</div>



    <h2>Blacklist</h2>

    <div class="kv"><label>Wallet (r‑…)</label><input id="bl_addr" placeholder="r..." /></div>

    <div class="actions" style="justify-content:flex-start">

      <button onclick="blAdd()">Add</button>

      <button onclick="blRemove()">Remove</button>

    </div>

    <div id="bl_list"></div>



    <h2>Manual Transfer (AXO → wallet)</h2>

    <div class="grid">

      <div><label>Recipient (r‑…)</label><input id="tx_to" placeholder="r..." /></div>

      <div><label>Amount (AXO)</label><input id="tx_amt" type="number" min="0" step="0.000001"/></div>

      <div class="actions" style="justify-content:flex-start"><button class="primary" onclick="manualSend()">Send</button></div>

    </div>

    <div id="tx_msg" class="hint"></div>



    <div class="actions">

      <button onclick="logoutAndHome()">Close</button>

      <button class="primary" onclick="saveAndExit()">Save</button>

    </div>

    <div id="msg" class="hint"></div>

  </div>

</div>



<script>

// always include cookies for same-site requests

const WITH_CRED = { credentials: 'same-origin' };



function goHome(){ location.href = '/'; }



async function isAuthed(){

  const r = await fetch('/api/admin/config', WITH_CRED);

  return r.status === 200;

}



async function show(){

  if(await isAuthed()){ await load(); document.getElementById('adminCard').style.display=''; }

  else { document.getElementById('pinCard').style.display=''; }

}



async function login(){

  const pin = document.getElementById('pin').value.trim();

  const r = await fetch('/api/admin/login', {

    method:'POST',

    headers:{'Content-Type':'application/json'},

    body: JSON.stringify({pin}),

    ...WITH_CRED

  });

  const m = document.getElementById('pinMsg');

  if(r.ok){ m.textContent='Unlocked.'; m.className='hint ok'; location.reload(); }

  else   { m.textContent='Invalid PIN.'; m.className='hint err'; }

}



async function logout(){

  await fetch('/api/admin/logout', { method:'POST', ...WITH_CRED });

}

async function logoutAndHome(){ await logout(); goHome(); }



async function load(){

  const r = await fetch('/api/admin/config', WITH_CRED); if(!r.ok) return;

  const j = await r.json(); const s=j.data||{}; const bl=j.blacklist||[];

  for(const k of ['signup_bonus','referral_reward','axo_price_usd','fee_xrp','vault_addr']){

    const el=document.getElementById(k); if(el) el.value = s[k] ?? (el.type==='number'?0:'');

  }

  renderBL(bl);

}



function renderBL(list){

  const c=document.getElementById('bl_list'); c.innerHTML='';

  list.forEach(w=>{ const t=document.createElement('span'); t.className='tag'; t.textContent=w; c.appendChild(t); });

}



async function saveAndExit(){

  await save(true);

  await logout();

  goHome();

}



async function save(silent=false){

  const body={

    signup_bonus:Number(document.getElementById('signup_bonus').value||0),

    referral_reward:Number(document.getElementById('referral_reward').value||0),

    axo_price_usd:Number(document.getElementById('axo_price_usd').value||0.01),

    fee_xrp:Number(document.getElementById('fee_xrp').value||0),

    vault_addr:String(document.getElementById('vault_addr').value||'').trim()

  };

  const r=await fetch('/api/admin/config',{

    method:'POST',

    headers:{'Content-Type':'application/json'},

    body: JSON.stringify(body),

    ...WITH_CRED

  });

  if(silent) return r.ok;

  const el=document.getElementById('msg'); el.textContent=r.ok?'Saved.':'Save failed'; el.className='hint '+(r.ok?'ok':'err');

  return r.ok;

}



async function blAdd(){

  const w=document.getElementById('bl_addr').value.trim(); if(!w) return;

  const r=await fetch('/api/admin/blacklist/add',{

    method:'POST', headers:{'Content-Type':'application/json'},

    body: JSON.stringify({wallet:w}), ...WITH_CRED

  });

  const j=await r.json(); if(j.ok) renderBL(j.blacklist);

}



async function blRemove(){

  const w=document.getElementById('bl_addr').value.trim(); if(!w) return;

  const r=await fetch('/api/admin/blacklist/remove',{

    method:'POST', headers:{'Content-Type':'application/json'},

    body: JSON.stringify({wallet:w}), ...WITH_CRED

  });

  const j=await r.json(); if(j.ok) renderBL(j.blacklist);

}



show();

</script>

</body>

</html>

"""
