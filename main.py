import os

from flask import Flask, send_from_directory, jsonify



# ------------------  FLASK APP  ------------------

app = Flask(__name__)



# ----------------  STATIC FRONTEND (SPA) ----------------

# Use absolute paths so behavior is identical no matter how Replit starts the app

# expects: dist/public/index.html and dist/public/assets/*

STATIC_ROOT = os.path.join(os.getcwd(), "dist", "public")

INDEX_FILE = os.path.join(STATIC_ROOT, "index.html")



# Helpful logs so we can diagnose "Not Found" quickly

print("STATIC_ROOT =", STATIC_ROOT)

print("INDEX_FILE =", INDEX_FILE, "exists?", os.path.exists(INDEX_FILE))



if not os.path.exists(INDEX_FILE):

    raise RuntimeError("index.html not found at " + INDEX_FILE)



# Root route -> dist/public/index.html

@app.route("/")

def serve_index():

    return send_from_directory(STATIC_ROOT, "index.html")



# Asset route -> dist/public/assets/*

@app.route("/assets/<path:filename>")

def serve_assets(filename: str):

    return send_from_directory(os.path.join(STATIC_ROOT, "assets"), filename)



# SPA catch-all for client-side routes (must be LAST)
@app.errorhandler(404)
def not_found(error):
    """Return index.html for any 404 (SPA routing)"""
    return send_from_directory(STATIC_ROOT, "index.html")

@app.route("/<path:unused>")
def spa_catchall(unused=None):
    """Catch all non-API routes and serve SPA"""
    # Check if it's an API route - if so, return proper 404
    if unused and unused.startswith('api/'):
        return jsonify({"error": "API endpoint not found"}), 404
    
    # For all other routes, serve the SPA
    return send_from_directory(STATIC_ROOT, "index.html")



# ------------- (OPTIONAL) SAMPLE API -------------

@app.route("/api/hello")

def api_hello():

    return jsonify({"message": "Hello from Flask API"})



# -------------------  RUN  -------------------

# We let Replit handle the entrypoint via run_flask.py, so no app.run() here.

# (app.run() is called from run_flask.py with the required host/port)