#!/usr/bin/env python3
"""
IL-2 Campaign Progress Tracker - Unified Launcher
Version: 1.1

Single executable that:
1. First run: GUI to select game directory
2. Extracts mission dates
3. Decodes save file
4. Mission cleanup check (new in v1.1)
5. Generates events
6. Monitors for changes
7. Auto-exits when IL-2 closes (optional)

For EXE packaging with external campaign_progress_config.yaml
"""

import sys
import os
import time
from pathlib import Path

# Determine script directory (works for both script and EXE)
if getattr(sys, 'frozen', False):
    # Running as EXE
    SCRIPT_DIR = Path(sys.executable).parent
else:
    # Running as script
    SCRIPT_DIR = Path(__file__).parent

# Add to path for imports
sys.path.insert(0, str(SCRIPT_DIR))

print("="*70)
print("IL-2 CAMPAIGN PROGRESS TRACKER v1.1")
print("="*70)
print()

# Check for required config file
CONFIG_FILE = SCRIPT_DIR / "campaign_progress_config.yaml"
if not CONFIG_FILE.exists():
    print("ERROR: campaign_progress_config.yaml not found!")
    print(f"Expected location: {CONFIG_FILE}")
    print()
    print("Please place campaign_progress_config.yaml in the same folder")
    print("as this executable.")
    print()
    input("Press Enter to exit...")
    sys.exit(1)

