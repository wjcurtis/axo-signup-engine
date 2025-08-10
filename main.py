# main.py — AXO Utility Hub (Flask + SPA + Admin)



import os

import json

import time

import threading

from typing import Any, Dict, Set



import requests

from flask import (

    Flask,

    jsonify,

    request,

    send_from_directory,

    render_template,

    session,

    make_response,

)



# ------------------ App & Config ------------------

app = Flask(__name__)



# Use a strong secret key in production (set RENDER/ENV: FLASK_SECRET_KEY)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))

app.config.update(

    SESSION_COOKIE_SAMESITE="Lax",

    SESSION_COOKIE_SECURE=True,

)



# Admin PIN (set in Render → Environment → ADMIN_PIN)

ADMIN_PIN = os.environ.get("ADMIN_PIN", "0000")



# Optional vault/wallet envs (placeholders for future on-ledger ops)

VAULT_WALLET = os.environ.get("VAULT_WALLET", "")       # r...

WALLET_SEED  = os.environ.get("WALLET_SEED", "")        # keep in env only!



# ------------------ Frontend (Static SPA) ------------------

# expects: dist/public/index.html and dist/public/assets/*

STATIC_ROOT = os.path.join(os.getcwd(), "dist", "public")

INDEX_FILE = os.path.join(STATIC_ROOT, "index.html")



print("STATIC_ROOT =", STATIC_ROOT)

print("INDEX_FILE exists? ", os.path.exists(INDEX_FILE))

if not os.path.exists(INDEX_FILE):

    raise RuntimeError("index.html not found at " + INDEX_FILE)



@app.route("/")

def serve_index():

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/assets/<path:filename>")

def serve_assets(filename: str):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)



# ------------------ Demo In‑Memory State ------------------

# (Free Render instances don’t have durable storage. These values reset on redeploy.)

DEFAULTS = {

    "signup_bonus": 1000,       # AXO

    "referral_bonus": 300,      # AXO

    "require_trustline": True,

    "axo_usd": 0.01,            # static AXO price (admin can change)

    "flat_fee_xrp": 0.25,       # covers network fee; remainder to vault

    "throttle_per_hr": 3,       # abuse throttle (basic)

}

STATE_LOCK = threading.Lock()

SETTINGS: Dict[str, Any] = dict(DEFAULTS)

BLOCKED: Set[str] = set()

ISSUED_WALLETS: Set[str] = set()    # each wallet can only claim signup bonus once



def admin_required() -> bool:

    return bool(session.get("is_admin"))



# ------------------ Admin Views ------------------

@app.route("/admin")

def admin_page():

    """

    Serves the admin UI. If not authed, shows PIN gate (handled by template JS via /api/admin/login).

    """

    return render_template("admin.html")



# ------------------ Admin API ------------------

@app.post("/api/admin/login")

def admin_login():

    data = request.get_json(silent=True) or {}

    pin = str(data.get("pin", "")).strip()

    if pin == ADMIN_PIN:

        session["is_admin"] = True

        # short admin session

        session.permanent = False

        return jsonify({"ok": True})

    return jsonify({"ok": False, "error": "Invalid PIN"}), 401



@app.post("/api/admin/logout")

def admin_logout():

    # Explicit logout for the modal "Close" and "Save" actions

    session.pop("is_admin", None)

    return jsonify({"ok": True})



@app.get("/api/admin/settings")

def admin_get_settings():

    if not admin_required():

        return jsonify({"ok": False, "error": "Auth required"}), 401

    with STATE_LOCK:

        return jsonify({"ok": True, "settings": SETTINGS, "blocked": sorted(BLOCKED)})



@app.post("/api/admin/settings")

