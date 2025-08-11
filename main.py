# main.py — AXO Utility Hub (final admin + core flows)

import os, time, json, hashlib, math, threading

from typing import Any, Dict, Set, Tuple

from flask import Flask, jsonify, request, send_from_directory, render_template, make_response

import requests



# Optional XRPL (real sends only if XRPL_ENABLE_REAL=true)

XRPL_ENABLE_REAL = os.getenv("XRPL_ENABLE_REAL", "false").strip().lower() in ("1","true","yes","on")

try:

    if XRPL_ENABLE_REAL:

        from xrpl.clients import JsonRpcClient

        from xrpl.wallet import Wallet

        from xrpl.models.transactions import Payment

        from xrpl.transaction import safe_sign_and_autofill_transaction, send_reliable_submission

        from xrpl.models.amounts import IssuedCurrencyAmount

        from xrpl.models.requests import AccountInfo

        from xrpl.utils import xrp_to_drops

except Exception:

    XRPL_ENABLE_REAL = False  # fallback to demo mode if lib not available



app = Flask(__name__, template_folder="templates")



# ---------------- Static SPA ----------------

STATIC_ROOT = os.path.join(os.getcwd(), "dist", "public")

INDEX_FILE = os.path.join(STATIC_ROOT, "index.html")

print("STATIC_ROOT =", STATIC_ROOT)

print("INDEX_FILE =", INDEX_FILE, "exists?", os.path.exists(INDEX_FILE))

if not os.path.exists(INDEX_FILE):

    raise RuntimeError("index.html not found at " + INDEX_FILE)



@app.route("/")

def index():

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/assets/<path:filename>")

def assets(filename):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)



@app.errorhandler(404)

def spa_404(_):

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catch(unused=None):

    if unused and unused.startswith("api/"):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



# ---------------- Config / Settings ----------------

def _env_float(name: str, default: float) -> float:

    try: return float(os.getenv(name, str(default)))

    except: return default



ADMIN_PIN = os.getenv("ADMIN_PIN", "").strip()

VAULT_ADDR = os.getenv("XRPL_VAULT_ADDR", "").strip()       # r-... (XRP never leaves vault)

AXO_PRICE_USD = _env_float("AXO_PRICE_USD", 0.01)            # static price, editable in Admin

FEE_XRP = _env_float("FEE_XRP", 0.25)                        # flat fee; XRPL fee comes first; remainder → vault



# XRPL network config (only used if XRPL_ENABLE_REAL=true)

XRPL_NETWORK = os.getenv("XRPL_NETWORK", "mainnet").lower()  # mainnet|testnet

XRPL_RPC = "https://s1.ripple.com:51234" if XRPL_NETWORK=="mainnet" else "https://s.altnet.rippletest.net:51234"

XRPL_SEED = os.getenv("XRPL_SEED", "").strip()               # vault signer seed (careful!)

AXO_ISSUER = os.getenv("AXO_ISSUER", "").strip()             # issuer r-...

AXO_CODE = os.getenv("AXO_CURRENCY_CODE", "AXO").strip()     # typically "AXO"



SETTINGS: Dict[str, Any] = {

    "signup_bonus": 1000,

    "referral_reward": 300,

    "axo_price_usd": AXO_PRICE_USD,

    "fee_xrp": FEE_XRP,

    "vault_addr": VAULT_ADDR,

}



# runtime tables (simple in-memory demo storage)

CLAIMED: Set[str] = set()          # wallets that already got the one-time signup bonus

BLACKLIST: Set[str] = set()        # banned wallets (no payouts)

REF_COUNTS: Dict[str, int] = {}    # referrer => count of rewarded referrals

RATE_WINDOW: Dict[str, list] = {}  # ip/wallet => timestamps (for basic rate-limiting)

LOCK = threading.Lock()



# ---------------- Market API ----------------

@app.get("/api/market")

def api_market():

    xrp_usd = 0.0

    try:

        r = requests.get(

            "https://api.coingecko.com/api/v3/simple/price",

            params={"ids": "ripple", "vs_currencies": "usd"},

            timeout=8

        )

        if r.ok:

            xrp_usd = float(r.json().get("ripple", {}).get("usd", 0) or 0.0)

    except Exception:

        xrp_usd = 0.0

    axo_usd = float(SETTINGS.get("axo_price_usd", 0.01) or 0.01)

    axo_per_xrp = (xrp_usd / axo_usd) if axo_usd > 0 else 0.0

    return jsonify({

        "axo_usd": round(axo_usd, 6),

        "xrp_usd": round(xrp_usd, 6),

        "axo_per_xrp": round(axo_per_xrp, 6),

        "source": "coingecko",

        "ts": int(time.time())

    })



