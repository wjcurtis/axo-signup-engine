import os

import json

import time

import datetime

from urllib.request import urlopen, Request

from urllib.error import URLError, HTTPError



from flask import Flask, send_from_directory, jsonify



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



# Root -> dist/public/index.html

@app.route("/")

def serve_index():

    return send_from_directory(STATIC_ROOT, "index.html")



# Asset route -> dist/public/assets/*

@app.route("/assets/<path:filename>")

def serve_assets(filename: str):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)



# ----------------  SIMPLE APIs  ----------------

@app.route("/api/hello")

def api_hello():

    return jsonify({"message": "Hello from Flask API"})



@app.route("/api/health")

def api_health():

    return jsonify({"ok": True, "ts": int(time.time())})



# ---- Live price endpoint (no extra deps) ----

# AXO has a fixed USD price; override with env AXO_PRICE_USD if needed.

AXO_PRICE_USD = float(os.getenv("AXO_PRICE_USD", "0.01"))



# Tiny in‑memory cache so we don’t spam the upstream API

_price_cache = {

    "xrp_usd": None,

    "fetched_at": 0.0,

}



def _fetch_xrp_usd(timeout=5):

    """Fetch XRP/USD from CoinGecko (id=ripple). Returns float or raises."""

    url = "https://api.coingecko.com/api/v3/simple/price?ids=ripple&vs_currencies=usd"

    req = Request(url, headers={"User-Agent": "AXO/price-check"})

    with urlopen(req, timeout=timeout) as resp:

        data = json.loads(resp.read().decode("utf-8"))

    return float(data["ripple"]["usd"])



def _get_xrp_usd(ttl_seconds=60):

    """Get XRP price, using a short cache."""

    now = time.time()

    if _price_cache["xrp_usd"] is not None and (now - _price_cache["fetched_at"] < ttl_seconds):

        return _price_cache["xrp_usd"], True  # cache hit

    # refresh

    xrp = _fetch_xrp_usd()

    _price_cache["xrp_usd"] = xrp

    _price_cache["fetched_at"] = now

    return xrp, False  # cache miss



@app.route("/api/prices")

def api_prices():

    """Returns live XRP/USD, fixed AXO/USD, and computed AXO per 1 XRP."""

    cache_hit = False

    source = "coingecko"

    xrp_usd = None

    error = None

    try:

        xrp_usd, cache_hit = _get_xrp_usd(ttl_seconds=60)

    except (URLError, HTTPError, KeyError, ValueError) as e:

        # fall back to last known, or a conservative default

        error = str(e)

        if _price_cache["xrp_usd"] is not None:

            xrp_usd = _price_cache["xrp_usd"]

            source = "cache-fallback"

        else:

            xrp_usd = 0.50  # last‑ditch default

            source = "default-fallback"



    axo_usd = AXO_PRICE_USD

    # AXO per 1 XRP = XRP/USD divided by AXO/USD

    axo_per_xrp = xrp_usd / axo_usd if axo_usd > 0 else None



    return jsonify({

        "xrp_usd": round(xrp_usd, 6),

        "axo_usd": round(axo_usd, 6),

        "axo_per_xrp": None if axo_per_xrp is None else round(axo_per_xrp, 3),

        "last_updated_iso": datetime.datetime.utcfromtimestamp(_price_cache["fetched_at"]).isoformat() + "Z" if _price_cache["fetched_at"] else None,

        "cache": "hit" if cache_hit else "miss",

        "source": source,

        "error": error,

    })



# ----------------  SPA CATCH-ALL (must be last) ----------------

@app.errorhandler(404)

def not_found(_error):

    """Return index.html for any unknown path (SPA routing)."""

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catchall(unused=None):

    """Catch all non-API routes and serve SPA."""

    if unused and unused.startswith("api/"):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")