def admin_save_settings():

    if not admin_required():

        return jsonify({"ok": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}

    with STATE_LOCK:

        # sanitize/assign with defaults if missing

        SETTINGS["signup_bonus"]     = int(data.get("signup_bonus", SETTINGS["signup_bonus"]))

        SETTINGS["referral_bonus"]   = int(data.get("referral_bonus", SETTINGS["referral_bonus"]))

        SETTINGS["require_trustline"]= bool(data.get("require_trustline", SETTINGS["require_trustline"]))

        SETTINGS["axo_usd"]          = float(data.get("axo_usd", SETTINGS["axo_usd"]))

        SETTINGS["flat_fee_xrp"]     = float(data.get("flat_fee_xrp", SETTINGS["flat_fee_xrp"]))

        SETTINGS["throttle_per_hr"]  = int(data.get("throttle_per_hr", SETTINGS["throttle_per_hr"]))

    # IMPORTANT: log out immediately so reopening admin requires PIN again

    session.pop("is_admin", None)

    return jsonify({"ok": True, "settings": SETTINGS})



@app.post("/api/admin/block")

def admin_block_wallet():

    if not admin_required():

        return jsonify({"ok": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}

    addr = str(data.get("address", "")).strip()

    if not addr:

        return jsonify({"ok": False, "error": "address required"}), 400

    with STATE_LOCK:

        BLOCKED.add(addr)

    return jsonify({"ok": True, "blocked": sorted(BLOCKED)})



@app.post("/api/admin/unblock")

def admin_unblock_wallet():

    if not admin_required():

        return jsonify({"ok": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}

    addr = str(data.get("address", "")).strip()

    with STATE_LOCK:

        BLOCKED.discard(addr)

    return jsonify({"ok": True, "blocked": sorted(BLOCKED)})



@app.post("/api/admin/send")

def admin_send_axo_stub():

    """

    Placeholder “send AXO” action. In this demo build we only validate inputs.

    Hook XRPL send logic here when you’re ready (server-side signing with VAULT_WALLET/WALLET_SEED).

    """

    if not admin_required():

        return jsonify({"ok": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}

    to_addr = str(data.get("to", "")).strip()

    amount  = int(data.get("amount", 0))

    if not to_addr or amount <= 0:

        return jsonify({"ok": False, "error": "to & positive amount required"}), 400

    # Return success stub for now.

    return jsonify({"ok": True, "tx": {"to": to_addr, "amount_axo": amount, "note": "stubbed"}})



# ------------------ Public API ------------------

def fetch_xrp_usd(timeout=4.0) -> float:

    """

    Best-effort XRP/USD via CoinGecko public API (no key). Free instances sometimes fail outbound fetches;

    we fail gracefully (return 0.0) and UI will still show AXO static pricing.

    """

    try:

        r = requests.get(

            "https://api.coingecko.com/api/v3/simple/price",

            params={"ids": "ripple", "vs_currencies": "usd"},

            timeout=timeout,

        )

        r.raise_for_status()

        data = r.json()

        return float(data.get("ripple", {}).get("usd", 0.0)) or 0.0

    except Exception:

        return 0.0



@app.get("/api/market")

def api_market():

    with STATE_LOCK:

        axo_usd = float(SETTINGS["axo_usd"])

    xrp_usd = fetch_xrp_usd()

    axo_per_xrp = (xrp_usd / axo_usd) if (axo_usd > 0 and xrp_usd > 0) else 0.0

    payload = {

        "axo_usd": round(axo_usd, 5),

        "xrp_usd": round(xrp_usd, 5),

        "axo_per_xrp": int(axo_per_xrp) if axo_per_xrp else 0,

        "source": "coingecko",

        "ts": int(time.time()),

    }

    # prevent caching

    resp = make_response(jsonify(payload))

    resp.headers["Cache-Control"] = "no-store"

    return resp



@app.post("/api/signup/prepare")

def api_signup_prepare():

    """

    Step 1: user submits wallet address.

    - Verify formatting (very light here).

    - Enforce blocklist & one-time signup per wallet.

    - Reserve the 1000 AXO (demo flag only).

    """

    data = request.get_json(silent=True) or {}

    addr = (data.get("address") or "").strip()

    if not addr.startswith("r") or len(addr) < 20:

        return jsonify({"ok": False, "error": "Invalid XRPL address"}), 400



    with STATE_LOCK:

        if addr in BLOCKED:

            return jsonify({"ok": False, "error": "Wallet blocked"}), 403

        if addr in ISSUED_WALLETS:

            return jsonify({"ok": False, "error": "Signup bonus already claimed"}), 409



    # In a real flow we’d set a server-side “session wallet” reservation.

    session["wallet"] = addr

    return jsonify({"ok": True})



@app.post("/api/signup/claim")

def api_signup_claim():

    """

    Step 3: claim signup bonus (requires trustline step to be done by user).

    - Enforces one-time per wallet.

    - Applies admin-configured amounts.

    - Handles referral payout logic (referrer address passed as 'ref').

    - XRPL payout logic is stubbed; returns a fake tx hash.

    """

    data = request.get_json(silent=True) or {}

    addr = (data.get("address") or "").strip()

    ref  = (data.get("ref") or "").strip()  # referral XRPL address



    if not addr or not addr.startswith("r"):

        return jsonify({"ok": False, "error": "address required"}), 400



    with STATE_LOCK:

        if addr in BLOCKED:

            return jsonify({"ok": False, "error": "Wallet blocked"}), 403

        if addr in ISSUED_WALLETS:

            return jsonify({"ok": False, "error": "Signup bonus already claimed"}), 409



        signup_amt   = int(SETTINGS["signup_bonus"])

        referral_amt = int(SETTINGS["referral_bonus"])

        require_tl   = bool(SETTINGS["require_trustline"])



    # TODO: verify trustline if require_tl (needs XRPL call). For demo we assume OK.



    # Mark as issued

    with STATE_LOCK:

        ISSUED_WALLETS.add(addr)



    # TODO: perform on-ledger send from VAULT_WALLET via WALLET_SEED (server-side signing).

    tx_signup  = {"to": addr, "amount_axo": signup_amt, "hash": "demo_tx_signup"}

    tx_ref     = None

    if ref and ref.startswith("r") and ref not in BLOCKED and ref != addr and referral_amt > 0:

        tx_ref = {"to": ref, "amount_axo": referral_amt, "hash": "demo_tx_ref"}



    return jsonify({"ok": True, "tx_signup": tx_signup, "tx_referral": tx_ref})



# ------------------ SPA catch-all ------------------

@app.errorhandler(404)

def not_found(_):

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catchall(unused=None):

    if unused and unused.startswith("api/"):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



# ------------------ Health ------------------

@app.get("/api/hello")

def api_hello():

    return jsonify({"message": "Hello from AXO API"})



# ------------------ Entrypoint ------------------

# Gunicorn will run "app" via your Procfile or render.yaml (no app.run() here).
