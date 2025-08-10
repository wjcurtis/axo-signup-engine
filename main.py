import os, time, json, secrets, csv, io

from typing import Any, Dict, List

from flask import (

    Flask, send_from_directory, jsonify, request, make_response, render_template

)



# ------------------ APP & STATIC ------------------

app = Flask(__name__, template_folder="templates")



# dist/public/index.html & assets

STATIC_ROOT = os.path.join(os.getcwd(), "dist", "public")

INDEX_FILE = os.path.join(STATIC_ROOT, "index.html")



print("STATIC_ROOT =", STATIC_ROOT)

print("INDEX_FILE exists?", os.path.exists(INDEX_FILE))

if not os.path.exists(INDEX_FILE):

    raise RuntimeError("index.html not found at " + INDEX_FILE)



# ------------- SIMPLE IN-MEMORY STATE -------------

# Demo session storage (reset on service restart)

ADMIN_TOKENS: Dict[str, float] = {}            # token -> expires_at

ADMIN_SESSION_SECS = 60 * 60 * 6               # 6h

CONFIG: Dict[str, Any] = {

    "signup_bonus": 1000,

    "referral_reward": 300,

    "require_trustline": True,

    "whitelist": [],

    "signups_open": True,

}

SIGNUPS: List[Dict[str, Any]] = []             # demo list of recent signups



# ----------------- HELPER UTILS -------------------

def _now() -> float:

    return time.time()



def _clean_tokens():

    now = _now()

    expired = [t for t, exp in ADMIN_TOKENS.items() if exp <= now]

    for t in expired:

        ADMIN_TOKENS.pop(t, None)



def _issue_token() -> str:

    _clean_tokens()

    tok = secrets.token_urlsafe(32)

    ADMIN_TOKENS[tok] = _now() + ADMIN_SESSION_SECS

    return tok



def _require_admin(req) -> bool:

    _clean_tokens()

    auth = req.headers.get("Authorization", "")

    if not auth.startswith("Bearer "):

        return False

    tok = auth.split(" ", 1)[1].strip()

    exp = ADMIN_TOKENS.get(tok)

    return bool(exp and exp > _now())



def _fmt_bool(v: Any) -> bool:

    if isinstance(v, bool): return v

    if isinstance(v, str):

        return v.lower() in ("1", "true", "t", "yes", "y", "on")

    return bool(v)



# ----------------- FRONTEND ROUTES ----------------

@app.route("/")

def serve_index():

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/assets/<path:filename>")

def serve_assets(filename: str):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)



# Admin UI page

@app.route("/admin")

def admin_page():

    return render_template("admin.html")



# --------------- PUBLIC API (EXAMPLE) -------------

@app.route("/api/market")

def api_market():

    # Keep simple: return zeros + timestamp (UI still renders)

    return jsonify({

        "axo_per_xrp": 0.0,

        "axo_usd": 0.0,

        "xrp_usd": 0.0,

        "source": "demo",

        "ts": int(_now())

    })



# --------------- ADMIN AUTH & CONFIG --------------

@app.route("/api/admin/login", methods=["POST"])

def admin_login():

    body = request.get_json(silent=True) or {}

    pin = (body.get("pin") or "").strip()

    required = os.environ.get("ADMIN_PIN", "")

    if not required:

        return jsonify({"error": "ADMIN_PIN not set on server"}), 500

    if not pin or pin != required:

        return jsonify({"error": "Invalid PIN"}), 401

    tok = _issue_token()

    return jsonify({"token": tok})



@app.route("/api/admin/config", methods=["GET", "POST"])

def admin_config():

    if not _require_admin(request):

        return jsonify({"error": "unauthorized"}), 401



    if request.method == "GET":

        return jsonify(CONFIG)



    # POST save

    body = request.get_json(silent=True) or {}

    try:

        if "signup_bonus" in body:

            CONFIG["signup_bonus"] = int(body["signup_bonus"])

        if "referral_reward" in body:

            CONFIG["referral_reward"] = int(body["referral_reward"])

        if "require_trustline" in body:

            CONFIG["require_trustline"] = _fmt_bool(body["require_trustline"])

        if "whitelist" in body:

            wl = body["whitelist"] or []

            CONFIG["whitelist"] = [str(x).strip() for x in wl if str(x).strip()]

    except Exception as e:

        return jsonify({"error": f"bad config: {e}"}), 400

    return jsonify({"ok": True, "config": CONFIG})



@app.route("/api/admin/actions", methods=["POST"])

def admin_actions():

    if not _require_admin(request):

        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}

    action = (body.get("action") or "").strip()



    if action == "refresh_market":

        return jsonify({"ok": True, "message": "market refresh queued"})

    if action == "toggle_signups":

        CONFIG["signups_open"] = not CONFIG.get("signups_open", True)

        return jsonify({"ok": True, "signups_open": CONFIG["signups_open"]})



    return jsonify({"error": "unknown action"}), 400



@app.route("/api/admin/signups")

def admin_signups():

    if not _require_admin(request):

        return jsonify({"error": "unauthorized"}), 401

    limit = max(1, min(int(request.args.get("limit", 50)), 500))

    rows = SIGNUPS[-limit:]

    return jsonify(rows[::-1])  # newest first



@app.route("/api/admin/export.csv")

def admin_export_csv():

    token = request.args.get("token", "")

    ok_header = _require_admin(request)

    ok_query = token and token in ADMIN_TOKENS and ADMIN_TOKENS[token] > _now()

    if not (ok_header or ok_query):

        return jsonify({"error": "unauthorized"}), 401



    output = io.StringIO()

    w = csv.writer(output)

    w.writerow(["ts", "wallet", "ref", "bonus", "status"])

    for r in SIGNUPS:

        w.writerow([r.get("ts",""), r.get("wallet",""), r.get("ref",""),

                    r.get("bonus",""), r.get("status","")])

    resp = make_response(output.getvalue())

    resp.headers["Content-Type"] = "text/csv"

    resp.headers["Content-Disposition"] = "attachment; filename=axo_signups.csv"

    return resp



# ----------- SPA catch-all --------

@app.errorhandler(404)

def not_found(_err):

    return send_from_directory(STATIC_ROOT, "index.html")



@app.route("/<path:unused>")

def spa_catchall(unused=None):

    if unused and unused.startswith("api/"):

        return jsonify({"error": "API endpoint not found"}), 404

    return send_from_directory(STATIC_ROOT, "index.html")
