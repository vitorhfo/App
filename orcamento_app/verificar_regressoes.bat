@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m unittest discover -p "test_*.py" -q
if errorlevel 1 (
  echo.
  echo FALHA: corrija os testes antes de considerar a alteração concluída.
  exit /b 1
)
echo.
echo Testes de regressão aprovados. Confira também PDFs e planilhas reais afetados.
exit /b 0
