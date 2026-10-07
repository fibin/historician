@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Install new libraries after an update (takes a couple of seconds if everything is there)
python -m pip install -q --disable-pip-version-check -r requirements.txt
python -m historian.web
pause
