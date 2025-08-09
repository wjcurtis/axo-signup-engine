
# Deploy AXO Flask + SPA on Render (All-in-One)



## Files in this pack

- requirements.txt  -> Python deps (Flask + Gunicorn)

- Procfile          -> Start command for Render

- render.yaml       -> Optional one-click config

- dist/public/...   -> Your SPA build (index.html + assets)

- main.py           -> Your Flask app (must export "app" and NOT call app.run)



## Render steps

1) Push this project to GitHub (or create a repo and upload these files).

2) Go to https://render.com → New → Web Service → Connect repo.

3) Runtime: Python

4) Build Command: pip install -r requirements.txt

5) Start Command: gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT main:app

6) Click Create Web Service and wait ~1–2 minutes.



## Verify

- https://<your-app>.onrender.com/          → SPA (HTTP 200)

- https://<your-app>.onrender.com/api/hello → JSON (HTTP 200)



## Notes

- main.py should define:

    app = Flask(__name__)

    # serve dist/public/index.html at "/"

    # serve /assets/* from dist/public/assets

    # optional catch-all returns index.html for SPA routing

    # /api/hello returns test JSON

- Do NOT call app.run(...) in main.py; Gunicorn handles serving.

- Put secrets (vault keys, admin pins) in Render → Environment variables.

