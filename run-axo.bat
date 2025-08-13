@echo off

setlocal ENABLEEXTENSIONS

title AXO Local Runner

echo.

echo === AXO Local Runner ===



REM 1) Go to this script's folder

pushd "%~dp0"



REM 2) Find Python

set "PY="

where py >nul 2>nul && set "PY=py -3"

if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (

  echo [ERROR] Python is not installed or not on PATH.

  echo         Install from https://www.python.org/downloads/ (check "Add Python to PATH") and re-run.

  pause

  exit /b 1

)



REM 3) Create virtual env if missing

if not exist "venv\Scripts\activate" (

  echo Creating virtual environment...

  %PY% -m venv venv || (

    echo [ERROR] Failed to create virtual environment.

    pause

    exit /b 1

  )

)



REM 4) Activate venv

call "venv\Scripts\activate"



REM 5) Install dependencies

if exist "requirements.txt" (

  echo Installing requirements...

  pip install -r requirements.txt

) else (

  echo requirements.txt not found. Installing minimal deps...

  pip install flask flask-cors requests python-dotenv

)



REM 6) Set environment variables for this session

set "FLASK_APP=main.py"

set "FLASK_ENV=development"

set "ADMIN_PIN=Ax0app112677"

set "AXO_PRICE=0.01"

set "WALLET_SEED=sEdVYyXEyHgXc5smtpvTNWvc3tPQ9Ve"

set "XRP_VAULT_ADDR=rwBDmYfuDXAhwZomUaNNZyNMbtxbUQUdW2"

set "FLASK_SECRET_KEY=flaskaxo112677"



REM 7) Launch app

if exist "run_flask.py" (

  echo Starting via run_flask.py ...

  python run_flask.py

) else (

  echo Starting via main.py ...

  python main.py

)



REM 8) Cleanup folder stack and keep window open

popd

echo.

echo (Press any key to close)

pause >nul