# Import modules (must be in same directory or packaged with EXE)
try:
    # Change to script directory
    os.chdir(SCRIPT_DIR)
    
    # Run step 1 if first time
    MISSION_DATES_FILE = SCRIPT_DIR / "campaign_mission_dates.json"
    
    if not MISSION_DATES_FILE.exists():
        print("FIRST RUN SETUP")
        print("="*70)
        print()
        
        # Import and run step 1
        import step1_extract_mission_dates
        step1_extract_mission_dates.main()
        
        if not MISSION_DATES_FILE.exists():
            print()
            print("ERROR: Setup incomplete. Mission dates not created.")
            input("Press Enter to exit...")
            sys.exit(1)
        
        # NEW: Show country validation GUI
        print()
        print("="*70)
        print("COUNTRY VALIDATION")
        print("="*70)
        print()
        print("Please verify the automatically detected countries...")
        print()
        print("[DEBUG] About to show GUI...")
        print(f"[DEBUG] Mission dates file: {MISSION_DATES_FILE}")
        print(f"[DEBUG] File exists: {MISSION_DATES_FILE.exists()}")
        
        try:
            print("[DEBUG] Importing country_validator_gui...")
            from country_validator_gui import validate_countries
            print("[DEBUG] Import successful!")
            print("[DEBUG] Calling validate_countries()...")
            
            result = validate_countries(str(MISSION_DATES_FILE))
            
            print(f"[DEBUG] validate_countries returned: {result}")
            
            if not result:
                print()
                print("Country validation was cancelled.")
                print("You can manually edit campaign_mission_dates.json")
                print("or restart the tracker to validate again.")
                print()
                input("Press Enter to continue anyway...")
        except Exception as e:
            print(f"[DEBUG] Exception: {type(e).__name__}: {e}")
            print(f"Warning: Could not show country validation GUI: {e}")
            print("You can manually edit campaign_mission_dates.json")
            print()
            import traceback
            traceback.print_exc()
            print()
            input("Press Enter to continue...")
    
    # ========================================================================
    # INITIAL PROCESSING
    # ========================================================================
    
    # Initial processing (only if save file exists)
    campaignsstates = SCRIPT_DIR / "campaignsstates.txt"
    
    # Try to find save file in IL-2 directory if not local
    if not campaignsstates.exists():
        print()
        print("Looking for campaignsstates.txt...")
        
        # Load game directory from mission dates
        import json
        try:
            with open(MISSION_DATES_FILE, 'r') as f:
                data = json.load(f)
                game_dir = Path(data.get('game_directory', ''))
                
            if game_dir:
                save_base = game_dir / "data" / "swf" / "il2" / "usersave"
                if save_base.exists():
                    uuid_folders = [f for f in save_base.iterdir() if f.is_dir()]
                    if uuid_folders:
                        save_file = uuid_folders[0] / "campaign" / "campaignsstates.txt"
                        if save_file.exists():
                            print(f"Found: {save_file}")
                            # Copy to local directory
                            import shutil
                            shutil.copy(save_file, campaignsstates)
                            print(f"Copied to: {campaignsstates}")
        except:
            pass
    
    if campaignsstates.exists():
        print()
        print("INITIAL PROCESSING")
        print("="*70)
        
        # Decode save file
        try:
            # Delete old decoded file if it exists
            old_decoded = SCRIPT_DIR / "campaigns_decoded.json"
            if old_decoded.exists():
                print(f"Removing old decoded file...")
                old_decoded.unlink()
            
            import decode_campaing_usersave1
            print("Decoding save file...")
            if hasattr(decode_campaing_usersave1, 'main'):
                decode_campaing_usersave1.main()
                
                # DEBUG: Check what was created
                import json
                decoded_file = SCRIPT_DIR / "campaigns_decoded.json"
                if decoded_file.exists():
                    with open(decoded_file) as f:
                        data = json.load(f)
                    if 'kerch' in data:
                        kerch_stats = data['kerch'].get('characterStatisticsByFileName', {})
                        print(f"DEBUG: Kerch stats keys: {list(kerch_stats.keys())[:5]}")
                        if kerch_stats:
                            first_key = list(kerch_stats.keys())[0]
                            first_val = kerch_stats[first_key]
                            print(f"DEBUG: '{first_key}' = {type(first_val)}")
                else:
                    print("ERROR: campaigns_decoded.json was not created!")
            else:
                # Old version - try to use it anyway
                print("Warning: Using legacy decoder")
        except Exception as e:
            print(f"Warning: Decoder error: {e}")
            import traceback
            traceback.print_exc()
        
        # Generate events  
        try:
            import step3_generate_events
            print("Generating events...")
            step3_generate_events.main()
        except Exception as e:
            print(f"Warning: Event generation error: {e}")
            import traceback
            traceback.print_exc()
    else:
        print()
        print("Note: campaignsstates.txt not found yet.")
        print("The tracker will watch for it and process when available.")
        print()
        print("To manually add save file:")
        print(f"  Copy campaignsstates.txt to: {SCRIPT_DIR}")
        print(f"  Then restart this program.")
    
    # ========================================================================
    # MISSION CLEANUP CHECK (New in v1.1)
    # ========================================================================
    # Now we run cleanup AFTER initial processing so campaigns_decoded.json exists
    
    print()
    print("="*70)
    print("CHECKING FOR UNSUCCESSFUL MISSIONS")
    print("="*70)
    print()
    
    try:
        from cleanup_failed_missions import startup_cleanup_check
        
        # This will:
        # 1. Scan all campaigns
        # 2. Find campaigns where LAST mission has takeOffStatus=1
        # 3. Show GUI ONLY if cleanup opportunities found
        # 4. Let user decide what to delete
        # 5. Create automatic backup before deletion
        
        startup_cleanup_check()
        
    except ImportError:
        print("Note: cleanup_failed_missions.py not found")
        print("      Mission cleanup feature not available")
        print()
    except Exception as e:
        print(f"Warning: Cleanup check failed: {e}")
        print("         Continuing with normal operations...")
        print()
        import traceback
        traceback.print_exc()
    
    # ========================================================================
    # START MONITORING
    # ========================================================================
    
    print()
    print("="*70)
    print("MONITORING ACTIVE")
    print("="*70)
    print("Checking for changes every 10 seconds...")
    print()
    print("This window will stay open - you can minimize it.")
    print("The tracker will automatically update your campaigns.")
    print()
    print("Press Ctrl+C to stop.")
    print()
    
    import monitor_campaigns
    monitor = monitor_campaigns.CampaignMonitor(check_interval=10)
    monitor.run()
    
except KeyboardInterrupt:
    print()
    print("="*70)
    print("TRACKER STOPPED BY USER")
    print("="*70)
    sys.exit(0)
    
except Exception as e:
    print()
    print("="*70)
    print(f"ERROR: {e}")
    print("="*70)
    import traceback
    traceback.print_exc()
    print()
    input("Press Enter to exit...")
    sys.exit(1)
