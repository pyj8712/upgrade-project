@echo off
chcp 65001 >nul
cd /d "C:\Users\yujin\OneDrive\Desktop\claude\rename-tax-invoices"

pip show PyMuPDF >nul 2>&1 || pip install PyMuPDF
pip show winsdk >nul 2>&1 || pip install winsdk

python orchestrator.py
pause
