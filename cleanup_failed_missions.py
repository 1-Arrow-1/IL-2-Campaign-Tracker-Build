#!/usr/bin/env python3
"""
IL-2 Campaign Mission Cleanup Tool

Detects and allows deletion of unsuccessful last missions (takeOffStatus = 1)
from campaignsstates.txt, enabling replay for better results.
"""

import json
import re
import shutil
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set
import tkinter as tk
from tkinter import ttk, messagebox


# File to store "don't ask again" preferences
IGNORE_FILE = Path("cleanup_ignored_missions.json")


def load_ignored_missions() -> Set[str]:
    """
    Load list of missions that user chose to ignore
    
    Returns:
        Set of mission keys in format "campaign_name::mission_id"
    """
    if not IGNORE_FILE.exists():
        return set()
    
    try:
        with open(IGNORE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('ignored', []))
    except Exception as e:
        print(f"Warning: Could not load ignored missions: {e}")
        return set()


def save_ignored_missions(ignored: Set[str]):
    """
    Save list of ignored missions
    
    Args:
        ignored: Set of mission keys in format "campaign_name::mission_id"
    """
    try:
        data = {
            'ignored': sorted(list(ignored)),
            'last_updated': datetime.now().isoformat()
        }
        with open(IGNORE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save ignored missions: {e}")


def add_to_ignored(campaign_name: str, mission_id: str):
    """
    Add a mission to the ignore list
    
    Args:
        campaign_name: Campaign name
        mission_id: Mission identifier
    """
    ignored = load_ignored_missions()
    key = f"{campaign_name}::{mission_id}"
    ignored.add(key)
    save_ignored_missions(ignored)
    print(f"✓ Added to ignore list: {campaign_name} - Mission {mission_id}")


def is_ignored(campaign_name: str, mission_id: str) -> bool:
    """
    Check if a mission is in the ignore list
    
    Args:
        campaign_name: Campaign name
        mission_id: Mission identifier
        
    Returns:
        True if mission should be ignored
    """
    ignored = load_ignored_missions()
    key = f"{campaign_name}::{mission_id}"
    return key in ignored


class MissionCleanup:
    """Handle cleanup of failed campaign missions"""
    
    def __init__(self, decoded_json_path: str = 'campaigns_decoded.json',
                 mission_dates_path: str = 'campaign_mission_dates.json',
                 campaignstates_path: str = None):
        """
        Initialize cleanup tool
        
        Args:
            decoded_json_path: Path to decoded campaign states
            mission_dates_path: Path to campaign mission dates
            campaignstates_path: Path to raw campaign states file (if None, auto-detect from game directory)
        """
        self.decoded_path = Path(decoded_json_path)
        self.dates_path = Path(mission_dates_path)
        
        # Auto-detect campaignsstates.txt location from game directory
        if campaignstates_path is None:
            self.states_path = self._find_campaignstates_file()
        else:
            self.states_path = Path(campaignstates_path)
        
        self.max_backups = 10
        
        print(f"Using campaignsstates.txt: {self.states_path}")
    
    def _find_campaignstates_file(self) -> Path:
        """
        Find campaignsstates.txt in IL-2 game directory
        
        Returns:
            Path to campaignsstates.txt
        """
        # Try to get game directory from campaign_mission_dates.json
        if self.dates_path.exists():
            try:
                with open(self.dates_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    game_dir = data.get('game_directory', '')
                    
                    if game_dir:
                        game_path = Path(game_dir).expanduser().resolve()
                        states_file = game_path / 'data' / 'campaignsstates.txt'
                        
                        if states_file.exists():
                            print(f"✓ Found campaignsstates.txt in game directory: {game_dir}")
                            return states_file
                        else:
                            print(f"⚠️  campaignsstates.txt not found at: {states_file}")
            except Exception as e:
                print(f"⚠️  Could not read game directory: {e}")
        
        # Fallback: try current directory
        fallback = Path('campaignsstates.txt')
        if fallback.exists():
            print(f"⚠️  Using campaignsstates.txt from current directory (fallback)")
            return fallback
        
        # If not found anywhere
        print(f"❌ campaignsstates.txt not found!")
        print(f"   Please ensure campaign_mission_dates.json has correct game_directory")
        raise FileNotFoundError("campaignsstates.txt not found in game directory or current directory")
    
    def find_cleanup_opportunities(self) -> Dict:
        """
        Find campaigns where LAST mission has takeOffStatus = 1
        
        Returns:
            Dict of campaigns needing cleanup with their details
            (excludes missions marked as "don't ask again")
        """
        if not self.decoded_path.exists():
            print(f"⚠️  {self.decoded_path} not found - cannot scan")
            return {}
        
        # Load decoded campaign states
        with open(self.decoded_path, 'r', encoding='utf-8') as f:
            decoded = json.load(f)
        
        # Load mission order (if available)
        mission_dates = {}
        if self.dates_path.exists():
            with open(self.dates_path, 'r', encoding='utf-8') as f:
                mission_dates = json.load(f)
        
        # Load ignored missions
        ignored = load_ignored_missions()
        
        opportunities = {}
        
        for campaign_name, campaign_data in decoded.items():
            # Skip non-campaign entries
            if campaign_name == 'game_directory':
                continue
            
            # Get mission stats
            stats = campaign_data.get('characterStatisticsByFileName', {})
            if not stats:
                continue
            
            # Determine mission order
            dates_data = mission_dates.get(campaign_name, {})
            all_missions = dates_data.get('missions', {})
            
            if all_missions:
                # Use chronological order from campaign_mission_dates
                mission_order = sorted(all_missions.keys(),
                                     key=lambda x: int(x) if x.isdigit() else 0)
            else:
                # Fallback: numeric sort
                mission_order = sorted(stats.keys(),
                                     key=lambda x: int(x) if x.isdigit() else 0)
            
            # Find which missions have been flown
            flown_missions = [m for m in mission_order if m in stats]
            
            if not flown_missions:
                continue
            
            # Get LAST flown mission
            last_mission_id = flown_missions[-1]
            
            # *** CHECK IF IGNORED ***
            if is_ignored(campaign_name, last_mission_id):
                continue  # Skip this one - user chose "don't ask again"
            
            last_mission_stats = stats[last_mission_id]
            
            # Check takeOffStatus
            takeoff_status = last_mission_stats.get('takeOffStatus', 2)
            
            if takeoff_status == 1:
                # This campaign needs cleanup!
                
                # Calculate kills
                air_kills = (last_mission_stats.get('killLightPlane', 0) + 
                           last_mission_stats.get('killMediumPlane', 0) +
                           last_mission_stats.get('killHeavyPlane', 0))
                
                ground_kills = (last_mission_stats.get('killLightArmoredVehicle', 0) +
                              last_mission_stats.get('killMediumArmoredVehicle', 0) +
                              last_mission_stats.get('killHeavyArmoredVehicle', 0) +
                              last_mission_stats.get('killCannon', 0) +
                              last_mission_stats.get('killAAAGun', 0) +
                              last_mission_stats.get('killMachinegun', 0))
                
                naval_kills = (last_mission_stats.get('killLightShip', 0) +
                             last_mission_stats.get('killDestroyerShip', 0) +
                             last_mission_stats.get('killLargeCargoShip', 0))
                
                # Format flight time
                flight_time_seconds = last_mission_stats.get('totalFlightTime', 0)
                minutes = int(flight_time_seconds / 60)
                seconds = int(flight_time_seconds % 60)
                flight_time_str = f"{minutes:02d}:{seconds:02d}"
                
                opportunities[campaign_name] = {
                    'mission_id': last_mission_id,
                    'mission_number': f"{len(flown_missions)} of {len(mission_order)}",
                    'air_kills': air_kills,
                    'ground_kills': ground_kills,
                    'naval_kills': naval_kills,
                    'flight_time': flight_time_str,
                    'raw_stats': last_mission_stats
                }
        
        return opportunities
    
    def create_backup(self) -> Optional[Path]:
        """
        Create timestamped backup and manage backup count
        
        Returns:
            Path to backup file, or None if failed
        """
        if not self.states_path.exists():
            print(f"⚠️  {self.states_path} not found - cannot backup")
            return None
        
        # Create backup with timestamp in SAME directory as campaignsstates.txt
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'campaignsstates_{timestamp}.backup'
        backup_path = self.states_path.parent / backup_filename
        
        try:
            shutil.copy(self.states_path, backup_path)
            print(f"✓ Backup created: {backup_path}")
            
            # Cleanup old backups (keep only last 10)
            self.cleanup_old_backups()
            
            return backup_path
            
        except Exception as e:
            print(f"❌ Failed to create backup: {e}")
            return None
    
    def cleanup_old_backups(self):
        """Keep only the last N backups in game directory"""
        backup_pattern = 'campaignsstates_*.backup'
        backup_dir = self.states_path.parent
        backups = sorted(backup_dir.glob(backup_pattern))
        
        if len(backups) > self.max_backups:
            # Remove oldest backups
            to_remove = backups[:-self.max_backups]
            for backup in to_remove:
                try:
                    backup.unlink()
                    print(f"  Removed old backup: {backup.name}")
                except Exception as e:
                    print(f"  ⚠️  Could not remove {backup.name}: {e}")
    
    def delete_mission_entry(self, campaign_name: str, mission_id: str) -> bool:
        """
        Delete mission entry from campaignsstates.txt by removing specific patterns
        
        Args:
            campaign_name: Campaign folder name
            mission_id: Mission number (e.g., "11")
            
        Returns:
            True if successful, False otherwise
        """
        # Create backup first
        backup_path = self.create_backup()
        if not backup_path:
            return False
        
        try:
            # Read file
            with open(self.states_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            print(f"\nDeleting Mission {mission_id} from {campaign_name}...")
            print(f"Original file size: {len(content)} chars")
            
            # Find the campaign entry
            campaign_pattern = f'campaigns/{campaign_name}='
            if campaign_pattern not in content:
                print(f"❌ Campaign {campaign_name} not found in file")
                return False
            
            # Find campaign start
            campaign_start = content.index(campaign_pattern)
            print(f"Campaign starts at position: {campaign_start}")
            
            # Find campaign end (next campaign or end of file)
            next_campaign = content.find('&campaigns/', campaign_start + 1)
            if next_campaign == -1:
                campaign_end = len(content)
                print(f"Campaign ends at: EOF (last campaign)")
            else:
                campaign_end = next_campaign
                next_campaign_name = content[next_campaign:next_campaign+50]
                print(f"Campaign ends at: {campaign_end} (next: {next_campaign_name[:30]}...)")
            
            # Extract campaign section - WE ONLY WORK WITHIN THIS SECTION
            before_campaign = content[:campaign_start]
            campaign_section = content[campaign_start:campaign_end]
            after_campaign = content[campaign_end:]
            
            print(f"\n{'='*70}")
            print(f"ISOLATED CAMPAIGN SECTION FOR: {campaign_name}")
            print(f"{'='*70}")
            print(f"Section size: {len(campaign_section)} chars")
            print(f"Section preview: {campaign_section[:100]}...")
            print(f"{'='*70}\n")
            
            # CRITICAL: All deletions happen ONLY within campaign_section
            # This ensures we never touch other campaigns!
            
            # Pattern 1: Delete mission stats
            # From: %2526{mission_id}%253D  to: %252526killSubmarine%25253D{value}
            # Example: %252611%253Dsorties%253D...%252526killSubmarine%25253D0
            
            pattern1_start = f'%2526{mission_id}%253D'
            pattern1_end = '%252526killSubmarine%25253D'
            
            # Find the pattern
            start_idx = campaign_section.find(pattern1_start)
            if start_idx == -1:
                print(f"⚠️  Pattern 1 not found: {pattern1_start}")
                print(f"   Searching for mission {mission_id} in different encoding...")
                
                # Try alternative patterns
                alt_patterns = [
                    f'%26{mission_id}%3D',     # Less encoded
                    f'&{mission_id}=',          # Not encoded
                ]
                
                for alt_pattern in alt_patterns:
                    start_idx = campaign_section.find(alt_pattern)
                    if start_idx != -1:
                        print(f"   ✓ Found alternative pattern: {alt_pattern}")
                        pattern1_start = alt_pattern
                        # Adjust end pattern accordingly
                        if '%26' in alt_pattern:
                            pattern1_end = '%26killSubmarine%3D'
                        else:
                            pattern1_end = '&killSubmarine='
                        break
                
                if start_idx == -1:
                    print(f"❌ Could not find mission {mission_id} in any encoding")
                    print(f"   This mission may not exist in {campaign_name}")
                    return False
            
            # VALIDATION: Ensure we found it WITHIN our campaign section
            if start_idx < 0 or start_idx >= len(campaign_section):
                print(f"❌ ERROR: Pattern found outside campaign section!")
                print(f"   This should be impossible - aborting for safety")
                return False
            
            print(f"✓ Found pattern at position {start_idx} (within campaign section)")
            
            # Find the end of this mission's stats (start of next field or next mission)
            end_idx = campaign_section.find(pattern1_end, start_idx)
            if end_idx == -1:
                print(f"❌ Could not find end pattern: {pattern1_end}")
                return False
            
            # Find where killSubmarine value ends (next field or mission starts)
            # killSubmarine value is followed by either another mission (%2526{next_mission}) or next section
            end_search_start = end_idx + len(pattern1_end)
            
            # Find the next delimiter (start of next mission or next section)
            next_mission_start = campaign_section.find('%2526', end_search_start)
            if next_mission_start == -1:
                # Maybe it's the last mission, look for next section
                next_mission_start = campaign_section.find('%26', end_search_start)
            
            if next_mission_start == -1:
                print(f"⚠️  Could not find end of killSubmarine value, using end of stats")
                # Find the digit(s) after killSubmarine%25253D
                import re
                remaining = campaign_section[end_search_start:end_search_start+20]
                match = re.match(r'\d+', remaining)
                if match:
                    next_mission_start = end_search_start + len(match.group())
                else:
                    print(f"❌ Could not determine where to end deletion")
                    return False
            
            # Delete from start_idx to next_mission_start
            mission_data = campaign_section[start_idx:next_mission_start]
            print(f"\n✓ Found mission stats to delete:")
            print(f"  Position: {start_idx} to {next_mission_start}")
            print(f"  Length: {len(mission_data)} chars")
            print(f"  Preview: {mission_data[:100]}...")
            
            campaign_section = campaign_section[:start_idx] + campaign_section[next_mission_start:]
            print(f"✓ Deleted mission stats")
            
            # Pattern 2: Delete from completedMissionsByFileName
            # Pattern: %252611%253D1  or  %2526{mission_id}%253D1
            pattern2 = f'%2526{mission_id}%253D1'
            
            if pattern2 in campaign_section:
                campaign_section = campaign_section.replace(pattern2, '')
                print(f"✓ Deleted mission from completedMissionsByFileName")
            else:
                # Try alternative patterns
                alt_pattern2 = f'%26{mission_id}%3D1'
                if alt_pattern2 in campaign_section:
                    campaign_section = campaign_section.replace(alt_pattern2, '')
                    print(f"✓ Deleted mission from completedMissionsByFileName (alt pattern)")
                else:
                    print(f"⚠️  completedMissionsByFileName entry not found (might not exist)")
            
            # Reconstruct file
            new_content = before_campaign + campaign_section + after_campaign
            
            print(f"\n{'='*70}")
            print(f"RECONSTRUCTION COMPLETE")
            print(f"{'='*70}")
            print(f"Original file size: {len(content)} chars")
            print(f"New file size: {len(new_content)} chars")
            print(f"Difference: {len(content) - len(new_content)} chars removed")
            
            # VALIDATION: Ensure we didn't touch other campaigns
            # Count how many times campaigns/ appears
            orig_campaign_count = content.count('&campaigns/')
            new_campaign_count = new_content.count('&campaigns/')
            
            if orig_campaign_count != new_campaign_count:
                print(f"\n❌ ERROR: Campaign count changed!")
                print(f"   Original: {orig_campaign_count} campaigns")
                print(f"   New: {new_campaign_count} campaigns")
                print(f"   This should never happen - aborting!")
                return False
            
            print(f"✓ Campaign count unchanged: {orig_campaign_count} campaigns")
            print(f"✓ Only modified {campaign_name}, other campaigns untouched")
            print(f"{'='*70}\n")
            
            # Write back
            with open(self.states_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            print(f"✓ Deleted Mission {mission_id} from {campaign_name}")
            
            # Verify deletion
            if self.verify_deletion(campaign_name, mission_id):
                print(f"✓ Deletion verified")
                return True
            else:
                print(f"⚠️  Verification failed - restoring backup")
                shutil.copy(backup_path, self.states_path)
                return False
                
        except Exception as e:
            print(f"❌ Error during deletion: {e}")
            import traceback
            traceback.print_exc()
            print("Restoring backup...")
            if backup_path:
                shutil.copy(backup_path, self.states_path)
            return False
    
    def verify_deletion(self, campaign_name: str, mission_id: str) -> bool:
        """
        Verify mission was actually deleted
        
        Args:
            campaign_name: Campaign folder name
            mission_id: Mission number
            
        Returns:
            True if mission is gone, False if still exists
        """
        try:
            # Simple verification: read file and check if mission ID still exists
            with open(self.states_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find campaign section
            campaign_pattern = f'campaigns/{campaign_name}='
            if campaign_pattern not in content:
                print(f"⚠️  Campaign {campaign_name} not found in file")
                return False
            
            # Extract campaign section
            start = content.index(campaign_pattern)
            # Find next campaign or end of file
            next_campaign = content.find('&campaigns/', start + 1)
            if next_campaign == -1:
                campaign_section = content[start:]
            else:
                campaign_section = content[start:next_campaign]
            
            # Decode and check if mission exists
            decoded = urllib.parse.unquote(campaign_section)
            
            # Mission should NOT exist in the characterStatisticsByFileName section
            # Pattern: &{mission_id}= or ={mission_id}=
            mission_patterns = [
                f'&{mission_id}=',
                f'={mission_id}=',
            ]
            
            for pattern in mission_patterns:
                if pattern in decoded:
                    print(f"⚠️  Mission {mission_id} still found with pattern: {pattern}")
                    return False
            
            # Double check with URL-encoded version
            encoded_patterns = [
                urllib.parse.quote(f'&{mission_id}='),
                urllib.parse.quote(f'={mission_id}='),
            ]
            
            for pattern in encoded_patterns:
                if pattern in campaign_section:
                    print(f"⚠️  Mission {mission_id} still found (encoded)")
                    return False
            
            return True
            
        except Exception as e:
            print(f"⚠️  Could not verify deletion: {e}")
            import traceback
            traceback.print_exc()
            return False


class CleanupGUI:
    """Tkinter GUI for mission cleanup"""
    
    def __init__(self, opportunities: Dict):
        """
        Initialize GUI
        
        Args:
            opportunities: Dict of campaigns needing cleanup
        """
        self.opportunities = opportunities
        self.selected = {}  # campaign_name -> selected (bool)
        self.ignore_flags = {}  # campaign_name -> ignore flag (bool)
        self.cleanup_tool = MissionCleanup()
        
        self.root = tk.Tk()
        self.root.title("IL-2 Campaign Mission Cleanup")
        self.root.geometry("800x550")
        
        self.create_widgets()
    
    def create_widgets(self):
        """Create GUI widgets"""
        
        # Title
        title_frame = ttk.Frame(self.root, padding="10")
        title_frame.pack(fill=tk.X)
        
        ttk.Label(title_frame, text="Campaign Mission Cleanup",
                 font=('Arial', 14, 'bold')).pack()
        
        ttk.Label(title_frame, 
                 text="Found unsuccessful last missions that can be replayed:",
                 font=('Arial', 10)).pack()
        
        # Scrollable frame for campaigns
        canvas_frame = ttk.Frame(self.root)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        canvas = tk.Canvas(canvas_frame)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Create campaign cards
        for campaign_name, data in self.opportunities.items():
            self.create_campaign_card(scrollable_frame, campaign_name, data)
        
        # Buttons
        button_frame = ttk.Frame(self.root, padding="10")
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="Apply Changes", 
                  command=self.on_apply, width=20).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", 
                  command=self.on_cancel, width=20).pack(side=tk.LEFT, padx=5)
        
        # Note
        note_frame = ttk.Frame(self.root, padding="10")
        note_frame.pack(fill=tk.X)
        
        ttk.Label(note_frame, 
                 text="Note: Backup will be created automatically before deletion. "
                      "Ignored missions can be managed in cleanup_ignored_missions.json",
                 font=('Arial', 9, 'italic'),
                 foreground='gray').pack()
    
    def create_campaign_card(self, parent, campaign_name: str, data: Dict):
        """Create a card for one campaign"""
        
        card = ttk.LabelFrame(parent, text=campaign_name.upper(), padding="10")
        card.pack(fill=tk.X, padx=5, pady=5)
        
        # Mission info
        info_text = f"Last Mission: {data['mission_number']}"
        ttk.Label(card, text=info_text, font=('Arial', 10, 'bold')).pack(anchor=tk.W)
        
        ttk.Label(card, text="Status: ⚠️  Unsuccessful (takeOffStatus = 1)",
                 foreground='orange').pack(anchor=tk.W)
        
        # Stats
        stats_text = f"Result: {data['air_kills']} air, {data['ground_kills']} ground"
        if data['naval_kills'] > 0:
            stats_text += f", {data['naval_kills']} naval"
        stats_text += f" | Flight Time: {data['flight_time']}"
        
        ttk.Label(card, text=stats_text).pack(anchor=tk.W)
        
        # Warning
        ttk.Label(card, 
                 text="⚠️  This mission entry is locked. Delete it to replay for a better result.",
                 foreground='red',
                 font=('Arial', 9)).pack(anchor=tk.W, pady=(5, 0))
        
        # Separator
        ttk.Separator(card, orient='horizontal').pack(fill=tk.X, pady=8)
        
        # Action frame for checkboxes
        action_frame = ttk.Frame(card)
        action_frame.pack(fill=tk.X, anchor=tk.W)
        
        # Delete checkbox
        delete_var = tk.BooleanVar(value=False)
        self.selected[campaign_name] = delete_var
        
        ttk.Checkbutton(action_frame, 
                       text=f"Delete Mission {data['mission_id']} entry",
                       variable=delete_var).pack(anchor=tk.W)
        
        # Ignore checkbox (with distinctive styling)
        ignore_var = tk.BooleanVar(value=False)
        self.ignore_flags[campaign_name] = ignore_var
        
        ignore_frame = ttk.Frame(action_frame)
        ignore_frame.pack(anchor=tk.W, pady=(5, 0))
        
        ignore_cb = ttk.Checkbutton(ignore_frame, 
                                   text="Don't ask me about this mission again",
                                   variable=ignore_var)
        ignore_cb.pack(side=tk.LEFT)
        
        # Info icon/text
        ttk.Label(ignore_frame, 
                 text="ℹ️",
                 foreground='blue',
                 cursor='hand2').pack(side=tk.LEFT, padx=(5, 0))
        
        # Tooltip would be nice here but keeping it simple
        ttk.Label(ignore_frame,
                 text="(Hide this mission from future checks)",
                 font=('Arial', 8, 'italic'),
                 foreground='gray').pack(side=tk.LEFT, padx=(2, 0))
    
    def on_apply(self):
        """Handle Apply button"""
        
        # Get selected campaigns for deletion
        to_delete = [(name, data) for name, data in self.opportunities.items() 
                    if self.selected[name].get()]
        
        # Get campaigns to ignore
        to_ignore = [(name, data) for name, data in self.opportunities.items()
                    if self.ignore_flags[name].get()]
        
        if not to_delete and not to_ignore:
            messagebox.showinfo("No Changes", "No missions selected for cleanup or ignore")
            return
        
        # Build confirmation message
        msg_parts = []
        
        if to_delete:
            msg_parts.append(f"Delete {len(to_delete)} mission entr{'y' if len(to_delete) == 1 else 'ies'}:")
            for name, data in to_delete:
                msg_parts.append(f"  • {name} - Mission {data['mission_id']}")
        
        if to_ignore:
            msg_parts.append("")
            msg_parts.append(f"Hide {len(to_ignore)} mission{'s' if len(to_ignore) > 1 else ''} from future checks:")
            for name, data in to_ignore:
                msg_parts.append(f"  • {name} - Mission {data['mission_id']}")
        
        if to_delete:
            msg_parts.append("")
            msg_parts.append("Backup will be created automatically.")
        
        msg = "\n".join(msg_parts)
        
        if not messagebox.askyesno("Confirm Changes", msg):
            return
        
        # Process ignore flags FIRST (before any deletion)
        for campaign_name, data in to_ignore:
            mission_id = data['mission_id']
            add_to_ignored(campaign_name, mission_id)
        
        # Perform deletions
        success_count = 0
        if to_delete:
            for campaign_name, data in to_delete:
                mission_id = data['mission_id']
                if self.cleanup_tool.delete_mission_entry(campaign_name, mission_id):
                    success_count += 1
        
        # Build result message
        result_parts = []
        
        if to_delete:
            if success_count == len(to_delete):
                result_parts.append(f"✓ Successfully deleted {success_count} mission entr{'y' if success_count == 1 else 'ies'}!")
                result_parts.append("You can now replay these missions for better results.")
            else:
                result_parts.append(f"⚠️  Deleted {success_count} of {len(to_delete)} missions.")
                result_parts.append("Check console for details.")
        
        if to_ignore:
            result_parts.append("")
            result_parts.append(f"✓ Added {len(to_ignore)} mission{'s' if len(to_ignore) > 1 else ''} to ignore list.")
            result_parts.append("You won't be asked about them again.")
        
        result_msg = "\n".join(result_parts)
        
        if success_count == len(to_delete) or not to_delete:
            messagebox.showinfo("Success", result_msg)
        else:
            messagebox.showwarning("Partial Success", result_msg)
        
        self.root.destroy()
    
    def on_cancel(self):
        """Handle Cancel button"""
        self.root.destroy()
    
    def run(self):
        """Run the GUI"""
        self.root.mainloop()


def startup_cleanup_check():
    """
    Run at tracker startup to check for cleanup opportunities
    
    Returns:
        True if cleanup was performed, False otherwise
    """
    print("\n" + "="*70)
    print("SCANNING FOR UNSUCCESSFUL LAST MISSIONS...")
    print("="*70)
    
    cleanup = MissionCleanup()
    opportunities = cleanup.find_cleanup_opportunities()
    
    # Show info about ignored missions (if any exist)
    ignored = load_ignored_missions()
    if ignored:
        print(f"ℹ️  {len(ignored)} mission(s) currently in ignore list")
        print(f"   (To manage: edit cleanup_ignored_missions.json)")
        print()
    
    if not opportunities:
        print("✓ All campaigns clean - no unsuccessful last missions found")
        return False
    
    print(f"\n⚠️  Found {len(opportunities)} campaign(s) with unsuccessful last mission:")
    for name, data in opportunities.items():
        print(f"  • {name} - Mission {data['mission_id']}")
    
    # Show GUI
    gui = CleanupGUI(opportunities)
    gui.run()
    
    return True


if __name__ == '__main__':
    startup_cleanup_check()
