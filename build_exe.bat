@echo off
REM Build IL-2 Campaign Tracker as EXE
REM 
REM Prerequisites:
REM   pip install pyinstaller pyyaml psutil

echo ====================================================================
echo IL-2 CAMPAIGN TRACKER - BUILD SCRIPT
echo ====================================================================
echo.

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>NUL
if errorlevel 1 (
    echo ERROR: PyInstaller not installed!
    echo.
    echo Please run: pip install pyinstaller
    echo.
    pause
    exit /b 1
)

echo [1/5] Checking required files...
if not exist "il2_tracker_launcher.py" (
    echo ERROR: il2_tracker_launcher.py not found!
    pause
    exit /b 1
)
if not exist "step1_extract_mission_dates.py" (
    echo ERROR: step1_extract_mission_dates.py not found!
    pause
    exit /b 1
)
if not exist "decode_campaing_usersave1.py" (
    echo ERROR: decode_campaing_usersave1.py not found!
    pause
    exit /b 1
)
if not exist "step3_generate_events.py" (
    echo ERROR: step3_generate_events.py not found!
    pause
    exit /b 1
)
if not exist "monitor_campaigns.py" (
    echo ERROR: monitor_campaigns.py not found!
    pause
    exit /b 1
)
if not exist "campaign_progress_config.yaml" (
    echo ERROR: campaign_progress_config.yaml not found!
    pause
    exit /b 1
)
if not exist "object_categories.yaml" (
    echo ERROR: object_categories.yaml not found!
    pause
    exit /b 1
)
if not exist "stock_campaigns.yaml" (
    echo ERROR: stock_campaigns.yaml not found!
    pause
    exit /b 1
)
if not exist "cleanup_failed_missions.py" (
    echo ERROR: cleanup_failed_missions.py not found!
    pause
    exit /b 1
)
if not exist "mlg2txt.py" (
    echo ERROR: mlg2txt.py not found!
    pause
    exit /b 1
)
if not exist "IL2_CampaignTracker.spec" (
    echo ERROR: IL2_CampaignTracker.spec not found!
    pause
    exit /b 1
)
if not exist "mlg2txt.spec" (
    echo ERROR: mlg2txt.spec not found!
    pause
    exit /b 1
)
echo OK
echo.

echo [2/5] Validating Python syntax...
setlocal enabledelayedexpansion

for %%F in (
		"il2_tracker_launcher.py"
		"step1_extract_mission_dates.py"
		"monitor_campaigns.py"
		"step3_generate_events.py"
		"decode_campaing_usersave1.py"
		"step4_process_mission_logs.py"
		"il2_mission_debrief.py"
		"mlg2txt.py"
		"country_validator_gui.py"
		"cleanup_failed_missions.py"
) do (
    if exist %%F (
        echo Testing %%F ...
        python -m py_compile %%F
        if errorlevel 1 (
            echo ---------------------------------------------------------
            echo ERROR: Syntax / Indentation problem in %%F
            echo Build aborted!
            echo ---------------------------------------------------------
            pause
            exit /b 1
        ) else (
            echo ✓ %%F OK
        )
    ) else (
        echo WARNING: File %%F not found!
    )
)

endlocal
echo.
echo ===============================================
echo   All files passed SYNTAX check successfully!
echo ===============================================
echo.

echo [3/5] Cleaning old build files...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
if exist "IL2_CampaignTracker.exe" del /q IL2_CampaignTracker.exe
if exist "mlg2txt.exe" del /q mlg2txt.exe
echo OK
echo.

echo [4/5] Building EXEs with PyInstaller...
echo This may take a few minutes...
echo.

REM Build main tracker EXE
echo Building IL2_CampaignTracker.exe...
pyinstaller IL2_CampaignTracker.spec
if errorlevel 1 (
    echo.
    echo ERROR: Build failed for IL2_CampaignTracker.exe!
    echo Check the error messages above.
    pause
    exit /b 1
)
echo ✓ IL2_CampaignTracker.exe built successfully
echo.

REM Build mlg2txt EXE
echo Building mlg2txt.exe...
pyinstaller mlg2txt.spec
if errorlevel 1 (
    echo.
    echo ERROR: Build failed for mlg2txt.exe!
    echo Check the error messages above.
    pause
    exit /b 1
)
echo ✓ mlg2txt.exe built successfully
echo OK
echo.

echo [5/5] Creating distribution package...
if not exist "IL2_Campaign_Tracker_v1.5" mkdir "IL2_Campaign_Tracker_v1.5"

REM Copy main EXE
copy "dist\IL2_CampaignTracker.exe" "IL2_Campaign_Tracker_v1.5\" >NUL
if errorlevel 1 (
    echo ERROR: Could not copy IL2_CampaignTracker.exe!
    pause
    exit /b 1
)

REM Copy mlg2txt EXE
copy "dist\mlg2txt.exe" "IL2_Campaign_Tracker_v1.5\" >NUL
if errorlevel 1 (
    echo ERROR: Could not copy mlg2txt.exe!
    pause
    exit /b 1
)

REM Copy config/objects (REQUIRED - external)
copy "campaign_progress_config.yaml" "IL2_Campaign_Tracker_v1.5\" >NUL
copy "object_categories.yaml" "IL2_Campaign_Tracker_v1.5\" >NUL
copy "stock_campaigns.yaml" "IL2_Campaign_Tracker_v1.5\" >NUL

REM Copy README if exists
if exist "README.md" copy "README.md" "IL2_Campaign_Tracker_v1.5\README.txt" >NUL

REM Create quick start guide
echo IL-2 CAMPAIGN PROGRESS TRACKER v1.5 > "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo. >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo QUICK START: >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo. >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo 1. Double-click IL2_CampaignTracker.exe >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo 2. Select your IL-2 installation folder >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo 3. Minimize the window and play IL-2! >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo. >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo The tracker will automatically update your campaigns. >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo. >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo REQUIREMENTS: >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo - IL-2 Sturmovik Great Battles series >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo - Rank/award images in IL-2\data\swf\CampaignRanksAwards\ >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo. >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo Download CampaignRanksAwards.zip from the GitHub repository >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo and extract to your IL-2 installation folder. >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo. >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo For detailed instructions, see README.txt >> "IL2_Campaign_Tracker_v1.5\QUICK_START.txt"
echo.
echo OK
echo.

echo ====================================================================
echo BUILD COMPLETE!
echo ====================================================================
echo.
echo Distribution package created in: IL2_Campaign_Tracker_v1.5\
echo.
echo Contents:
echo   - IL2_CampaignTracker.exe (~40 MB)
echo   - mlg2txt.exe (~10 MB)
echo   - Configuration files (*.yaml)
echo   - Documentation (README.txt, QUICK_START.txt)
echo.
echo IMPORTANT: Users must download CampaignRanksAwards.zip separately!
echo.
pause