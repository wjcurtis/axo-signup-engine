# main.py — AXO Utility Hub (Flask + SPA + Admin v2)

import os, json, time, hashlib

from typing import Any, Dict, List

from flask import (

    Flask, send_from_directory, jsonify, request, make_response, render_template

)

import requests



app = Flask(__name__, template_folder="templates")



# ---------- Static (SPA) ----------

STATIC_ROOT = os.path.join(os.getcwd(), "dist", "public")

INDEX_FILE = os.path.join(STATIC_ROOT, "index.html")

print("STATIC_ROOT =", STATIC_ROOT)

print("INDEX_FILE =", INDEX_FILE, "exists?", os.path.exists(INDEX_FILE))

if not os.path.exists(INDEX_FILE):

    raise RuntimeError("index.html not found at " + INDEX_FILE)



@app.route("/")

def serve_index():

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/assets/<path:filename>")

def serve_assets(filename: str):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)



@app.errorhandler(404)

def not_found(_):

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catchall(unused=None):

    if unused and unused.startswith("api/"):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



# ---------- Defaults & Settings ----------

def _env_bool(name: str, default: bool) -> bool:

    v = os.getenv(name)

    if v is None: return default

    return str(v).strip().lower() in ("1","true","yes","on")



AXO_PRICE_USD = float(os.getenv("AXO_PRICE_USD", "0.01"))

FEE_XRP       = float(os.getenv("FEE_XRP", "0.25"))

VAULT_ADDR    = os.getenv("XRPL_VAULT_ADDR", "").strip()



# Unified, editable settings (fast in‑memory demo storage)

SETTINGS: Dict[str, Any] = {

    # Incentives

    "signup_bonus":        int(os.getenv("AXO_SIGNUP_BONUS", "1000")),

    "referral_reward":     int(os.getenv("AXO_REFERRAL_REWARD", "300")),

    "require_trustline":   _env_bool("REQUIRE_TRUSTLINE", True),



    # Buying / pricing

    "axo_price_usd":       AXO_PRICE_USD,      # static AXO price

    "buy_enabled":         _env_bool("BUY_ENABLED", True),



    # Fees / treasury

    "fee_xrp":             FEE_XRP,            # flat fee charged to user (covers XRPL fee; remainder to vault)

    "vault_addr":          VAULT_ADDR,         # r-addr (XRP never leaves vault)



    # Abuse controls

    "daily_cap_axo":       int(os.getenv("DAILY_CAP_AXO", "500000")),  # max AXO airdropped per day

    "max_claims_per_wallet": int(os.getenv("MAX_CLAIMS_PER_WALLET", "1")),

    "rate_limit_claims_per_hour": int(os.getenv("CLAIMS_PER_HOUR", "60")),

    "whitelist_addresses": [],  # list of r-... strings; optional

    "blacklist_addresses": [],  # optional



    # Ops toggles

    "airdrop_paused":      _env_bool("AIRDROP_PAUSED", False),

    "maintenance_mode":    _env_bool("MAINTENANCE_MODE", False),

    "quick_signup_enabled":_env_bool("QUICK_SIGNUP_ENABLED", False),

}



# ---------- Market API ----------

@app.route("/api/market")

def market():

    xrp_usd = 0.0

    try:

        r = requests.get(

            "https://api.coingecko.com/api/v3/simple/price",

            params={"ids":"ripple","vs_currencies":"usd"},

            timeout=8

        )

        if r.ok:

            xrp_usd = float(r.json().get("ripple",{}).get("usd",0) or 0.0)

    except Exception:

        xrp_usd = 0.0



    axo_usd    = float(SETTINGS.get("axo_price_usd", 0.01) or 0.01)

    axo_per_xrp= (xrp_usd/axo_usd) if axo_usd>0 else 0.0

    return jsonify({

        "axo_usd": round(axo_usd,6),

        "xrp_usd": round(xrp_usd,6),

        "axo_per_xrp": round(axo_per_xrp,6),

        "source":"coingecko","ts":int(time.time()),"cached_seconds":None

    })



# ---------- Admin auth ----------

ADMIN_PIN = os.getenv("ADMIN_PIN","").strip()

