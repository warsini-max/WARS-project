@echo off
REM WARS Scanner - jalankan aplikasi di Windows (klik dua kali file ini).
REM Pertama kali: membuat lingkungan Python (.venv) dan memasang paket (beberapa menit).
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto nopython

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Membuat lingkungan Python...
    %PY% -m venv .venv || goto fail
)
echo [2/3] Memasang paket (sekali saja; berikutnya cepat)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-lock.txt || goto fail

echo [3/3] Menjalankan aplikasi. Browser akan terbuka di http://localhost:8501
echo       Untuk berhenti: tutup jendela ini.
start "" cmd /c "timeout /t 8 >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --browser.gatherUsageStats false
goto end

:nopython
echo.
echo Python belum terpasang. Pasang Python 3.13 dari https://www.python.org/downloads/windows/
echo dan centang "Add python.exe to PATH" saat instalasi, lalu jalankan file ini lagi.
pause
goto end

:fail
echo.
echo Instalasi atau menjalankan aplikasi gagal. Salin pesan di atas dan kirim ke Claude.
pause

:end
