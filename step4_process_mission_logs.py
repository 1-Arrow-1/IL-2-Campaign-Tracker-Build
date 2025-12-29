#!/usr/bin/env python3
"""
IL-2 Campaign Progress Tracker - Step 4: Mission Log Processor

Processes mission report files (.mlg) from FlightLogs folder:
1. Finds .mlg files for completed missions
2. Converts .mlg to .txt using mlg2txt
3. Parses .txt to .events.json using il2_mission_debrief
4. Returns debriefing data for HTML generation

Usage:
    from step4_process_mission_logs import MissionLogProcessor
    processor = MissionLogProcessor(game_directory)
    debriefings = processor.get_all_debriefings(campaign_name, completed_missions)
"""

import re
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import shutil


class MissionLogProcessor:
    def __init__(self, game_directory: str, verbose: bool = False):
        """
        Initialize mission log processor
        
        Args:
            game_directory: Path to IL-2 game directory
            verbose: Enable detailed logging
        """
        self.game_directory = Path(game_directory)
        self.flight_logs_dir = self.game_directory / "data" / "FlightLogs"
        self.verbose = verbose
        
        # Working directory for temporary files
        self.work_dir = Path.cwd()
        
        # Import required modules
        self._import_modules()
        
        if self.verbose:
            print(f"MissionLogProcessor initialized")
            print(f"  Game directory: {self.game_directory}")
            print(f"  FlightLogs: {self.flight_logs_dir}")
            print(f"  Exists: {self.flight_logs_dir.exists()}")
    
    def _import_modules(self):
        """Import il2_mission_debrief module (mlg2txt used via subprocess only)"""
        # Note: mlg2txt is NOT imported because it runs argparse at module level
        # We use subprocess instead
        self.mlg2txt = None
        
        try:
            import il2_mission_debrief
            self.debrief_parser = il2_mission_debrief
        except ImportError as e:
            print(f"Warning: Could not import il2_mission_debrief: {e}")
            self.debrief_parser = None
    
    def get_all_debriefings(self, campaign_name: str, completed_missions: List[str]) -> Dict:
        """
        Get debriefing data for all completed missions in a campaign
        
        Args:
            campaign_name: Name of campaign (e.g., "kerch")
            completed_missions: List of completed mission IDs (e.g., ["01", "02", "08"])
        
        Returns:
            Dict mapping mission_id -> debriefing_data
            {
                "08": {
                    "aircraft": "Bf 109 G-6",
                    "duration": "01:17:50",
                    "air_kills": 4,
                    "ground_kills": 3,
                    "events": [...],
                    "timestamp": "2025-12-22_15-47-53"
                }
            }
        """
        if not self.flight_logs_dir.exists():
            if self.verbose:
                print(f"FlightLogs directory not found: {self.flight_logs_dir}")
            return {}
        
        debriefings = {}
        
        for mission_id in completed_missions:
            try:
                print(f"  Looking for debriefing: {campaign_name}/{mission_id}")
                debriefing = self.get_mission_debriefing(campaign_name, mission_id)
                if debriefing:
                    debriefings[mission_id] = debriefing
                    print(f"    ✓ Debriefing loaded for Mission {mission_id}")
                else:
                    print(f"    ⚠️  No debriefing data returned for Mission {mission_id}")
            except Exception as e:
                print(f"    ❌ Error processing mission {campaign_name}/{mission_id}: {e}")
                if self.verbose:
                    import traceback
                    traceback.print_exc()
                continue
        
        return debriefings
    
    def get_mission_debriefing(self, campaign_name: str, mission_id: str) -> Optional[Dict]:
        """
        Get debriefing data for a single mission
        
        Args:
            campaign_name: Campaign name (e.g., "kerch")
            mission_id: Mission ID (e.g., "08" or "1943-07-04a-FW190-A5U17-IISG1")
        
        Returns:
            Debriefing data dict or None if not found/failed
        """
        # Find newest .mlg file for this mission
        mlg_file = self._find_newest_mlg(campaign_name, mission_id)
        
        if not mlg_file:
            if self.verbose:
                print(f"  No .mlg file found for {campaign_name}/{mission_id}")
            return None
        
        if self.verbose:
            print(f"  Found .mlg: {mlg_file.name}")
        
        # Process pipeline: .mlg → .txt → .json
        try:
            # Step 1: Convert .mlg to .txt (creates ONE complete file without --split)
            txt_file = self._mlg_to_txt(mlg_file)
            if not txt_file or not txt_file.exists():
                if self.verbose:
                    print(f"  Failed to convert .mlg to .txt")
                return None
            
            # Step 2: Parse .txt to .events.json
            json_file = self._txt_to_json(txt_file)
            if not json_file or not json_file.exists():
                if self.verbose:
                    print(f"  Failed to parse .txt to .json")
                return None
            
            # Step 3: Load and return JSON data
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Add metadata
            timestamp = self._extract_timestamp(mlg_file.name)
            data['timestamp'] = timestamp
            data['mission_id'] = mission_id
            
            if self.verbose:
                print(f"  ✓ Debriefing loaded: {data['summary']}")
            
            return data
            
        except Exception as e:
            print(f"  Error processing {mlg_file.name}: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return None
    
    def _find_newest_mlg(self, campaign_name: str, mission_id: str) -> Optional[Path]:
        """
        Find newest .mlg file for a specific mission
        
        Searches for .mlg files containing "campaigns/<campaign>/<mission>.msnbin"
        and returns the one with the newest timestamp.
        
        Args:
            campaign_name: Campaign name (lowercase)
            mission_id: Mission ID (e.g., "08" or "1940-11-27a-BoB I JG51-BF109F1-fighter-sweep")
        
        Returns:
            Path to newest .mlg file or None
        """
        import urllib.parse
        
        # Pattern to search for in .mlg files
        # Handle both .msnbin and .cmpbin
        # Also handle URL-encoded variants (spaces as %20, etc.)
        patterns = []
        
        # Normal version (decoded)
        patterns.append(f"campaigns/{campaign_name}/{mission_id}.msnbin".encode('utf-8'))
        patterns.append(f"campaigns/{campaign_name}/{mission_id}.cmpbin".encode('utf-8'))
        
        # URL-encoded version (if mission_id contains spaces or special chars)
        mission_id_encoded = urllib.parse.quote(mission_id)
        if mission_id_encoded != mission_id:
            patterns.append(f"campaigns/{campaign_name}/{mission_id_encoded}.msnbin".encode('utf-8'))
            patterns.append(f"campaigns/{campaign_name}/{mission_id_encoded}.cmpbin".encode('utf-8'))
        
        matching_files = []
        
        # Scan all .mlg files
        for mlg_file in self.flight_logs_dir.glob("*.mlg"):
            try:
                # Read file and search for campaign mission pattern
                with open(mlg_file, 'rb') as f:
                    content = f.read()
                
                # Check if this .mlg contains our mission
                if any(pattern in content for pattern in patterns):
                    # Extract timestamp from filename
                    timestamp = self._extract_timestamp(mlg_file.name)
                    if timestamp:
                        matching_files.append((mlg_file, timestamp))
                        if self.verbose:
                            print(f"    Found: {mlg_file.name} ({timestamp})")
            
            except Exception as e:
                if self.verbose:
                    print(f"    Error reading {mlg_file.name}: {e}")
                continue
        
        if not matching_files:
            return None
        
        # Return newest (sort by timestamp, descending)
        matching_files.sort(key=lambda x: x[1], reverse=True)
        newest = matching_files[0][0]
        
        if self.verbose and len(matching_files) > 1:
            print(f"    Multiple versions found, using newest: {newest.name}")
        
        return newest
    
    def _extract_timestamp(self, filename: str) -> Optional[str]:
        """
        Extract timestamp from .mlg filename
        
        Example: "missionReport(2025-12-22_15-47-53).mlg" → "2025-12-22_15-47-53"
        
        Returns:
            Timestamp string or None if pattern doesn't match
        """
        match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', filename)
        return match.group(1) if match else None
    
    def _mlg_to_txt(self, mlg_file: Path) -> Optional[Path]:
        """
        Convert .mlg to .txt using mlg2txt module via subprocess
        
        Note: mlg2txt ALWAYS creates files with [N] suffix in the filename.
        Without --split: Creates ONE file named [0].txt with all events.
        With --split: Creates MULTIPLE files [0].txt, [1].txt, [2].txt with fragmented events.
        
        Args:
            mlg_file: Path to .mlg file
        
        Returns:
            Path to generated .txt file or None
        """
        try:
            base_name = mlg_file.stem  # Without .mlg
            # mlg2txt ALWAYS creates [0].txt, even without --split flag
            txt_file = mlg_file.parent / f"{base_name}[0].txt"
            
            # Check if already converted AND if .txt is newer than .mlg
            if txt_file.exists():
                # Compare modification times
                mlg_mtime = mlg_file.stat().st_mtime
                txt_mtime = txt_file.stat().st_mtime
                
                if txt_mtime >= mlg_mtime:
                    # TXT is up-to-date
                    if self.verbose:
                        print(f"    Using existing .txt: {txt_file.name}")
                    return txt_file
                else:
                    # MLG is newer - need to reconvert
                    if self.verbose:
                        print(f"    .mlg is newer than .txt, reconverting...")
            
            if self.verbose:
                print(f"    Converting .mlg to .txt...")
            
            # Find mlg2txt executable
            import sys
            
            if getattr(sys, 'frozen', False):
                # Running as compiled EXE
                # mlg2txt.exe should be in same directory as the EXE
                exe_dir = Path(sys.executable).parent
                mlg2txt_executable = exe_dir / 'mlg2txt.exe'
                
                if not mlg2txt_executable.exists():
                    print(f"    Error: mlg2txt.exe not found at {mlg2txt_executable}")
                    print(f"    Please ensure mlg2txt.exe is in the same folder as IL2_CampaignTracker.exe")
                    return None
            else:
                # Running as Python script
                # Use mlg2txt.py with Python
                mlg2txt_executable = Path(__file__).parent / 'mlg2txt.py'
                
                if not mlg2txt_executable.exists():
                    print(f"    Error: mlg2txt.py not found at {mlg2txt_executable}")
                    return None
            
            # Use subprocess to run mlg2txt
            import subprocess
            import sys
            
            # Determine command based on whether we're running as EXE or script
            if getattr(sys, 'frozen', False):
                # Running as EXE - call mlg2txt.exe directly
                cmd = [str(mlg2txt_executable), '--output', str(mlg_file.parent), str(mlg_file)]
            else:
                # Running as script - call mlg2txt.py with Python
                cmd = [sys.executable, str(mlg2txt_executable), '--output', str(mlg_file.parent), str(mlg_file)]
            
            # Run conversion
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            if result.returncode != 0:
                print(f"    mlg2txt failed: {result.stderr}")
                return None
            
            # Check if file was created
            if txt_file.exists():
                if self.verbose:
                    print(f"    ✓ Created: {txt_file.name}")
                return txt_file
            else:
                print(f"    Error: Expected output not found: {txt_file}")
                return None
                
        except Exception as e:
            print(f"    Error in mlg2txt conversion: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return None
    
    def _txt_to_json(self, txt_file: Path) -> Optional[Path]:
        """
        Parse .txt to .events.json using il2_mission_debrief
        
        Args:
            txt_file: Path to .txt file
        
        Returns:
            Path to generated .events.json file
        """
        if not self.debrief_parser:
            print("Error: il2_mission_debrief module not available")
            return None
        
        try:
            # Expected output: same name with .events.json
            json_file = txt_file.with_suffix('.events.json')
            
            # ALWAYS regenerate JSON to ensure it reflects the latest mission report
            # This is important when user re-flies missions (e.g., after being shot down)
            if self.verbose:
                if json_file.exists():
                    print(f"    Regenerating .json from latest report...")
                else:
                    print(f"    Parsing .txt to .json...")
            
            # Create parser and process
            parser = self.debrief_parser.MissionDebriefParser(str(txt_file))
            stats = parser.parse()
            parser.to_json(str(json_file))
            
            if json_file.exists():
                if self.verbose:
                    print(f"    ✓ Created: {json_file.name}")
                return json_file
            else:
                print(f"    Error: JSON output not created")
                return None
                
        except Exception as e:
            print(f"    Error in debrief parsing: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return None


def main():
    """Test/demo function"""
    import argparse
    
    # Parse OUR arguments BEFORE importing mlg2txt (which has its own argparser)
    parser = argparse.ArgumentParser(description="Process IL-2 mission logs")
    parser.add_argument("game_directory", help="Path to IL-2 game directory")
    parser.add_argument("campaign", help="Campaign name (e.g., kerch)")
    parser.add_argument("missions", nargs='+', help="Mission IDs (e.g., 01 02 08)")
    parser.add_argument("-v", "--verbose", action='store_true', help="Verbose output")
    
    args = parser.parse_args()
    
    print("="*70)
    print("IL-2 MISSION LOG PROCESSOR - Step 4")
    print("="*70)
    print()
    
    processor = MissionLogProcessor(args.game_directory, verbose=args.verbose)
    debriefings = processor.get_all_debriefings(args.campaign, args.missions)
    
    print()
    print(f"Processed {len(debriefings)} mission(s):")
    for mission_id, data in debriefings.items():
        print(f"  Mission {mission_id}:")
        print(f"    Aircraft: {data['player']['aircraft']}")
        print(f"    Duration: {data['summary']['flight_duration']}")
        print(f"    Air Kills: {data['summary']['air_kills']}")
        print(f"    Ground Kills: {data['summary']['ground_kills']}")
        print(f"    Status: {data['summary']['final_state']}")


if __name__ == "__main__":
    main()