COOKIE_NAME = "axo_admin"



def _pin_ok(pin:str)->bool:

    return bool(ADMIN_PIN) and pin==ADMIN_PIN



def _has_admin_cookie(req)->bool:

    token = req.cookies.get(COOKIE_NAME,"")

    if not token or not ADMIN_PIN: return False

    expect = hashlib.sha256(("ok:"+ADMIN_PIN).encode()).hexdigest()

    return token==expect



def _make_admin_cookie(resp):

    val = hashlib.sha256(("ok:"+ADMIN_PIN).encode()).hexdigest()

    # session cookie (no max_age) so it disappears on browser close

    resp.set_cookie(COOKIE_NAME, val, httponly=True, secure=True, samesite="Lax")

    return resp



def _clear_admin_cookie(resp):

    resp.delete_cookie(COOKIE_NAME, samesite="Lax")

    return resp



# ---------- Admin routes ----------

@app.route("/admin")

def admin_page():

    # Always render template; it shows PIN gate if not authed

    return render_template("admin.html")



@app.post("/api/admin/login")

def admin_login():

    data = request.get_json(silent=True) or {}

    pin = (data.get("pin") or "").strip()

    if not _pin_ok(pin):

        return jsonify({"ok":False,"error":"Invalid PIN"}), 401

    resp = make_response(jsonify({"ok":True}))

    return _make_admin_cookie(resp)



@app.post("/api/admin/logout")

def admin_logout():

    resp = make_response(jsonify({"ok":True}))

    return _clear_admin_cookie(resp)



@app.get("/api/admin/config")

def admin_get_config():

    if not _has_admin_cookie(request):

        return jsonify({"ok":False,"error":"Unauthorized"}), 401

    return jsonify({"ok":True,"data":SETTINGS})



@app.post("/api/admin/config")

def admin_set_config():

    if not _has_admin_cookie(request):

        return jsonify({"ok":False,"error":"Unauthorized"}), 401

    data = request.get_json(silent=True) or {}



    def _norm_bool(v): 

        if isinstance(v,bool): return v

        return str(v).strip().lower() in ("1","true","yes","on")

    def _norm_float(v, d=0.0):

        try: return float(v)

        except: return d

    def _norm_int(v, d=0):

        try: return int(v)

        except: return d

    def _norm_list_csv(v) -> List[str]:

        if not v: return []

        if isinstance(v, list): return [s.strip() for s in v if s]

        return [s.strip() for s in str(v).split(",") if s.strip()]



    # Accept & normalize known fields

    allowed = {

        "signup_bonus":       ("int", "signup_bonus"),

        "referral_reward":    ("int", "referral_reward"),

        "require_trustline":  ("bool","require_trustline"),

        "axo_price_usd":      ("float","axo_price_usd"),

        "buy_enabled":        ("bool","buy_enabled"),

        "fee_xrp":            ("float","fee_xrp"),

        "vault_addr":         ("str", "vault_addr"),

        "daily_cap_axo":      ("int", "daily_cap_axo"),

        "max_claims_per_wallet": ("int","max_claims_per_wallet"),

        "rate_limit_claims_per_hour": ("int","rate_limit_claims_per_hour"),

        "whitelist_addresses":("list","whitelist_addresses"),

        "blacklist_addresses":("list","blacklist_addresses"),

        "airdrop_paused":     ("bool","airdrop_paused"),

        "maintenance_mode":   ("bool","maintenance_mode"),

        "quick_signup_enabled":("bool","quick_signup_enabled"),

    }

    for key, (kind, dest) in allowed.items():

        if key not in data: 

            continue

        v = data[key]

        if kind=="bool":   SETTINGS[dest] = _norm_bool(v)

        elif kind=="int":  SETTINGS[dest] = _norm_int(v, SETTINGS[dest])

        elif kind=="float":SETTINGS[dest] = _norm_float(v, SETTINGS[dest])

        elif kind=="list": SETTINGS[dest] = _norm_list_csv(v)

        else:              SETTINGS[dest] = str(v)



    return jsonify({"ok":True,"data":SETTINGS})
