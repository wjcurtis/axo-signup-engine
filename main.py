import os

import time

import requests

from flask import Flask, send_from_directory, jsonify



# ------------------  FLASK APP  ------------------

app = Flask(__name__)



# ----------------  STATIC FRONTEND (SPA) ----------------

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



# SPA catch-alls

@app.errorhandler(404)

def not_found(_):

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catchall(unused=None):

    if unused and unused.startswith('api/'):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")



# ------------- SAMPLE API -------------

@app.route("/api/hello")

def api_hello():

    return jsonify({"message": "Hello from Flask API"})



# ------------- LIVE MARKET API -------------

# Config: set AXO price in USD (can override via env var on Render)

AXO_USD = float(os.getenv("AXO_USD", "0.01"))



# very tiny cache to avoid hammering the price API

_price_cache = {"ts": 0, "data": None}

CACHE_SECONDS = 45



def get_xrp_usd():

    """Fetch XRP/USD from CoinGecko (simple, no API key)."""

    # If cached and fresh, return it

    now = time.time()

    if _price_cache["data"] and now - _price_cache["ts"] < CACHE_SECONDS:

        return _price_cache["data"]



    url = "https://api.coingecko.com/api/v3/simple/price"

    params = {"ids": "ripple", "vs_currencies": "usd"}

    try:

        r = requests.get(url, params=params, timeout=8)

        r.raise_for_status()

        xrp_usd = float(r.json()["ripple"]["usd"])

        _price_cache["data"] = xrp_usd

        _price_cache["ts"] = now

        return xrp_usd

    except Exception as e:

        # If error and we had a previous value, serve it

        if _price_cache["data"]:

            return _price_cache["data"]

        # last resort default

        return 0.0



@app.route("/api/market")

def api_market():

    """

    Returns:

      {

        "xrp_usd": 3.29,

        "axo_usd": 0.01,

        "xrp_per_axo": 0.00304,

        "axo_per_xrp": 329.0,

        "source": "coingecko",

        "cached_seconds": 45

      }

    """

    xrp_usd = get_xrp_usd()

    axo_usd = AXO_USD

    axo_per_xrp = (xrp_usd / axo_usd) if (axo_usd and xrp_usd) else 0.0

    xrp_per_axo = (axo_usd / xrp_usd) if (axo_usd and xrp_usd) else 0.0

    return jsonify({

        "xrp_usd": round(xrp_usd, 6),

        "axo_usd": round(axo_usd, 6),

        "axo_per_xrp": round(axo_per_xrp, 6),

        "xrp_per_axo": round(xrp_per_axo, 6),

        "source": "coingecko",

        "cached_seconds": CACHE_SECONDS

    })
