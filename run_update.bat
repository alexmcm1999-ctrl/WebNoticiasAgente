@echo off
cd /d "%~dp0"
python scripts\check_local_model.py
python scripts\update_digest.py
pause
