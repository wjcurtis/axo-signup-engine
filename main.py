import os, json, time

from functools import wraps



import requests

from flask import Flask, send_from_directory, jsonify, request, session, make_response



# ----------- Config ----------

ROOT = os.getcwd()

STATIC_ROOT = os.path.join(ROOT, "dist", "public")  # serves / (index.html) and /assets/*

INDEX_FILE = os.path.join(STATIC_ROOT, "index.html")



ADMIN_PIN = os.getenv("ADMIN_PIN", "").strip()

AXO_PRICE = float(os.getenv("AXO_PRICE", "0.01"))      # static AXO price (USD)

XRP_VAULT_ADDR = os.getenv("XRP_VAULT_ADDR", "")

WALLET_SEED = os.getenv("WALLET_SEED", "")



SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "replace-this-with-a-long-random-string")



# ----------- App -------------

app = Flask(__name__)

app.config["SECRET_KEY"] = SECRET_KEY

app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.config["SESSION_COOKIE_SECURE"] = True



# Simple in‑memory admin “config” (can be extended or persisted later)

ADMIN_STATE = {

    "signup_bonus": 1000,

    "referral_reward": 300,

    "require_trustline": True,

    "axo_price_usd": AXO_PRICE,

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



# ----------- Helpers ----------

def admin_required(fn):

    @wraps(fn)

    def _wrap(*args, **kwargs):

        if not session.get("is_admin"):

            return jsonify({"error": "auth required"}), 401

        return fn(*args, **kwargs)

    return _wrap





# ----------- Static routes ----

@app.route("/")

def serve_index():

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/assets/<path:filename>")

def serve_assets(filename: str):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)





# ----------- API: market ------

# Returns: { axo_usd, xrp_usd, axo_per_xrp, source, ts }

@app.route("/api/market")

def api_market():

    axo_usd = float(ADMIN_STATE.get("axo_price_usd", AXO_PRICE) or AXO_PRICE)

    xrp_usd = 0.0

    source = "coingecko"

    try:

        # small, fast endpoint

        r = requests.get(

            "https://api.coingecko.com/api/v3/simple/price",

            params={"ids": "ripple", "vs_currencies": "usd"},

            timeout=6,

        )

        if r.ok:

            xrp_usd = float(r.json().get("ripple", {}).get("usd", 0) or 0)

        else:

            source = f"coingecko:{r.status_code}"

    except Exception:

        source = "coingecko:error"



    axo_per_xrp = (xrp_usd / axo_usd) if (axo_usd > 0 and xrp_usd > 0) else 0.0

    return jsonify({

        "axo_usd": round(axo_usd, 6),

        "xrp_usd": round(xrp_usd, 6),

        "axo_per_xrp": axo_per_xrp,

        "source": source,

        "ts": int(time.time())

    })





# ----------- API: admin auth ---

@app.route("/api/admin/login", methods=["POST"])

def admin_login():

    if not ADMIN_PIN:

        return jsonify({"error": "ADMIN_PIN not set"}), 500

    try:

        pin = (request.get_json() or {}).get("pin", "").strip()

    except Exception:

        pin = ""

    if pin and pin == ADMIN_PIN:

        session["is_admin"] = True

        # short session; adjust as needed

        session.permanent = False

        return jsonify({"ok": True})

    return jsonify({"error": "invalid pin"}), 401





@app.route("/api/admin/logout", methods=["POST"])

def admin_logout():

    session.clear()

    resp = make_response(jsonify({"ok": True}))

    return resp





# ----------- API: admin config -

@app.route("/api/admin/config", methods=["GET"])

@admin_required

def admin_get_config():

    return jsonify({"data": ADMIN_STATE})



@app.route("/api/admin/config", methods=["POST"])

@admin_required

def admin_set_config():

    try:

        data = request.get_json() or {}

        # coerce types safely

        def to_bool(v): return str(v).lower() == "true" if isinstance(v, str) else bool(v)

        def to_num(v, d=0): 

            try: return float(v)

            except Exception: return d



        ADMIN_STATE.update({

            "signup_bonus": int(to_num(data.get("signup_bonus"), ADMIN_STATE["signup_bonus"])),

            "referral_reward": int(to_num(data.get("referral_reward"), ADMIN_STATE["referral_reward"])),

            "require_trustline": to_bool(data.get("require_trustline")),

            "axo_price_usd": float(to_num(data.get("axo_price_usd"), ADMIN_STATE["axo_price_usd"])),

            "buy_enabled": to_bool(data.get("buy_enabled")),

            "quick_signup_enabled": to_bool(data.get("quick_signup_enabled")),

            "fee_xrp": float(to_num(data.get("fee_xrp"), ADMIN_STATE["fee_xrp"])),

            "vault_addr": (data.get("vault_addr") or "").strip() or ADMIN_STATE["vault_addr"],

            "daily_cap_axo": int(to_num(data.get("daily_cap_axo"), ADMIN_STATE["daily_cap_axo"])),

            "max_claims_per_wallet": int(to_num(data.get("max_claims_per_wallet"), ADMIN_STATE["max_claims_per_wallet"])),

            "rate_limit_claims_per_hour": int(to_num(data.get("rate_limit_claims_per_hour"), ADMIN_STATE["rate_limit_claims_per_hour"])),

            "whitelist_addresses": [x.strip() for x in (data.get("whitelist_addresses") or "").split(",") if x.strip()],

            "blacklist_addresses": [x.strip() for x in (data.get("blacklist_addresses") or "").split(",") if x.strip()],

            "airdrop_paused": to_bool(data.get("airdrop_paused")),

            "maintenance_mode": to_bool(data.get("maintenance_mode")),

        })

        return jsonify({"ok": True, "data": ADMIN_STATE})

    except Exception as e:

        return jsonify({"error": "bad request", "detail": str(e)}), 400





