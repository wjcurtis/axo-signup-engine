# main.py — AXO Utility Hub (Flask + SPA + Market API)

import os, time, json

from typing import Any, Dict

from flask import Flask, send_from_directory, jsonify, make_response, request



# ------------------  FLASK APP  ------------------

app = Flask(__name__)



# ----------------  STATIC FRONTEND (SPA) ----------------

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



# SPA fallback for any non-API 404s

@app.errorhandler(404)

def _spa_on_404(_):

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catchall(unused: str):

    if unused.startswith("api/"):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



# -------------------  SIMPLE APIS -------------------

@app.route("/api/hello")

def api_hello():

    return jsonify({"message": "Hello from Flask API"})



# /api/market — live XRP price (USD), fixed AXO price (USD), and AXO per XRP

# Uses a tiny in-memory cache to avoid rate limits; refreshes every 60s.

_AXO_USD = 0.01  # your fixed AXO price

_cache: Dict[str, Any] = {"ts": 0, "xrp_usd": None}



def _get_xrp_usd() -> float:

    # refresh every 60 seconds

    if time.time() - (_cache["ts"] or 0) < 60 and _cache["xrp_usd"] is not None:

        return _cache["xrp_usd"]



    import requests  # listed in requirements.txt

    try:

        # CoinGecko public endpoint (no API key)

        url = "https://api.coingecko.com/api/v3/simple/price"

        resp = requests.get(url, params={"ids": "ripple", "vs_currencies": "usd"}, timeout=6)

        data = resp.json()

        xrp = float(data.get("ripple", {}).get("usd", 0.0))

        if xrp > 0:

            _cache["xrp_usd"] = xrp

            _cache["ts"] = time.time()

            return xrp

    except Exception as e:

        print("xrp fetch error:", e)

    # fallback to last known or 0

    return float(_cache["xrp_usd"] or 0.0)



@app.route("/api/market")

def api_market():

    xrp_usd = _get_xrp_usd()

    axo_usd = _AXO_USD

    axo_per_xrp = (xrp_usd / axo_usd) if axo_usd > 0 else 0.0



    payload = {

        "axo_usd": round(axo_usd, 4),

        "xrp_usd": round(xrp_usd, 6),

        "axo_per_xrp": round(axo_per_xrp, 6),

        "source": "coingecko",

        "cached_seconds": int(time.time() - (_cache["ts"] or 0)) if _cache["ts"] else None,

        "ts": int(time.time()),

    }

    res = make_response(jsonify(payload))

    # Tell browsers not to cache this (your script already requests no-store)

    res.headers["Cache-Control"] = "no-store, max-age=0"

    # Basic CORS so your SPA can fetch from same origin (and future subpaths)

    res.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")

    res.headers["Vary"] = "Origin"

    return res



# No app.run() — gunicorn runs via Procfile/run_flask.py on Render
