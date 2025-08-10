# main.py — AXO Utility Hub (Flask + SPA + Admin)

import os

import json

import time

import hashlib

from typing import Any, Dict

from flask import (

    Flask, send_from_directory, jsonify, request, make_response,

    render_template, abort

)

import requests



# ------------------ App ------------------

app = Flask(__name__, template_folder="templates")



# ------------------ Static Frontend (SPA) ------------------

# expects: dist/public/index.html and dist/public/assets/*

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



# SPA catch-all for client routes

@app.errorhandler(404)

def not_found(_):

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catchall(unused=None):

    if unused and unused.startswith("api/"):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



# ------------------ Simple in‑memory settings (demo) ------------------

SETTINGS: Dict[str, Any] = {

    "signup_bonus": 1000,     # AXO

    "referral_reward": 300,   # AXO

    "require_trustline": True

}

# Static price for AXO in USD (can override via env)

AXO_PRICE_USD = float(os.getenv("AXO_PRICE_USD", "0.01"))



# ------------------ Market API ------------------

# Returns live XRP price from CoinGecko and static AXO price (0.01)

@app.route("/api/market")

def market():

    xrp_usd = 0.0

    try:

        r = requests.get(

            "https://api.coingecko.com/api/v3/simple/price",

            params={"ids": "ripple", "vs_currencies": "usd"},

            timeout=8,

        )

        if r.ok:

            xrp_usd = float(r.json().get("ripple", {}).get("usd", 0) or 0.0)

    except Exception:

        xrp_usd = 0.0



    axo_usd = AXO_PRICE_USD

    # How many AXO per 1 XRP at static AXO=$0.01

    axo_per_xrp = (xrp_usd / axo_usd) if (axo_usd > 0) else 0.0



    return jsonify({

        "axo_usd": round(axo_usd, 6),

        "xrp_usd": round(xrp_usd, 6),

        "axo_per_xrp": round(axo_per_xrp, 6),

        "source": "coingecko",

        "ts": int(time.time()),

        "cached_seconds": None

    })



# ------------------ Admin auth helpers ------------------

ADMIN_PIN = os.getenv("ADMIN_PIN", "").strip()

COOKIE_NAME = "axo_admin"



def _pin_ok(pin: str) -> bool:

    if not ADMIN_PIN:

        return False

    return pin == ADMIN_PIN



def _has_admin_cookie(req) -> bool:

    token = req.cookies.get(COOKIE_NAME, "")

    if not token or not ADMIN_PIN:

        return False

    # simple HMAC-ish check

    expect = hashlib.sha256(("ok:" + ADMIN_PIN).encode()).hexdigest()

    return token == expect



def _make_admin_cookie(resp):

    val = hashlib.sha256(("ok:" + ADMIN_PIN).encode()).hexdigest()

    resp.set_cookie(

        COOKIE_NAME, val, httponly=True, secure=True, samesite="Lax", max_age=86400

    )

    return resp



# ------------------ Admin routes ------------------

@app.route("/admin")

def admin_page():

    # Always render the template; it will show the PIN prompt if not authed

    return render_template("admin.html")



@app.post("/api/admin/login")

def admin_login():

    data = request.get_json(silent=True) or {}

    pin = (data.get("pin") or "").strip()

    if not _pin_ok(pin):

        return jsonify({"ok": False, "error": "Invalid PIN"}), 401

    resp = make_response(jsonify({"ok": True}))

    return _make_admin_cookie(resp)



@app.get("/api/admin/config")

def admin_get_config():

    if not _has_admin_cookie(request):

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    return jsonify({"ok": True, "data": SETTINGS})



@app.post("/api/admin/config")

def admin_set_config():

    if not _has_admin_cookie(request):

        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    # Only allow known keys

    for k in ("signup_bonus", "referral_reward", "require_trustline"):

        if k in data:

            SETTINGS[k] = data[k]

    return jsonify({"ok": True, "data": SETTINGS})



# ------------------ (Notes for the vault + fee logic) ------------------

# The .25 XRP fee → you’ll set FEE_XRP=0.25 and XRPL_VAULT_ADDR in Render.

# Business rules (XRP stays in vault, AXO payouts only) will be enforced in

# future endpoints (/api/claim, /api/purchase, etc.). This demo keeps UI/Admin

# working while we wire those secure flows next.



# ------------------ End ------------------
