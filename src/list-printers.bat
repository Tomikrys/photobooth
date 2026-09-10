@echo off
REM Lists all printers installed on this Windows machine.
REM Copy the exact printer name and paste it into PRINTER_NAME in your .env file.
echo Available printers (use the name exactly as shown):
echo ---
powershell -NoProfile -Command "Get-Printer | Select-Object -ExpandProperty Name"
echo ---
echo Default printer:
powershell -NoProfile -Command "(Get-CimInstance -Class Win32_Printer -Filter 'Default = True').Name"
pause
