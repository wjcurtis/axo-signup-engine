# main.py — AXO Utility Hub (Flask + SPA + Admin)

import os, json, time, csv, io, threading

from pathlib import Path

from typing import Any, Dict

from flask import (

    Flask, request, jsonify, send_from_directory, session,

    render_template, make_response, abort

)

import requests



# ---------- Config & App ----------

ROOT = Path(__file__).resolve().parent

DATA_DIR = ROOT / "data"

DATA_DIR.mkdir(exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"



DEFAULT_CONFIG = {

    "signup_bonus": 1000,

    "referral_bonus": 300,

    "require_trustline": True,

    "banner": ""

}



def load_config() -> Dict[str, Any]:

    if CONFIG_FILE.exists():

        try:

            with CONFIG_FILE.open("r", encoding="utf-8") as f:

                cfg = json.load(f)

                return {**DEFAULT_CONFIG, **cfg}

        except Exception:

            pass

    save_config(DEFAULT_CONFIG)

    return DEFAULT_CONFIG.copy()



def save_config(cfg: Dict[str, Any]) -> None:

    with CONFIG_FILE.open("w", encoding="utf-8") as f:

        json.dump(cfg, f, indent=2)



CONFIG = load_config()



ADMIN_PIN = os.environ.get("ADMIN_PIN", "").strip()

SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32).hex())



app = Flask(

    __name__,

    static_folder=str(ROOT / "dist" / "public"),

    static_url_path="/"

)

app.secret_key = SECRET_KEY



# ---------- SPA Routes ----------

STATIC_ROOT = app.static_folder  # dist/public

INDEX_FILE = "index.html"



@app.route("/")

def spa_root():

    return send_from_directory(STATIC_ROOT, INDEX_FILE)



@app.route("/assets/<path:filename>")

def assets(filename):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)



# catch-all: serve SPA (except API & admin)

@app.errorhandler(404)

def spa_404(_):

    path = request.path.lstrip("/")

    if path.startswith("api/") or path.startswith("admin"):

        return jsonify({"error": "Not found"}), 404

    return send_from_directory(STATIC_ROOT, INDEX_FILE)



# ---------- Market (demo: XRP live via CoinGecko; AXO static unless you wire price feed) ----------

_last_market = {"t": 0, "data": {"axo_usd": 0.01, "xrp_usd": 0.00, "axo_per_xrp": 0.0}}



def fetch_xrp_usd() -> float:

    try:

        r = requests.get(

            "https://api.coingecko.com/api/v3/simple/price",

            params={"ids": "ripple", "vs_currencies": "usd"},

            timeout=6,

        )

        r.raise_for_status()

        return float(r.json().get("ripple", {}).get("usd", 0.0))

    except Exception:

        return 0.0



@app.route("/api/market")

def api_market():

    # simple 30s cache to keep free tier happy

    now = time.time()

    if now - _last_market["t"] > 30:

        xrp = fetch_xrp_usd()

        axo = float(_last_market["data"]["axo_usd"])  # keep demo static or replace with your oracle

        axo_per_xrp = round((xrp / axo), 3) if axo > 0 and xrp > 0 else 0.0

        _last_market["t"] = now

        _last_market["data"] = {

            "axo_usd": axo,

            "xrp_usd": xrp,

            "axo_per_xrp": axo_per_xrp,

        }

    return jsonify({**_last_market["data"], "source": "coingecko", "ts": int(_last_market["t"])})



# ---------- Admin helpers ----------

def is_admin() -> bool:

    return bool(session.get("is_admin") is True)



@app.route("/api/admin/me")

def admin_me():

    return jsonify({"admin": is_admin()})



@app.route("/api/admin/login", methods=["POST"])

def admin_login():

    if not ADMIN_PIN:

        return jsonify({"ok": False, "error": "ADMIN_PIN not set on server"}), 403

    data = request.get_json(silent=True) or {}

    pin = str(data.get("pin", "")).strip()

    if pin and pin == ADMIN_PIN:

        session["is_admin"] = True

        return jsonify({"ok": True})

    return jsonify({"ok": False, "error": "Invalid PIN"}), 401



@app.route("/api/admin/logout", methods=["POST"])

def admin_logout():

    session.clear()

    return jsonify({"ok": True})



def require_admin():

    if not is_admin():

        abort(401)



@app.route("/admin")

def admin_page():

    # Render a template (PIN handled client-side via /api/admin/me)

    return render_template("admin.html")



# ---------- Admin: Config ----------

@app.route("/api/admin/config", methods=["GET", "POST"])

def admin_config():

    if request.method == "GET":

        return jsonify(CONFIG)

    # POST

    require_admin()

    data = request.get_json(silent=True) or {}

    new_cfg = CONFIG.copy()

    if "signup_bonus" in data:       new_cfg["signup_bonus"] = int(data["signup_bonus"])

    if "referral_bonus" in data:     new_cfg["referral_bonus"] = int(data["referral_bonus"])

    if "require_trustline" in data:  new_cfg["require_trustline"] = bool(data["require_trustline"])

    if "banner" in data:             new_cfg["banner"] = str(data["banner"])

    save_config(new_cfg)

    CONFIG.update(new_cfg)

    return jsonify({"ok": True, "config": CONFIG})



# ---------- Admin: CSV export (stub demo data) ----------

@app.route("/api/admin/export")

def admin_export():

    require_admin()

    # Replace this with your real datastore

    rows = [

        {"timestamp": int(time.time())-3600, "xrpl": "rEXAMPLE1", "ref": "", "awarded": False},

        {"timestamp": int(time.time())-120, "xrpl": "rEXAMPLE2", "ref": "rREFERRER", "awarded": True},

    ]

    out = io.StringIO()

    w = csv.DictWriter(out, fieldnames=["timestamp", "xrpl", "ref", "awarded"])

    w.writeheader()

    for r in rows: w.writerow(r)

    resp = make_response(out.getvalue())

    resp.headers["Content-Type"] = "text/csv"

    resp.headers["Content-Disposition"] = 'attachment; filename="signups.csv"'

    return resp



# ---------- Admin: Cache refresh (no-op for demo) ----------

@app.route("/api/admin/rebuild-cache", methods=["POST"])

def rebuild_cache():

    require_admin()

    # Put any warming tasks you need here

    def _warm():

        try: fetch_xrp_usd()

        except Exception: pass

    threading.Thread(target=_warm, daemon=True).start()

    return jsonify({"ok": True})



# ---------- API examples for UI buttons (stubs) ----------

@app.route("/api/signup", methods=["POST"])

def api_signup():

    # Validate and store signup (stub)

    body = request.get_json(silent=True) or {}

    # TODO: verify XRPL address & referral, gate trustline, etc.

    return jsonify({"ok": True, "message": "Signup recorded (demo).", "config": CONFIG})



@app.route("/api/claim-bonus", methods=["POST"])

def api_claim():

    # TODO: validate wallet, trustline, pay bonus using your on-ledger service

    return jsonify({"ok": True, "awarded": CONFIG["signup_bonus"]})



# ---------- Health ----------

@app.route("/api/hello")

def api_hello():

    return jsonify({"message": "Hello from AXO backend"})



# End of file
