@echo off
cd /d C:\FT8_Plus
pyinstaller --clean --onefile --noconsole ^
  --icon=logo.ico ^
  --add-data "logo.ico;." ^
  --add-data "zh_rCN.txt;." ^
  --version-file version.txt ^
  --name=FT8_Plus ^
  main.py
echo.
echo Build done: dist\FT8_Plus.exe
pause