@echo off
title Importador Estoque - Loop Horario
set PASTA=C:\Users\Marcos\Desktop\ImportadorEstoque
set PYTHON=C:\Users\Marcos\AppData\Local\Microsoft\WindowsApps\python.exe

:loop
echo [%DATE% %TIME%] Iniciando importacao...
"%PYTHON%" "%PASTA%\auto_importador.py"
echo [%DATE% %TIME%] Aguardando 1 hora...
timeout /t 3600 /nobreak > nul
goto loop
