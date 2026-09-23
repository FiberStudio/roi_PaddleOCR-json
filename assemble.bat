@echo off
setlocal
rem ============================================================
rem  Region OCR plugin - engine assembly script
rem  Copies ONLY the PaddleOCR-json ENGINE files: exe, models,
rem  dlls, from the official Paddle plugin folder into this
rem  plugin folder. Plugin control files are NEVER overwritten.
rem  NOTE: an old version of this script copied everything and
rem  overwrote the plugin control files. If you ran that version,
rem  delete this folder and re-copy the clean plugin first.
rem ============================================================

set "TARGET=%~dp0"
set "SRC=%TARGET%..\win7_x64_PaddleOCR-json"

echo ============================================
echo   Region OCR plugin - Engine Assembly
echo ============================================

if exist "%TARGET%PPOCR_umi.py" goto damaged
if exist "%TARGET%PaddleOCR-json.exe" goto have_engine
if exist "%SRC%\PaddleOCR-json.exe" goto copy_engine
goto manual

:damaged
echo [WARN] Detected official plugin control files: PPOCR_umi.py
echo        This happens when an OLD assemble.bat copied everything over.
echo        Please delete this folder and re-copy the CLEAN plugin folder,
echo        then run this script again.
goto done

:have_engine
echo [OK] Engine files already exist in this plugin folder.
goto check

:copy_engine
echo [Info] Official Paddle plugin folder found: %SRC%
echo [Info] Copying engine files ONLY: exe, models, dll ...
xcopy /I /Y "%SRC%\PaddleOCR-json.exe" "%TARGET%" >nul
xcopy /E /I /Y "%SRC%\models" "%TARGET%models" >nul
xcopy /Y "%SRC%\*.dll" "%TARGET%" >nul
echo [OK] Copy finished.
goto check

:manual
echo [Error] Official Paddle plugin folder NOT found: %SRC%
echo.
echo Please assemble the engine manually:
echo   1. Download  win7_x64_PaddleOCR-json_*.7z  from:
echo        https://github.com/hiroi-sora/Umi-OCR_plugins/releases
echo   2. Extract it, then copy ONLY the engine files
echo      - PaddleOCR-json.exe
echo      - models folder
echo      - all *.dll files
echo      into this plugin folder:
echo        %TARGET%
echo   3. Do NOT copy __init__.py / PPOCR_umi.py / PPOCR_config.py
echo      from the official folder - they belong to the official
echo      plugin and would overwrite this plugin's control files.
goto check

:check
if exist "%TARGET%PaddleOCR-json.exe" goto ready
echo [Error] PaddleOCR-json.exe still not found. Please check.
goto done

:ready
echo [OK] Engine ready: %TARGET%PaddleOCR-json.exe
echo [Info] You may now restart Umi-OCR and select the
echo        "Region OCR" plugin in global settings.

:done
echo.
pause