# ----------- Admin page (/admin)

# Minimal admin shell; the public UI links here via the rocket icon.

ADMIN_HTML = """

<!doctype html><html><head>

<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>

<title>AXO Admin</title>

<style>

body{margin:0;background:#0f172a;color:#e5e7eb;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial}

.wrap{max-width:1000px;margin:40px auto;padding:20px}

.card{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:22px}

h1{margin:0 0 16px;font-size:24px}

.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}

label{display:block;font-size:13px;color:#9ca3af;margin:0 0 6px}

input,select,textarea{width:100%;padding:10px 12px;border:1px solid #374151;border-radius:10px;background:#0b1220;color:#e5e7eb}

.actions{display:flex;gap:12px;justify-content:flex-end;margin-top:16px}

button{padding:10px 14px;border-radius:10px;border:1px solid #2a3a6a;background:#101936;color:#cbd5e1;cursor:pointer}

button.primary{background:linear-gradient(180deg,#3b82f6,#2563eb);border-color:#2b50a8;color:white}

.pin{max-width:420px;margin:80px auto 0}

.hint{color:#94a3b8;font-size:13px;margin-top:6px}

.ok{color:#10b981}.err{color:#f87171}

</style>

</head><body><div class="wrap">

  <div id="pinCard" class="card pin" style="display:none">

    <h1>Enter Admin PIN</h1>

    <label>PIN</label><input id="pin" type="password" placeholder="••••••"/>

    <div class="actions">

      <button onclick="login()">Unlock</button>

      <button onclick="goHome()">Back</button>

    </div>

    <div id="pinMsg" class="hint"></div>

  </div>



  <div id="adminCard" class="card" style="display:none">

    <h1>AXO Admin</h1>

    <div class="grid">

      <div><label>Signup Bonus (AXO)</label><input id="signup_bonus" type="number"></div>

      <div><label>Referral Reward (AXO)</label><input id="referral_reward" type="number"></div>

      <div><label>Require TrustLine</label><select id="require_trustline"><option>true</option><option>false</option></select></div>

    </div>

    <h3>Pricing & Flow</h3>

    <div class="grid">

      <div><label>AXO Price (USD)</label><input id="axo_price_usd" type="number" step="0.0001"></div>

      <div><label>Buy Enabled</label><select id="buy_enabled"><option>true</option><option>false</option></select></div>

      <div><label>Quick Signup</label><select id="quick_signup_enabled"><option>false</option><option>true</option></select></div>

    </div>

    <h3>Fees & Vault</h3>

    <div class="grid">

      <div><label>Flat Fee (XRP)</label><input id="fee_xrp" type="number" step="0.000001"></div>

      <div><label>Vault Address</label><input id="vault_addr" placeholder="r..."></div>

      <div></div>

    </div>

    <div class="actions">

      <button onclick="logoutAndHome()">Close</button>

      <button class="primary" onclick="saveAndExit()">Save</button>

    </div>

    <div id="msg" class="hint"></div>

  </div>

</div>

<script>

function goHome(){ location.href='/' }

async function isAuthed(){ const r=await fetch('/api/admin/config'); return r.status===200 }

async function show(){ if(await isAuthed()){ await load(); adminCard.style.display=''; } else { pinCard.style.display=''; }}

async function login(){

  const pin=document.getElementById('pin').value.trim();

  const r=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin})});

  const m=document.getElementById('pinMsg');

  if(r.ok){ m.textContent='Unlocked.'; m.className='hint ok'; location.reload(); }

  else{ m.textContent='Invalid PIN.'; m.className='hint err'; }

}

async function logout(){ await fetch('/api/admin/logout',{method:'POST'}) }

async function logoutAndHome(){ await logout(); goHome(); }

async function saveAndExit(){

  await save(true);

  await logout();

  goHome();

}

async function load(){

  const r=await fetch('/api/admin/config'); if(!r.ok) return;

  const s=(await r.json()).data||{};

  for(const k of ['signup_bonus','referral_reward','require_trustline','axo_price_usd','buy_enabled','quick_signup_enabled','fee_xrp','vault_addr']){

    const el=document.getElementById(k); if(!el) continue;

    if(el.tagName==='SELECT') el.value=String(s[k]); else el.value=s[k]??'';

  }

}

async function save(silent=false){

  const v=id=>document.getElementById(id).value;

  const body={

    signup_bonus:Number(v('signup_bonus')||0),

    referral_reward:Number(v('referral_reward')||0),

    require_trustline:(v('require_trustline')==='true'),

    axo_price_usd:Number(v('axo_price_usd')||0.01),

    buy_enabled:(v('buy_enabled')==='true'),

    quick_signup_enabled:(v('quick_signup_enabled')==='true'),

    fee_xrp:Number(v('fee_xrp')||0),

    vault_addr:v('vault_addr').trim()

  };

  const r=await fetch('/api/admin/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

  if(silent) return r.ok;

  const el=document.getElementById('msg'); el.textContent=r.ok?'Saved.':'Save failed'; el.className='hint '+(r.ok?'ok':'err');

  return r.ok;

}

const pinCard=document.getElementById('pinCard'), adminCard=document.getElementById('adminCard'); show();

</script>

</body></html>

"""



@app.route("/admin")

def admin_page():

    return ADMIN_HTML





# ----------- SPA fallback -----

@app.errorhandler(404)

def spa_404(_):

    # Send index.html so client-side routes work

    return send_from_directory(STATIC_ROOT, "index.html")





# ----------- Health ----------

@app.route("/healthz")

def health():

    return "ok", 200





# ----------- Entrypoint -------

# (gunicorn will import "app" from this file)
