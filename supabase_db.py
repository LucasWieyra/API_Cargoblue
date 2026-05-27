@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
py -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
pause