# ---------------- Admin auth helpers ----------------

COOKIE = "axo_admin"



def _pin_ok(pin: str) -> bool:

    return bool(ADMIN_PIN) and pin == ADMIN_PIN



def _has_admin_cookie(req) -> bool:

    tok = req.cookies.get(COOKIE, "")

    if not tok or not ADMIN_PIN:

        return False

    expect = hashlib.sha256(("ok:" + ADMIN_PIN).encode()).hexdigest()

    return tok == expect



def _make_cookie(resp):

    tok = hashlib.sha256(("ok:" + ADMIN_PIN).encode()).hexdigest()

    resp.set_cookie(COOKIE, tok, httponly=True, secure=True, samesite="Lax")

    return resp



def _clear_cookie(resp):

    resp.delete_cookie(COOKIE, samesite="Lax")

    return resp



# ---------------- Admin pages & APIs ----------------

@app.get("/admin")

def admin_page():

    return render_template("admin.html")



@app.post("/api/admin/login")

def admin_login():

    data = request.get_json(silent=True) or {}

    if not _pin_ok((data.get("pin") or "").strip()):

        return jsonify({"ok": False, "error": "Invalid PIN"}), 401

    return _make_cookie(make_response(jsonify({"ok": True})))



@app.post("/api/admin/logout")

def admin_logout():

    return _clear_cookie(make_response(jsonify({"ok": True})))



@app.get("/api/admin/config")

def admin_get_cfg():

    if not _has_admin_cookie(request):

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    return jsonify({"ok": True, "data": SETTINGS, "blacklist": sorted(BLACKLIST)})



@app.post("/api/admin/config")

def admin_set_cfg():

    if not _has_admin_cookie(request):

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    with LOCK:

        if "signup_bonus" in data: SETTINGS["signup_bonus"] = int(data["signup_bonus"])

        if "referral_reward" in data: SETTINGS["referral_reward"] = int(data["referral_reward"])

        if "axo_price_usd" in data: SETTINGS["axo_price_usd"] = float(data["axo_price_usd"])

        if "fee_xrp" in data: SETTINGS["fee_xrp"] = float(data["fee_xrp"])

        if "vault_addr" in data: SETTINGS["vault_addr"] = str(data["vault_addr"]).strip()

    return jsonify({"ok": True, "data": SETTINGS})



@app.post("/api/admin/blacklist/add")

def admin_blacklist_add():

    if not _has_admin_cookie(request):

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    w = (request.get_json(silent=True) or {}).get("wallet","").strip()

    if not (w and w.startswith("r")):

        return jsonify({"ok": False, "error": "Invalid wallet"}), 400

    with LOCK:

        BLACKLIST.add(w)

    return jsonify({"ok": True, "blacklist": sorted(BLACKLIST)})



@app.post("/api/admin/blacklist/remove")

def admin_blacklist_remove():

    if not _has_admin_cookie(request):

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    w = (request.get_json(silent=True) or {}).get("wallet","").strip()

    with LOCK:

        BLACKLIST.discard(w)

    return jsonify({"ok": True, "blacklist": sorted(BLACKLIST)})



@app.post("/api/admin/transfer")

def admin_transfer():

    """Manual admin transfer of AXO from vault to target wallet."""

    if not _has_admin_cookie(request):

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}

    to = (body.get("to") or "").strip()

    amt = float(body.get("amount_axo") or 0)

    if not (to and to.startswith("r")):

        return jsonify({"ok": False, "error": "Invalid r-address"}), 400

    if amt <= 0:

        return jsonify({"ok": False, "error": "Amount must be > 0"}), 400

    if to in BLACKLIST:

        return jsonify({"ok": False, "error": "Wallet is blacklisted"}), 403



    # DEMO: no real XRPL unless enabled

    if not XRPL_ENABLE_REAL:

        # pretend success

        return jsonify({"ok": True, "txid": "demo-admin-transfer", "to": to, "amount_axo": amt, "real": False})



    # Real XRPL (IssuedCurrencyAmount payment of AXO)

    try:

        client = JsonRpcClient(XRPL_RPC)

        wallet = Wallet(seed=XRPL_SEED, sequence=0)  # sequence autofilled

        amount = IssuedCurrencyAmount(currency=AXO_CODE, issuer=AXO_ISSUER, value=str(amt))

        tx = Payment(account=wallet.classic_address, destination=to, amount=amount)

        signed = safe_sign_and_autofill_transaction(tx, wallet, client)

        res = send_reliable_submission
