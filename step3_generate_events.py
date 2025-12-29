#!/usr/bin/env python3
"""
IL-2 Campaign Progress Tracker - Step 3: Event Generator

Reads decoded campaign save files and generates Events section for campaign info files.
Calculates ranks, awards, and creates chronological event timeline.
Also processes mission logs (.mlg files) to generate debriefing sections.

Usage:
    python step3_generate_events.py
    
Files needed:
    - campaigns_decoded.json (from decode_campaing_usersave1.py)
    - campaign_mission_dates.json (from step1_extract_mission_dates.py)
    - campaign_progress_config.yaml (ranks & awards configuration)
    - mlg2txt.py (for mission log conversion)
    - il2_mission_debrief.py (for debriefing parsing)
    - object_categories.yaml (for object classification)
"""

import json
import yaml
import shutil
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re
import argparse


def smart_mission_sort_key(mission_id: str):
    """
    Smart sorting for mission IDs
    - Numeric IDs (01, 02, 10): Sort numerically
    - Date-based IDs (1943-07-04a): Sort alphabetically (ISO format sorts correctly)
    - Mixed (01a, 02b): Sort by number then suffix
    """
    # If it's purely numeric, convert to int
    if mission_id.isdigit():
        return (int(mission_id), "")
    
    # Try to extract leading digits (handles "01a", "02b", "1943-07-04a", etc.)
    match = re.match(r'^(\d+)(.*)$', mission_id)
    if match:
        return (int(match.group(1)), match.group(2))
    
    # No leading digits - sort alphabetically (works for ISO dates like "1943-07-04a")
    # Use large number to put these after pure numeric missions
    return (999999, mission_id)


class EventGenerator:
    def __init__(self, config_file: str = "campaign_progress_config.yaml", dry_run: bool = False):
        """Initialize event generator with configuration
        
        Args:
            config_file: Path to YAML configuration
            dry_run: If True, don't actually modify files (just show what would happen)
        """
        
        self.dry_run = dry_run
        
        # Load configuration
        # Try external file first (for user editing), then embedded
        from pathlib import Path
        import sys
        
        config_path = Path(config_file)
        if not config_path.is_absolute():
            # Relative path - check multiple locations
            if getattr(sys, 'frozen', False):
                # Running as EXE - check directory next to EXE first
                exe_dir = Path(sys.executable).parent
                config_path = exe_dir / config_file
                if not config_path.exists():
                    # Fallback to embedded
                    config_path = Path(sys._MEIPASS) / config_file
        
        # Try UTF-8 first, fallback to ISO-8859-1
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
        except UnicodeDecodeError:
            with open(config_path, 'r', encoding='iso-8859-1') as f:
                self.config = yaml.safe_load(f)
        
        # Load mission dates with explicit error handling
        try:
            with open('campaign_mission_dates.json', 'r', encoding='utf-8') as f:
                self.mission_dates = json.load(f)
        except FileNotFoundError:
            print(f"ERROR: Required file 'campaign_mission_dates.json' not found!")
            print(f"Please run step1_extract_mission_dates.py first.")
            raise
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in 'campaign_mission_dates.json'")
            print(f"  Line {e.lineno}, Column {e.colno}: {e.msg}")
            print(f"  The file may be corrupted. Try regenerating it.")
            raise
        
        # Load decoded save data with explicit error handling
        try:
            with open('campaigns_decoded.json', 'r', encoding='utf-8') as f:
                self.save_data = json.load(f)
        except FileNotFoundError:
            print(f"ERROR: Required file 'campaigns_decoded.json' not found!")
            print(f"Please run decode_campaing_usersave1.py first.")
            raise
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in 'campaigns_decoded.json'")
            print(f"  Line {e.lineno}, Column {e.colno}: {e.msg}")
            print(f"  The file may be corrupted. Try re-decoding the save file.")
            raise
        
        # Extract game directory from mission dates JSON
        self.game_directory = self.mission_dates.get('game_directory', '')
        
        # Initialize Mission Log Processor for debriefings
        self.log_processor = None
        if self.game_directory:
            try:
                from step4_process_mission_logs import MissionLogProcessor
                self.log_processor = MissionLogProcessor(self.game_directory, verbose=False)
                print(f"  - Mission log processor initialized")
            except Exception as e:
                print(f"  - Warning: Could not initialize mission log processor: {e}")
        
        print(f"Loaded configuration:")
        print(f"  - {len(self.mission_dates) - 1} campaigns with dates")  # -1 for game_directory key
        print(f"  - {len(self.save_data)} campaigns with save data")
        print(f"  - Game directory: {self.game_directory}")
        
        # Create case-insensitive lookup for mission_dates
        # (campaign names may have different capitalization between sources)
        self.mission_dates_lower = {
            k.lower(): (k, v) for k, v in self.mission_dates.items() if k != 'game_directory'
        }
    
    def extract_mission_datetime(self, campaign_name: str, mission_id: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extract mission date and start time from .eng file
        
        Looks for:
        - Date: 4 November, 1943<br>
        - Time: 9:45<br>
        
        Args:
            campaign_name: Campaign folder name
            mission_id: Mission identifier (e.g., "01", "1941-07-02a")
            
        Returns:
            Tuple of (date_string, time_string) or (None, None) if not found
            Example: ("4 November, 1943", "09:45")
        """
        if not self.game_directory:
            return None, None
        
        campaign_path = Path(self.game_directory) / "data" / "Campaigns" / campaign_name
        
        # Try to find the mission file - check common patterns
        possible_files = [
            campaign_path / f"{mission_id}.eng",
            campaign_path / f"{mission_id.zfill(2)}.eng",
        ]
        
        # Also check for files with extended names
        for file in campaign_path.glob(f"{mission_id}*.eng"):
            possible_files.append(file)
        
        for mission_file in possible_files:
            if not mission_file.exists():
                continue
            
            try:
                # Try multiple encodings (IL-2 uses UTF-16 LE for .eng files)
                content = None
                for encoding in ['utf-16-le', 'utf-16', 'utf-8', 'utf-8-sig', 'iso-8859-1']:
                    try:
                        with open(mission_file, 'r', encoding=encoding, errors='ignore') as f:
                            content = f.read(2000)  # Read first 2000 chars (briefing is at top)
                        break  # Success!
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                
                if not content:
                    continue
                
                # Look for: Date: 4 November, 1943<br>
                date_str = None
                date_match = re.search(r'Date:\s*([^<\r\n]+)', content, re.IGNORECASE)
                if date_match:
                    date_str = date_match.group(1).strip()
                
                # Look for: Time: 9:45<br> or Time: 09:45<br>
                time_str = None
                time_match = re.search(r'Time:\s*(\d{1,2}:\d{2})', content, re.IGNORECASE)
                if time_match:
                    time_raw = time_match.group(1)
                    # Ensure HH:MM format
                    parts = time_raw.split(':')
                    if len(parts) == 2:
                        hours = parts[0].zfill(2)
                        minutes = parts[1]
                        time_str = f"{hours}:{minutes}"
                
                if date_str or time_str:
                    return date_str, time_str
            
            except Exception:
                continue
        
        return None, None
    
    def extract_mission_start_time(self, campaign_name: str, mission_id: str) -> Optional[str]:
        """
        Extract mission start time from .eng file (backward compatibility)
        
        Returns:
            Time string (e.g., "09:45") or None if not found
        """
        _, time_str = self.extract_mission_datetime(campaign_name, mission_id)
        return time_str
    
    def calculate_cumulative_stats(self, campaign_stats: Dict) -> Dict:
        """
        Calculate cumulative statistics from characterStatisticsByFileName
        
        Args:
            campaign_stats: characterStatisticsByFileName from save data
            
        Returns:
            Dictionary of cumulative statistics
        """
        cumulative = {
            'missions_completed': 0,
            'total_air_kills': 0,
            'fighter_kills': 0,  # killLightPlane + killMediumPlane
            'bomber_kills': 0,   # killHeavyPlane
            'static_plane_kills': 0,  # killStaticPlane (parked aircraft)
            'air_combat_score': 0,  # fighters + static_planes*0.5 + (bombers*2)
            'ground_kills': 0,
            'tank_kills': 0,
            'ship_kills': 0,
            'total_kills': 0,  # air + ground + ship
            'deaths': 0,
            'total_flight_time': 0,  # seconds
            'flight_time_hours': 0,
            'total_score': 0
        }
        
        for mission_num, stats in campaign_stats.items():
            # Defensive: ensure stats is a dict
            if not isinstance(stats, dict):
                print(f"    Warning: Stats for mission {mission_num} is not a dict: {type(stats)} = {stats}")
                continue
            
            cumulative['missions_completed'] += 1
            
            # Air kills (static planes count as 0.5)
            light = int(stats.get('killLightPlane', 0))
            medium = int(stats.get('killMediumPlane', 0))
            heavy = int(stats.get('killHeavyPlane', 0))
            static = int(stats.get('killStaticPlane', 0))
            
            cumulative['fighter_kills'] += light + medium
            cumulative['bomber_kills'] += heavy
            cumulative['static_plane_kills'] += static
            cumulative['total_air_kills'] += light + medium + heavy + (static * 0.5)
            
            # Air combat score (weighted: bombers count double, static count 0.5)
            cumulative['air_combat_score'] += light + medium + (static * 0.5) + (heavy * 2)
            
            # Ground kills
            ground = (
                int(stats.get('killTransportVehicle', 0)) +
                int(stats.get('killLightArmoredVehicle', 0)) +
                int(stats.get('killMediumArmoredVehicle', 0)) +
                int(stats.get('killHeavyArmoredVehicle', 0)) +
                int(stats.get('killCannon', 0)) +
                int(stats.get('killAAAGun', 0)) +
                int(stats.get('killMachinegun', 0)) +
                int(stats.get('killRocketLauncher', 0)) +
                int(stats.get('killRailroadCarriage', 0)) +
                int(stats.get('killLocomotive', 0)) +
                int(stats.get('killRailroadStation', 0)) +
                int(stats.get('killBridge', 0)) +
                int(stats.get('killFacility', 0)) +
                int(stats.get('killRadar', 0)) +
                int(stats.get('killSearchlight', 0)) +
                int(stats.get('killResidentalBuilding', 0))
            )
            cumulative['ground_kills'] += ground
            
            # Tank kills
            tanks = (
                int(stats.get('killLightArmoredVehicle', 0)) +
                int(stats.get('killMediumArmoredVehicle', 0)) +
                int(stats.get('killHeavyArmoredVehicle', 0))
            )
            cumulative['tank_kills'] += tanks
            
            # Ship kills
            ships = (
                int(stats.get('killLightShip', 0)) +
                int(stats.get('killLargeCargoShip', 0)) +
                int(stats.get('killDestroyerShip', 0)) +
                int(stats.get('killSubmarine', 0))
            )
            cumulative['ship_kills'] += ships
            
            # Deaths
            cumulative['deaths'] += int(stats.get('deaths', 0))
            
            # Total kills (air + ground + sea)
            cumulative['total_kills'] = (
                cumulative['total_air_kills'] + 
                cumulative['ground_kills'] + 
                cumulative['ship_kills']
            )
            
            # Flight time
            cumulative['total_flight_time'] += int(stats.get('totalFlightTime', 0))
            cumulative['flight_time_hours'] = cumulative['total_flight_time'] / 3600
            
            # Score
            cumulative['total_score'] += int(stats.get('score', 0))
        
        # Convert flight time to hours
        cumulative['flight_time_hours'] = cumulative['total_flight_time'] / 3600
        
        return cumulative
    
    def get_mission_date(self, campaign_name: str, mission_num: str) -> Optional[str]:
        """Get the date for a specific mission (case-insensitive campaign lookup)"""
        # Case-insensitive lookup
        campaign_name_lower = campaign_name.lower()
        if campaign_name_lower not in self.mission_dates_lower:
            return None
        
        original_name, campaign_data = self.mission_dates_lower[campaign_name_lower]
        missions = campaign_data.get('missions', {})
        
        if mission_num in missions:
            mission_data = missions[mission_num]
            # Defensive: check if it's a dict
            if isinstance(mission_data, dict):
                return mission_data.get('normalized_date')
            else:
                print(f"    Warning: mission_data for {campaign_name}/{mission_num} is {type(mission_data)}: {mission_data}")
                return None
        
        return None
    
    def check_awards(self, country: str, cumulative_stats: Dict,
                    per_mission_stats: Dict, completed_missions: List[str],
                    campaign_name: str, debriefing_wounds: Dict = None) -> List[Dict]:
        """
        Check which awards have been earned - mission by mission
        
        Args:
            debriefing_wounds: Dict mapping mission_id -> wounded (True/False)
                               Based on actual damage taken in debriefings
        
        Returns:
            List of award events
        """
        if debriefing_wounds is None:
            debriefing_wounds = {}
        
        if country not in self.config['awards']:
            return []
        
        awards_config = self.config['awards'][country]
        earned_awards = []
        already_earned = []  # Track what's been earned so far
        earned_this_mission = []  # Track what was just earned this mission
        
        # Track running statistics
        running_stats = {
            'air_combat_score': 0,
            'total_air_kills': 0,
            'missions_completed': 0,
            'flight_time_hours': 0,
            'deaths': 0,
            'total_score': 0,
            'ground_kills': 0,
            'tank_kills': 0,
            'ship_kills': 0,
            'total_kills': 0  # air + ground + ship
        }
        
        # Add starting rank (before first mission)
        ranks = self.config['ranks'].get(country, [])
        if ranks:
            # Get starting rank offset from campaign_mission_dates.json
            starting_rank_offset = 0
            # New JSON structure: campaigns are at root level (no 'campaigns' wrapper)
            if campaign_name in self.mission_dates and campaign_name != 'game_directory':
                campaign_data = self.mission_dates[campaign_name]
                starting_rank_offset = campaign_data.get('starting_rank_offset', 0)
                # Clamp to valid range
                starting_rank_offset = max(0, min(starting_rank_offset, len(ranks) - 1))
            
            starting_rank = ranks[starting_rank_offset]  # Use configured offset
            # Get date of first mission or use placeholder
            first_mission = sorted(completed_missions, key=smart_mission_sort_key)[0]
            first_mission_date = self.get_mission_date(campaign_name, first_mission)
            
            earned_awards.append({
                'type': 'promotion',
                'rank': starting_rank['name'],
                'image': starting_rank['image'],
                'mission': 'Initial',
                'date': first_mission_date  # Same date as first mission
            })
        
        # Add Pilot's Badge/Emblem (before first mission)
        # For USSR: Choose between Badge (early) and Emblem (late) based on first mission date
        first_mission = sorted(completed_missions, key=smart_mission_sort_key)[0]
        first_mission_date = self.get_mission_date(campaign_name, first_mission)
        
        for award in awards_config:
            # Check if this is a pilot's badge/emblem
            is_pilots_award = (
                "Pilot's Badge" in award['name'] or 
                "Aviation Badge" in award['name'] or
                "Aviation Emblem" in award['name'] or
                "pilots_badge" in award.get('image', '') or
                "pilots_emblem" in award.get('image', '')
            )
            
            if is_pilots_award:
                # For Soviet Union, choose based on date
                if country == 'Soviet Union':
                    # Check if campaign starts before or after transition
                    if first_mission_date and first_mission_date >= "1943-01-06":
                        # Late period - use Aviation Emblem
                        if "Emblem" in award['name'] or "emblem" in award.get('image', ''):
                            earned_awards.append({
                                'type': 'award',
                                'name': award['name'],
                                'image': award['image'],
                                'mission': 'Initial',
                                'date': first_mission_date
                            })
                            already_earned.append(award['name'])
                            break
                    else:
                        # Early period - use Aviation Badge
                        if "Badge" in award['name'] or "badge" in award.get('image', ''):
                            earned_awards.append({
                                'type': 'award',
                                'name': award['name'],
                                'image': award['image'],
                                'mission': 'Initial',
                                'date': first_mission_date
                            })
                            already_earned.append(award['name'])
                            break
                else:
                    # For other countries, just use first match
                    earned_awards.append({
                        'type': 'award',
                        'name': award['name'],
                        'image': award['image'],
                        'mission': 'Initial',
                        'date': first_mission_date
                    })
                    already_earned.append(award['name'])
                    break  # Only one pilot's badge
        
        # Process missions in order
        for mission_num in sorted(completed_missions, key=smart_mission_sort_key):
            if mission_num not in per_mission_stats:
                continue
            
            mission_stats = per_mission_stats[mission_num]
            earned_this_mission = []  # Reset for new mission
            
            # Update running statistics (static planes count as 0.5)
            light = int(mission_stats.get('killLightPlane', 0))
            medium = int(mission_stats.get('killMediumPlane', 0))
            heavy = int(mission_stats.get('killHeavyPlane', 0))
            static = int(mission_stats.get('killStaticPlane', 0))
            
            running_stats['air_combat_score'] += light + medium + (static * 0.5) + (heavy * 2)
            running_stats['total_air_kills'] += light + medium + heavy + (static * 0.5)
            running_stats['missions_completed'] += 1
            running_stats['flight_time_hours'] += int(mission_stats.get('totalFlightTime', 0)) / 3600
            running_stats['deaths'] += int(mission_stats.get('deaths', 0))
            running_stats['total_score'] += int(mission_stats.get('score', 0))
            
            # Ground kills
            ground = (
                int(mission_stats.get('killTransportVehicle', 0)) +
                int(mission_stats.get('killLightArmoredVehicle', 0)) +
                int(mission_stats.get('killMediumArmoredVehicle', 0)) +
                int(mission_stats.get('killHeavyArmoredVehicle', 0)) +
                int(mission_stats.get('killCannon', 0)) +
                int(mission_stats.get('killAAAGun', 0)) +
                int(mission_stats.get('killMachinegun', 0)) +
                int(mission_stats.get('killRocketLauncher', 0)) +
                int(mission_stats.get('killRailroadCarriage', 0)) +
                int(mission_stats.get('killLocomotive', 0)) +
                int(mission_stats.get('killRailroadStation', 0)) +
                int(mission_stats.get('killBridge', 0)) +
                int(mission_stats.get('killFacility', 0)) +
                int(mission_stats.get('killRadar', 0)) +
                int(mission_stats.get('killSearchlight', 0)) +
                int(mission_stats.get('killResidentalBuilding', 0))
            )
            running_stats['ground_kills'] += ground
            
            # Tank kills
            tanks = (
                int(mission_stats.get('killLightArmoredVehicle', 0)) +
                int(mission_stats.get('killMediumArmoredVehicle', 0)) +
                int(mission_stats.get('killHeavyArmoredVehicle', 0))
            )
            running_stats['tank_kills'] += tanks
            
            # Ship kills
            ships = (
                int(mission_stats.get('killLightShip', 0)) +
                int(mission_stats.get('killLargeCargoShip', 0)) +
                int(mission_stats.get('killDestroyerShip', 0)) +
                int(mission_stats.get('killSubmarine', 0))
            )
            running_stats['ship_kills'] += ships
            
            # Total kills (air + ground + sea)
            running_stats['total_kills'] = (
                running_stats['total_air_kills'] + 
                running_stats['ground_kills'] + 
                running_stats['ship_kills']
            )
            
            # Check each award
            for award in awards_config:
                award_name = award['name']
                max_awards = award.get('max_awards', 1)
                
                # Handle unlimited awards (max_awards: null)
                if max_awards is not None:
                    # Check if max awards already reached for this award
                    award_count = already_earned.count(award_name)
                    if award_count >= max_awards:
                        continue  # Already earned maximum times
                
                # Check prerequisites - must have been earned BEFORE this mission
                # (not on this mission - prevents chaining)
                requires = award.get('requires')
                if requires:
                    if requires not in already_earned:
                        continue  # Don't have prerequisite at all
                    if requires in earned_this_mission:
                        continue  # Prerequisite earned THIS mission - wait for next mission
                
                # Check mutual exclusivity (e.g., USSR wound stripes)
                mutually_exclusive = award.get('mutually_exclusive_with')
                if mutually_exclusive:
                    if mutually_exclusive in earned_this_mission:
                        continue  # Mutually exclusive award already earned this mission
                
                # Check if per-sortie award
                if award.get('per_sortie'):
                    # Check THIS mission only (static planes count as 0.5)
                    mission_kills = light + medium + heavy + (static * 0.5)
                    wounded = int(mission_stats.get('deaths', 0)) > 0
                    
                    award_earned = False
                    conditions = award.get('conditions', [])
                    
                    for condition in conditions:
                        if 'air_kills_in_sortie' in condition:
                            if mission_kills >= condition['air_kills_in_sortie']:
                                award_earned = True
                                break
                        
                        if 'air_kills_wounded_sortie' in condition:
                            if mission_kills >= condition['air_kills_wounded_sortie'] and wounded:
                                award_earned = True
                                break
                        
                        if 'wounded_this_sortie' in condition:
                            # Check if wounded in THIS mission only
                            if wounded:
                                award_earned = True
                                break
                    
                    # Check random threshold (if specified)
                    if award_earned and ('random_threshold' in award or 'random_threshold_min' in award):
                        import random
                        # Seed with campaign + mission + award name for deterministic AND unique results
                        random.seed(f"{campaign_name}_{mission_num}_{award_name}")
                        random_roll = random.randint(0, 999)
                        
                        # Standard threshold: RND < X (e.g., RND<800 = 80% chance)
                        if 'random_threshold' in award:
                            if random_roll >= award['random_threshold']:
                                award_earned = False  # Failed random check
                        
                        # Minimum threshold: RND >= X (e.g., RND>=800 = 20% chance)
                        if 'random_threshold_min' in award:
                            if random_roll < award['random_threshold_min']:
                                award_earned = False  # Failed random check
                    
                    if award_earned:
                        # Store award with tier for later filtering
                        award_tier = award.get('award_tier', 999)  # Default = lowest priority
                        mission_date = self.get_mission_date(campaign_name, mission_num)
                        earned_this_mission.append({
                            'name': award_name,
                            'award': award,
                            'tier': award_tier,
                            'mission': mission_num,
                            'date': mission_date
                        })
                
                else:
                    # Check rank index requirements
                    # Get ranks for this country
                    current_rank_idx = 0
                    if country in self.config.get('ranks', {}):
                        ranks = self.config['ranks'][country]
                        # Find current rank based on score
                        for idx, rank in enumerate(ranks):
                            if running_stats.get('total_score', 0) >= rank['score']:
                                current_rank_idx = idx
                    
                    # Check minimum rank requirement
                    if 'requires_rank_index' in award or 'min_rank_index' in award:
                        required_min = award.get('requires_rank_index', award.get('min_rank_index', 0))
                        if current_rank_idx < required_min:
                            continue  # Don't have required minimum rank yet
                    
                    # Check maximum rank requirement (for NCO-only awards)
                    if 'max_rank_index' in award:
                        required_max = award['max_rank_index']
                        if current_rank_idx > required_max:
                            continue  # Rank too high for this award
                    
                    # Check cumulative stats OR graduated random
                    award_granted = False
                    
                    # First check graduated random kills (British DFM/DFC style)
                    if 'graduated_random_kills' in award:
                        import random
                        random.seed(f"{campaign_name}_{mission_num}_{award_name}")
                        random_roll = random.randint(0, 999)
                        
                        total_kills = running_stats.get('total_air_kills', 0)
                        graduated_thresholds = award['graduated_random_kills']
                        
                        # Check if any kill threshold passes the random check
                        for kill_count, rnd_threshold in sorted(graduated_thresholds.items(), reverse=True):
                            if total_kills >= kill_count and random_roll < rnd_threshold:
                                award_granted = True
                                break
                    
                    # OR check normal conditions (missions/flight time)
                    if not award_granted and self.check_award_conditions_with_stats(award, running_stats, debriefing_wounds):
                        award_granted = True
                    
                    # If no graduated_random_kills, just check normal conditions
                    if 'graduated_random_kills' not in award:
                        award_granted = self.check_award_conditions_with_stats(award, running_stats, debriefing_wounds)
                    
                    if award_granted:
                        # Check standard random thresholds
                        if 'random_threshold' in award or 'random_threshold_min' in award:
                            import random
                            random.seed(f"{campaign_name}_{mission_num}_{award_name}")
                            random_roll = random.randint(0, 999)
                            
                            # Standard threshold: RND < X
                            if 'random_threshold' in award:
                                if random_roll >= award['random_threshold']:
                                    award_granted = False
                            
                            # Minimum threshold: RND >= X
                            if 'random_threshold_min' in award:
                                if random_roll < award['random_threshold_min']:
                                    award_granted = False
                        
                        if award_granted:
                            mission_date = self.get_mission_date(campaign_name, mission_num)
                            # Store award with tier info for cumulative awards too
                            award_tier = award.get('award_tier', 999)
                            earned_this_mission.append({
                                'name': award_name,
                                'award': award,
                                'tier': award_tier,
                                'type': 'award',
                                'mission': mission_num,
                                'date': mission_date
                            })
            
            # TIER FILTERING: Process ALL tiered awards (both per-sortie and cumulative)
            # Keep only highest tier per mission to prevent multiple awards for same achievement
            tiered_awards_this_mission = [e for e in earned_this_mission if isinstance(e, dict) and 'tier' in e]
            regular_awards_this_mission = [e for e in earned_this_mission if isinstance(e, str)]
            
            if tiered_awards_this_mission:
                # Find highest tier (lowest number = highest priority)
                # Tier 1 = Hero/Medal of Honor, Tier 2 = Red Banner/DSC, etc.
                highest_tier = min(e['tier'] for e in tiered_awards_this_mission)
                
                # Keep only awards at highest tier
                kept_award_names = []
                for tiered_award in tiered_awards_this_mission:
                    if tiered_award['tier'] == highest_tier:
                        # Add to final list
                        earned_awards.append({
                            'type': 'award',
                            'name': tiered_award['name'],
                            'image': tiered_award['award']['image'],
                            'mission': tiered_award['mission'],
                            'date': tiered_award['date']
                        })
                        already_earned.append(tiered_award['name'])
                        kept_award_names.append(tiered_award['name'])
                
                # Update earned_this_mission for prerequisite checking next mission
                earned_this_mission = kept_award_names + regular_awards_this_mission
            else:
                # No tiered awards, process regular awards normally
                for regular_award in regular_awards_this_mission:
                    # These were already added to earned_awards in the loop above
                    pass
                    
        # === 🩸 WOUND BADGE SYSTEM (Cumulative, YAML-driven) ===
                    
        if country in self.config.get('awards', {}):
            # Dynamisch: finde alle Awards, die Verwundungen als Bedingung haben
            wound_awards = []
            for a in self.config['awards'][country]:
                for cond in a.get('conditions', []):
                    if 'deaths' in cond or 'wounded_in_sortie' in cond or 'wounded_this_sortie' in cond:
                        wound_awards.append(a)
                        break

            if wound_awards:
                cumulative_wounds = sum(1 for w in debriefing_wounds.values() if w)

                for award in wound_awards:
                    for condition in award.get('conditions', []):
                        if 'deaths' in condition or 'wounded_in_sortie' in condition:
                            required_wounds = condition.get('deaths') or condition.get('wounded_in_sortie')
                            if cumulative_wounds >= required_wounds and award['name'] not in already_earned:
                                last_mission = sorted(completed_missions, key=smart_mission_sort_key)[-1]
                                mission_date = self.get_mission_date(campaign_name, last_mission)

                                earned_awards.append({
                                    'type': 'award',
                                    'name': award['name'],
                                    'image': award['image'],
                                    'mission': last_mission,
                                    'date': mission_date
                                })
                                already_earned.append(award['name'])
                                print(f"  ✓ Awarded {award['name']} after {cumulative_wounds} wounds")

        
        return earned_awards
    
    def check_award_conditions_with_stats(self, award: Dict, stats: Dict, debriefing_wounds: Dict = None) -> bool:
        """
        Check if award conditions are met (OR logic) with specific stats dict.
        Supports 'deaths' in YAML as an alias for cumulative wounds from debriefings.
        """
        conditions = award.get('conditions', [])
        if debriefing_wounds is None:
            debriefing_wounds = {}

        # Count total wounds from debriefings (most accurate)
        cumulative_wounds = sum(1 for w in debriefing_wounds.values() if w)

        for condition in conditions:
            for stat_name, threshold in condition.items():
                # Treat 'deaths' as wounds (for legacy YAML)
                if stat_name == 'deaths':
                    if cumulative_wounds >= threshold:
                        return True
                else:
                    stat_value = stats.get(stat_name, 0)
                    if stat_value >= threshold:
                        return True  # OR logic – any condition triggers

        return False
    
    def find_mission_for_award(self, campaign_name: str, award: Dict,
                               missions: List[str], per_mission_stats: Dict) -> Optional[Dict]:
        """Find which mission an award was earned on"""
        # Simplified: Use last mission for now
        # TODO: Implement proper tracking of when conditions were met
        last_mission = sorted(missions, key=smart_mission_sort_key)[-1]
        mission_date = self.get_mission_date(campaign_name, last_mission)
        
        return {
            'mission': last_mission,
            'date': mission_date
        }
    
    def generate_events_for_campaign(self, campaign_name: str) -> List[Dict]:
        """Generate all events (promotions + awards) for a campaign"""
        
        # Check if campaign has save data
        if campaign_name not in self.save_data:
            return []
        
        campaign_data = self.save_data[campaign_name]
        
        # Check if any missions completed
        completed = campaign_data.get('completedMissionsByFileName', {})
        if not completed:
            return []
        
        # Get country (case-insensitive lookup)
        campaign_name_lower = campaign_name.lower()
        if campaign_name_lower not in self.mission_dates_lower:
            print(f"  Warning: No mission dates found for {campaign_name}")
            return []
        
        # Get original campaign name and data from mission_dates
        original_name, mission_data = self.mission_dates_lower[campaign_name_lower]
        country = mission_data.get('country')
        if not country:
            print(f"  Warning: No country detected for {campaign_name}")
            return []
        
        print(f"\nProcessing: {campaign_name} ({country})")
        print(f"  Missions completed: {len(completed)}")
        
        # STEP 1: Load debriefing data FIRST (for accurate wound counting)
        debriefing_wounds = {}  # mission_id -> True/False
        if self.log_processor:
            try:
                completed_missions_list = list(completed.keys())
                debriefings = self.log_processor.get_all_debriefings(campaign_name, completed_missions_list)
                
                for mission_id, data in debriefings.items():
                    # Check if wounded (using threshold > 0.2)
                    wounded = data['summary'].get('wounded', False)
                    debriefing_wounds[mission_id] = wounded
                
                if debriefing_wounds:
                    wound_count = sum(1 for w in debriefing_wounds.values() if w)
                    print(f"  Debriefings loaded: {len(debriefings)} missions, {wound_count} wounded")
            except Exception as e:
                print(f"  Warning: Could not load debriefings: {e}")
        
        try:
            # Calculate statistics
            per_mission_stats = campaign_data.get('characterStatisticsByFileName', {})
            cumulative_stats = self.calculate_cumulative_stats(per_mission_stats)
            
            print(f"  Total score: {cumulative_stats['total_score']}")
            print(f"  Air kills: {cumulative_stats['total_air_kills']}")
            print(f"  Air combat score: {cumulative_stats['air_combat_score']}")
            
            # Show rank scaling info
            scale_factor = self.get_rank_scaling_factor(campaign_name)
            if scale_factor != 1.0:
                mission_count = len(completed)
                print(f"  Rank scaling: {scale_factor}x (campaign length: {mission_count} missions)")
            
            events = []
            
            # Check promotions
            completed_missions = list(completed.keys())
            promotions = self.check_rank_promotions_v2(
                campaign_name, country, per_mission_stats, completed_missions
            )
            events.extend(promotions)
            
            # Check awards (pass debriefing wounds for accurate wound counting)
            awards = self.check_awards(
                country, cumulative_stats, per_mission_stats, 
                completed_missions, campaign_name, debriefing_wounds
            )
            events.extend(awards)
            
            # Sort chronologically by mission DATE (not just number)
            def sort_key(event):
                # Initial events (starting rank, pilot's badge) come first
                if event['mission'] == 'Initial':
                    mission_sort = ("0000-00-00", "0", "")  # Before all missions - all strings!
                else:
                    # Try to get actual mission date for proper chronological order
                    mission_date = self.get_mission_date(campaign_name, event['mission'])
                    if mission_date:
                        # Parse date for sorting (YYYY-MM-DD format)
                        try:
                            # Handle both formats: "1941-06-22" and "22.6.1941"
                            if '-' in mission_date and len(mission_date) == 10 and mission_date[0].isdigit():
                                # ISO format YYYY-MM-DD
                                mission_sort = (mission_date, "0", "")  # String "0" for priority
                            else:
                                # DD.MM.YYYY format or D.M.YYYY - convert to YYYY-MM-DD
                                parts = mission_date.split('.')
                                if len(parts) == 3:
                                    # Pad day and month with zeros
                                    date_str = f"{parts[2].zfill(4)}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                                    mission_sort = (date_str, "0", "")
                                else:
                                    # Fallback to mission number as string (padded)
                                    mission_num_str = event['mission'].zfill(10)
                                    mission_sort = ("9999-99-99", "1", mission_num_str)
                        except:
                            # Fallback to mission number as string
                            mission_num_str = event['mission'].zfill(10)
                            mission_sort = ("9999-99-99", "1", mission_num_str)
                    else:
                        # No date available - use mission number as string
                        mission_num_str = event['mission'].zfill(10)
                        mission_sort = ("9999-99-99", "1", mission_num_str)
                
                # Type order: promotion=0, award=1 (promotions first on same day)
                type_order = 0 if event['type'] == 'promotion' else 1
                score = event.get('score', 0)
                return (*mission_sort, type_order, score)
            
            events.sort(key=sort_key)
            
            print(f"  Generated {len(events)} events ({len(promotions)} promotions, {len(awards)} awards)")
            
            return events
            
        except Exception as e:
            print(f"  ERROR in {campaign_name}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_rank_scaling_factor(self, campaign_name: str) -> float:
        """
        Get rank scaling factor based on campaign length
        
        Args:
            campaign_name: Campaign name
            
        Returns:
            Scaling factor (1.0 = no scaling, 2.0 = double requirements, etc.)
        """
        # Check if scaling is enabled
        rank_scaling = self.config.get('rank_scaling', {})
        if not rank_scaling.get('enabled', True):
            return 1.0  # Scaling disabled
        
        # Get total mission count for this campaign
        campaign_name_lower = campaign_name.lower()
        if campaign_name_lower not in self.mission_dates_lower:
            return 1.0  # Unknown campaign, use default
        
        _, mission_data = self.mission_dates_lower[campaign_name_lower]
        mission_count = mission_data.get('mission_count', 0)
        
        if mission_count == 0:
            return 1.0  # No missions, use default
        
        # Get factors from config
        factors = rank_scaling.get('factors', {})
        
        # Parse all brackets dynamically and find matching one
        matching_factor = 1.0  # Default if no bracket matches
        
        for bracket_str, factor in factors.items():
            # Parse bracket string (e.g., "11-20", "71+", "5")
            bracket_str = str(bracket_str).strip()
            
            try:
                if '+' in bracket_str:
                    # Format: "71+" means 71 and above
                    min_val = int(bracket_str.replace('+', '').strip())
                    if mission_count >= min_val:
                        matching_factor = float(factor)
                        # Don't break - continue to find highest matching bracket
                
                elif '-' in bracket_str:
                    # Format: "11-20" means 11 to 20 inclusive
                    parts = bracket_str.split('-')
                    if len(parts) == 2:
                        min_val = int(parts[0].strip())
                        max_val = int(parts[1].strip())
                        if min_val <= mission_count <= max_val:
                            matching_factor = float(factor)
                            break  # Found exact match
                
                else:
                    # Format: "10" means exactly 10
                    exact_val = int(bracket_str)
                    if mission_count == exact_val:
                        matching_factor = float(factor)
                        break  # Found exact match
            
            except (ValueError, TypeError):
                # Invalid bracket format, skip it
                print(f"  Warning: Invalid rank_scaling bracket format: '{bracket_str}'")
                continue
        
        return matching_factor
    
    def check_rank_promotions_v2(self, campaign_name: str, country: str,
                                  per_mission_stats: Dict, missions: List[str]) -> List[Dict]:
        """Check rank promotions mission by mission - only ONE rank per mission"""
        if country not in self.config['ranks']:
            return []
        
        ranks = self.config['ranks'][country]
        promotions = []
        running_score = 0
        
        # Get starting rank offset from campaign_mission_dates.json
        starting_rank_offset = 0
        # New JSON structure: campaigns are at root level (no 'campaigns' wrapper)
        if hasattr(self, 'mission_dates') and campaign_name in self.mission_dates and campaign_name != 'game_directory':
            campaign_data = self.mission_dates[campaign_name]
            starting_rank_offset = campaign_data.get('starting_rank_offset', 0)
            # Clamp to valid range
            starting_rank_offset = max(0, min(starting_rank_offset, len(ranks) - 1))
        
        current_rank_index = starting_rank_offset  # Start at configured rank
        
        # Get rank scaling factor based on campaign length
        scale_factor = self.get_rank_scaling_factor(campaign_name)
        
        for mission_num in sorted(missions, key=smart_mission_sort_key):
            if mission_num not in per_mission_stats:
                continue
            
            mission_score = int(per_mission_stats[mission_num].get('score', 0))
            running_score += mission_score
            
            # Check if we've reached next rank (only ONE promotion per mission)
            if current_rank_index < len(ranks) - 1:
                next_rank = ranks[current_rank_index + 1]
                # Apply scaling factor to FULL rank requirement (not reduced by starting rank)
                required_score = int(next_rank['score'] * scale_factor)
                
                if running_score >= required_score:
                    # Promotion!
                    current_rank_index += 1
                    mission_date = self.get_mission_date(campaign_name, mission_num)
                    
                    promotions.append({
                        'type': 'promotion',
                        'rank': next_rank['name'],
                        'image': next_rank['image'],
                        'mission': mission_num,
                        'date': mission_date,
                        'score': running_score
                    })
        
        return promotions
    
    def image_to_base64(self, image_path: str, rotate: bool = False) -> str:
        """
        Convert image to base64 for embedding in PDF
        Supports PNG and DDS formats (converts DDS to PNG on-the-fly)
        
        Args:
            image_path: Relative path to image (e.g., "CampaignRanksAwards/Germany/medal.png")
            rotate: If True, rotate image 90° counter-clockwise before encoding
            
        Returns:
            Base64 data URI or original path if conversion fails
        """
        import base64
        
        if not self.game_directory:
            return image_path
        
        # Construct full path - images are in data/swf/ directory!
        full_path = Path(self.game_directory) / "data" / "swf" / image_path
        
        # Check for both .png and .dds extensions
        if not full_path.exists():
            # Try .dds if .png doesn't exist
            if full_path.suffix.lower() == '.png':
                dds_path = full_path.with_suffix('.dds')
                if dds_path.exists():
                    full_path = dds_path
                else:
                    print(f"  ⚠️  Image not found: {full_path} (also tried .dds)")
                    return image_path
            else:
                print(f"  ⚠️  Image not found: {full_path}")
                return image_path
        
        try:
            ext = full_path.suffix.lower()
            
            # Handle DDS files - convert to PNG
            if ext == '.dds':
                try:
                    from PIL import Image
                    
                    # Open DDS file with PIL
                    img = Image.open(full_path)
                    
                    # Rotate if requested (before converting to PNG)
                    if rotate:
                        img = img.rotate(90, expand=True)  # 90° counter-clockwise
                    
                    # Convert to PNG in memory
                    from io import BytesIO
                    png_buffer = BytesIO()
                    img.save(png_buffer, format='PNG')
                    img_data = png_buffer.getvalue()
                    mime_type = 'image/png'
                    
                except ImportError:
                    print(f"  ⚠️  PIL not available, cannot convert DDS: {full_path.name}")
                    return image_path
                except Exception as e:
                    print(f"  ⚠️  Failed to convert DDS {full_path.name}: {e}")
                    return image_path
            
            # Handle regular image files (PNG, JPG, etc)
            else:
                # If rotation needed, load with PIL
                if rotate:
                    try:
                        from PIL import Image
                        from io import BytesIO
                        
                        img = Image.open(full_path)
                        img = img.rotate(90, expand=True)  # 90° counter-clockwise
                        
                        png_buffer = BytesIO()
                        img.save(png_buffer, format='PNG')
                        img_data = png_buffer.getvalue()
                        mime_type = 'image/png'
                        
                    except ImportError:
                        print(f"  ⚠️  PIL not available, cannot rotate image: {full_path.name}")
                        # Fallback: read without rotation
                        with open(full_path, 'rb') as f:
                            img_data = f.read()
                        mime_types = {
                            '.png': 'image/png',
                            '.jpg': 'image/jpeg',
                            '.jpeg': 'image/jpeg',
                            '.gif': 'image/gif'
                        }
                        mime_type = mime_types.get(ext, 'image/png')
                    except Exception as e:
                        print(f"  ⚠️  Failed to rotate image {full_path.name}: {e}")
                        # Fallback: read without rotation
                        with open(full_path, 'rb') as f:
                            img_data = f.read()
                        mime_types = {
                            '.png': 'image/png',
                            '.jpg': 'image/jpeg',
                            '.jpeg': 'image/jpeg',
                            '.gif': 'image/gif'
                        }
                        mime_type = mime_types.get(ext, 'image/png')
                else:
                    # No rotation needed, read directly
                    with open(full_path, 'rb') as f:
                        img_data = f.read()
                    
                    # Determine MIME type
                    mime_types = {
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.gif': 'image/gif'
                    }
                    mime_type = mime_types.get(ext, 'image/png')
            
            # Convert to base64
            b64_data = base64.b64encode(img_data).decode('utf-8')
            
            return f"data:{mime_type};base64,{b64_data}"
            
        except Exception as e:
            print(f"  ⚠️  Failed to convert image {image_path}: {e}")
            return image_path
    
    def rank_needs_rotation(self, event: Dict, country: str, country_folder: str = None) -> bool:
        """
        Determine if a rank image needs to be rotated 90° counter-clockwise
        
        Args:
            event: Event dictionary
            country: Country name
            country_folder: Country folder path (e.g., "USSR/late", "Germany")
            
        Returns:
            True if image should be rotated
        """
        # Only rotate promotions (not awards)
        if event.get('type') != 'promotion':
            return False
        
        image_name = event.get('image', '').lower()
        
        # DEBUG: Print what we're checking
        # print(f"DEBUG: Checking rotation for {country}/{country_folder}/{image_name}")
        
        # Define which ranks need rotation (based on user requirements)
        ranks_to_rotate = {
            'Germany': [
                # ALL German ranks need rotation
                'unteroffizier.png',
                'oberstleutnant.png',
                'oberleutnant.png',
                'oberfeldwebel.png',
                'major.png',
                'leutnant.png',
                'hauptmann.png',
                'feldwebel.png',
                'generalleutnant.png',
                'generalmajor.png',
                'generalfeldmarschall.png',
                'generaloberst.png',
                'oberst.png',
                'stabsfeldwebel.png',
                'gefreiter.png',
            ],
            'Britain': [
                # Only these 5 British ranks
                'flight_lieutenant.png',
                'flying_officer.png',
                'pilot_officer.png',
                'squadron_leader.png',
                'wing_commander.png',
            ],
            'US': [  # NOTE: Changed from 'USA' to 'US' to match country_folder!
                # All US ranks EXCEPT first_sergeant.png
                'second_lieutenant.png',
                'major_usaaf.png',
                'lt_colonel.png',
                'flight_officer.png',
                # 'first_sergeant.png',  # ← NOT rotated!
                'first_lieutenant.png',
                'chief_warrant_officer.png',
                'captain_usaaf.png',
                'brigadier_general.png',
                'colonel.png',
                'major_general.png',
                'lieutenant_general.png',
                'general.png',
                'master_sergeant.png',
                'technical_sergeant.png',
                'staff_sergeant.png',
            ],
            'USSR/late': [
                # ALL USSR/late ranks need rotation
                'sub_colonel.png',
                'sergeant_vvs.png',
                'senior_sergeant.png',
                'senior_lieutenant.png',
                'major_vvs.png',
                'lieutenant_vvs.png',
                'junior_lieutenant.png',
                'captain_vvs.png',
                'colonel_vvs.png',
                'major_general_vvs.png',
                'lieutenant_general_vvs.png',
                'general_vvs.png',
                'marshal_vvs.png',
            ],
            # USSR/early: NONE - not in dictionary, so will return False
        }
        
        # For Soviet Union, use the country_folder to determine early/late
        if country == 'Soviet Union':
            if country_folder == 'USSR/late':
                country_key = 'USSR/late'
            else:
                # USSR/early - no rotations
                return False
        else:
            country_key = country_folder or country
        
        # Check if this rank should be rotated
        country_ranks = ranks_to_rotate.get(country_key, [])
        should_rotate = image_name in [r.lower() for r in country_ranks]
        
        # DEBUG: Print result
        # print(f"DEBUG: country_key={country_key}, should_rotate={should_rotate}")
        
        return should_rotate
    
    def format_event_html(self, event: Dict, country: str, for_pdf: bool = False) -> str:
        """Format a single event as HTML
        
        Args:
            event: Event dictionary
            country: Country name
            for_pdf: If True, embed images as base64 for PDF compatibility
        """
        
        # Get image path with special handling for Soviet Union (early/late periods)
        country_folder_map = {
            'Germany': 'Germany',
            'Britain': 'Britain',
            'USA': 'US'
        }
        
        if country == 'Soviet Union':
            # Determine early vs late based on event date
            # Historical transition: 6 January 1943 (introduction of shoulder boards / погоны)
            event_date = event.get('date')
            
            if event_date and event_date >= "1943-01-06":
                country_folder = 'USSR/late'
            else:
                # Default to early if no date or before transition
                country_folder = 'USSR/early'
        else:
            country_folder = country_folder_map.get(country, country)
        
        image_path = f"CampaignRanksAwards/{country_folder}/{event['image']}"
        
        # Check if rank needs rotation
        needs_rotation = self.rank_needs_rotation(event, country, country_folder)
        
        # Convert to base64 if generating for PDF, with rotation if needed
        if for_pdf:
            image_src = self.image_to_base64(image_path, rotate=needs_rotation)
        else:
            # For in-game: Use Windows-style backslashes (IL-2 expects this)
            image_src = image_path.replace('/', '\\')
        
        # Format date
        if event.get('mission') == 'Initial':
            # Initial events (starting rank + pilot's badge)
            # Show date of first mission if available
            if event.get('date'):
                try:
                    date_obj = datetime.strptime(event['date'], '%Y-%m-%d')
                    date_str = date_obj.strftime('%d %B, %Y')
                except:
                    date_str = "Before First Mission"
            else:
                date_str = "Before First Mission"
        elif event.get('date'):
            try:
                date_obj = datetime.strptime(event['date'], '%Y-%m-%d')
                date_str = date_obj.strftime('%d %B, %Y')
            except:
                date_str = event['date']
        else:
            date_str = f"After Mission {event['mission']}"
        
        # Format description
        if event['type'] == 'promotion':
            if event.get('mission') == 'Initial':
                description = f"Started as {event['rank']}"
            else:
                description = f"Promoted to {event['rank']}"
        else:
            if event.get('mission') == 'Initial':
                description = f"Awarded {event['name']}"
            else:
                description = f"Awarded {event['name']}"
        
        # Apply rotation:
        # - For PDF: Image is rotated via PIL in image_to_base64()
        # - For in-game: NO rotation (IL-2's browser doesn't support it well)
        
        # DEBUG: Print what we're generating
        if for_pdf:
            # PDF: Better formatting with text before image and proper alignment
            result = f"• {date_str} - {description} <span style='display: inline-block; vertical-align: middle; margin-left: 5px;'><img src='{image_src}' style='vertical-align: middle;'></span><br>"
        else:
            # In-game: IL-2 expects unquoted src, image after text
            result = f"• {date_str} - {description} <img src={image_src}><br>"
            print(f"DEBUG HTML: {result[:150]}")  # First 150 chars
        
        return result
    
    
    def generate_debriefings_html(self, campaign_name: str, completed_missions: List[str]) -> tuple:
        """
        Generate Mission Debriefings HTML section
        
        Args:
            campaign_name: Campaign folder name
            completed_missions: List of completed mission IDs
            
        Returns:
            Tuple of (html_string, debriefings_dict)
        """
        if not self.log_processor:
            return ("", {})
        
        # Get debriefing data for all missions
        debriefings = self.log_processor.get_all_debriefings(campaign_name, completed_missions)
        
        if not debriefings:
            return ("", {})
        
        html_lines = ["<u>Mission Debriefings</u><br>", "<br>"]
        
        # Sort missions in order
        sorted_missions = sorted(debriefings.keys(), key=smart_mission_sort_key)
        
        for mission_id in sorted_missions:
            data = debriefings[mission_id]
            
            # DEBUG: Show which mission we're processing
            print(f"  Processing debriefing for Mission {mission_id}...")
            
            # Extract mission date and start time from .eng file
            mission_date, mission_start_time = self.extract_mission_datetime(campaign_name, mission_id)
            
            # Use mission date from .eng if available, otherwise show "No date"
            if mission_date:
                date_str = mission_date
            else:
                # No date in mission file - don't use timestamp!
                date_str = None  # Will skip date in header
            
            # Summary data
            aircraft = data['player']['aircraft']
            duration = data['summary']['flight_duration']
            status = data['summary']['final_state']
            aircraft_dmg = data['summary'].get('aircraft_damage', 0)
            pilot_dmg = data['summary'].get('pilot_damage', 0)
            
            # Kills summary
            air_kills = data['summary']['air_kills']
            air_kills_flying = data['summary'].get('air_kills_flying', air_kills)
            air_kills_parked = data['summary'].get('air_kills_parked', 0)
            ground_kills = data['summary']['ground_kills']
            naval_kills = data['summary']['naval_kills']
            
            # Mission header with box (wrapped in div to prevent page breaks)
            html_lines.append(f'<div class="mission-box">')
            html_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>")
            # Only show date if available (from mission file)
            if date_str:
                html_lines.append(f"<b>MISSION {mission_id} | {date_str}</b><br>")
            else:
                html_lines.append(f"<b>MISSION {mission_id}</b><br>")
            html_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>")
            
            # Summary line with status and damage
            summary_parts = [f"Aircraft: {aircraft}", f"Duration: {duration}", f"Status: {status}"]
            if aircraft_dmg > 0:
                summary_parts.append(f"Aircraft Dmg: {aircraft_dmg}%")
            if pilot_dmg > 0:
                summary_parts.append(f"Pilot Dmg: {pilot_dmg}%")
            html_lines.append(f"{' | '.join(summary_parts)}<br>")
            html_lines.append(f"<br>")
            
            # Combat results - show parked separately if present
            html_lines.append(f"<b>COMBAT RESULTS</b><br>")
            if air_kills_parked > 0:
                html_lines.append(f"Air: {air_kills} ({air_kills_flying} flying, {air_kills_parked} parked)  |  Ground: {ground_kills}  |  Naval: {naval_kills}<br>")
            else:
                html_lines.append(f"Air: {air_kills}  |  Ground: {ground_kills}  |  Naval: {naval_kills}<br>")
            html_lines.append(f"<br>")
            
            # Flight log with detailed events
            html_lines.append(f"<b>FLIGHT LOG</b><br>")
            
            # Check if player bailed out - suppress damage events after bailout
            # Use final_state from summary instead of tracking during loop
            mission_ended_in_bailout = "Bailout" in status
            
            for event in data.get('events', [])[:25]:  # Max 25 events
                time = event.get('time', '')
                event_type = event.get('type', event.get('event', ''))
                target = event.get('target', '')
                altitude = event.get('altitude')
                distance = event.get('distance')
                damage = event.get('damage')
                
                # Convert mission time to real time if we have start time
                display_time = time
                if mission_start_time and time:
                    try:
                        # Parse mission time (e.g., "00:23:45")
                        time_parts = time.split(':')
                        if len(time_parts) == 3:
                            hours, minutes, seconds = map(int, time_parts)
                            mission_duration = timedelta(hours=hours, minutes=minutes, seconds=seconds)
                            
                            # Parse start time (e.g., "09:45")
                            start_parts = mission_start_time.split(':')
                            if len(start_parts) == 2:
                                start_hour, start_min = map(int, start_parts)
                                start_dt = datetime(2000, 1, 1, start_hour, start_min)
                                
                                # Add mission duration to start time
                                real_time = start_dt + mission_duration
                                display_time = real_time.strftime('%H:%M:%S')  # Include seconds
                    except Exception:
                        # Fallback to mission time if conversion fails
                        pass
                
                # Format event based on type
                if event_type == "Kill":
                    # Kill event with altitude
                    details = []
                    if altitude is not None:
                        details.append(f"Alt: {altitude}m")
                    
                    detail_str = f" ({', '.join(details)})" if details else ""
                    # Don't truncate target name - show full type
                    html_lines.append(f"  {display_time}  {target} destroyed{detail_str}<br>")
                
                elif event_type == "Damage Taken":
                    # Skip ALL damage events if mission ended in bailout
                    if mission_ended_in_bailout:
                        continue
                    
                    # Normal damage event
                    details = []
                    
                    if damage:
                        details.append(damage)
                    if altitude is not None:
                        details.append(f"Alt: {altitude}m")
                    
                    detail_str = f" ({', '.join(details)})" if details else ""
                    html_lines.append(f"  {display_time}  Hit by {target}{detail_str}<br>")
                
                elif event_type == "Landing Damage":
                    # Landing damage (hard landing)
                    details = []
                    
                    if damage:
                        details.append(damage)
                    if altitude is not None:
                        details.append(f"Alt: {altitude}m")
                    
                    detail_str = f" ({', '.join(details)})" if details else ""
                    html_lines.append(f"  {display_time}  Landing damage{detail_str}<br>")
                
                elif event_type in ["Takeoff", "Landing", "Crash", "Bailout"]:
                    # Takeoff/Landing/Crash/Bailout with altitude
                    # Check if it's a hard landing
                    hard_landing = event.get('hard_landing', False)
                    event_label = f"{event_type} (Hard)" if hard_landing and event_type == "Landing" else event_type
                    
                    detail_str = f" ({altitude}m)" if altitude is not None else ""
                    html_lines.append(f"  {display_time}  {event_label}{detail_str}<br>")
                
                else:
                    # Other events
                    html_lines.append(f"  {display_time}  {event_type}<br>")
            
            html_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>")
            html_lines.append("</div>")  # Close mission-box
            html_lines.append("<br>")  # Spacing between missions
        
        return ("\n".join(html_lines), debriefings)
    
    def generate_events_html(self, events: List[Dict], country: str, for_pdf: bool = False) -> str:
        """Generate complete Events HTML section
        
        Args:
            events: List of event dictionaries
            country: Country name
            for_pdf: If True, use base64-embedded images for PDF compatibility
        """
        if not events:
            return ""
        
        html_lines = ["<u>Events</u><br>"]
        
        for event in events:
            html_lines.append(self.format_event_html(event, country, for_pdf=for_pdf))
        
        return "\n".join(html_lines)
    
    def update_campaign_info_file(self, campaign_name: str, events_html: str) -> bool:
        """
        Update campaign info.locale=eng.txt with Events section
        
        Args:
            campaign_name: Campaign folder name (e.g., 'kerch')
            events_html: Generated HTML for Events section
            
        Returns:
            True if successful, False otherwise
        """
        if not self.game_directory:
            print(f"  Error: No game directory configured")
            return False
        
        # Build path to info file
        info_file = Path(self.game_directory) / "data" / "Campaigns" / campaign_name / "info.locale=eng.txt"
        
        if not info_file.exists():
            print(f"  Warning: Info file not found: {info_file}")
            print(f"  (This is normal if campaign hasn't been started)")
            return False
        
        if self.dry_run:
            print(f"  [DRY RUN] Would update: {info_file}")
            return True
        
        try:
            # Create backup
            backup_file = info_file.with_suffix('.txt.backup')
            if not backup_file.exists():  # Only create backup if it doesn't exist
                shutil.copy(info_file, backup_file)
                print(f"  Created backup: {backup_file.name}")
            
            # Read existing content and detect encoding
            # Try different encodings
            content = None
            detected_encoding = None
            for encoding in ['utf-8', 'utf-16-le', 'utf-16-be', 'latin-1']:
                try:
                    with open(info_file, 'r', encoding=encoding) as f:
                        content = f.read()
                    detected_encoding = encoding
                    print(f"  Detected encoding: {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                print(f"  Error: Could not decode file with any encoding")
                return False
            
            # Check if Events section already exists
            # We need to be careful to preserve any content AFTER Events section
            # (could be modded campaigns with custom sections)
            
            # Strategy: Find and extract content in three parts:
            # 1. Before Mission Debriefings/Events
            # 2. Mission Debriefings + Events (we'll replace this)
            # 3. After Events (we'll preserve this)
            
            before_content = content
            after_events_content = ""
            
            # Step 1: Check for and remove Mission Debriefings section
            if '<u>Mission Debriefings</u>' in content:
                # Find where Mission Debriefings starts
                match = re.search(r'<u>Mission Debriefings</u>', content)
                if match:
                    before_content = content[:match.start()]
                    content_after_debriefings = content[match.start():]
                    
                    # Check if there's an Events section after Debriefings
                    if '<u>Events</u>' in content_after_debriefings:
                        # Find Events section
                        events_match = re.search(r'<u>Events</u>', content_after_debriefings)
                        if events_match:
                            # Check if there's content after Events that's NOT part of Events
                            content_after_events = content_after_debriefings[events_match.end():]
                            
                            # Look for next section marker (starts with <u>)
                            next_section = re.search(r'<br><br><u>[^<]+</u>', content_after_events)
                            if next_section:
                                after_events_content = content_after_events[next_section.start():]
                    else:
                        # No Events section, check for content after Debriefings
                        next_section = re.search(r'<br><br><u>[^<]+</u>', content_after_debriefings)
                        if next_section:
                            after_events_content = content_after_debriefings[next_section.start():]
                    
                    print(f"  Removed old Mission Debriefings section")
            
            # Step 2: Check for Events section (if no Debriefings section)
            elif '<u>Events</u>' in content:
                # Find where Events starts
                match = re.search(r'<u>Events</u>', content)
                if match:
                    before_content = content[:match.start()]
                    content_after_events = content[match.end():]
                    
                    # Look for next section marker
                    next_section = re.search(r'<br><br><u>[^<]+</u>', content_after_events)
                    if next_section:
                        after_events_content = content_after_events[next_section.start():]
                
                print(f"  Removed old Events section")

            # Cleanup trailing whitespace and <br> tags from before_content
            before_content = before_content.rstrip()
            while before_content.endswith('<br>'):
                before_content = before_content[:-4].rstrip()
            
            # Build new content: before + new events + after (if any)
            updated_content = before_content + '<br><br>' + events_html
            
            if after_events_content:
                # Preserve content that came after Events section
                updated_content += after_events_content
                print(f"  ✓ Preserved content after Events section")
            
            # Write updated content using SAME encoding as original
            # This prevents corruption of UTF-16 LE files (common in IL-2)
            with open(info_file, 'w', encoding=detected_encoding) as f:
                f.write(updated_content)
            
            print(f"  ✓ Updated: {info_file} (encoding: {detected_encoding})")
            return True
            
        except Exception as e:
            print(f"  Error updating file: {e}")
            return False
    
    def get_campaign_display_name(self, campaign_name: str) -> str:
        """
        Extract campaign display name from info.locale=eng.txt
        
        Args:
            campaign_name: Campaign folder name
            
        Returns:
            Display name from &name= field, or folder name as fallback
        """
        if not self.game_directory:
            return campaign_name
        
        campaign_path = Path(self.game_directory) / "data" / "Campaigns" / campaign_name
        info_file = campaign_path / "info.locale=eng.txt"
        
        if not info_file.exists():
            return campaign_name
        
        try:
            # Read file
            with open(info_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Look for &name="Campaign Display Name"
            # Can be with or without quotes
            match = re.search(r'&name\s*=\s*"([^"]+)"', content)
            if match:
                return match.group(1)
            
            # Try without quotes
            match = re.search(r'&name\s*=\s*([^\n&]+)', content)
            if match:
                return match.group(1).strip()
            
        except Exception as e:
            print(f"  ⚠️  Could not read campaign name: {e}")
        
        return campaign_name
    
    def generate_campaign_summary_html(self, campaign_name: str, events: List[Dict], 
                                       debriefings: Dict, country: str, cumulative_stats: Dict = None) -> str:
        """
        Generate campaign summary statistics for PDF
        
        Args:
            campaign_name: Campaign folder name
            events: List of events (awards, promotions)
            debriefings: Dict of mission debriefings
            country: Country code
            cumulative_stats: Cumulative statistics from campaigns_decoded.json (optional)
            
        Returns:
            HTML string for campaign summary
        """
        if not debriefings:
            return ""
        
        # Collect statistics
        total_air = 0
        total_ground = 0
        total_naval = 0
        total_flight_time_seconds = 0
        aircraft_usage = {}
        target_counts = {'air': {}, 'ground': {}, 'naval': {}}
        mission_count = len(debriefings)
        safe_landings = 0
        hard_landings = 0
        wounded_landings = 0
        bailouts = 0
        kia_mia = 0
        
        # Initialize parked kills counter
        total_air_parked = 0
        
        # Get parked kills from cumulative stats (campaigns_decoded.json)
        # These are kills that happened outside of debriefed missions
        if cumulative_stats:
            total_air_parked += cumulative_stats.get('static_plane_kills', 0)
        
        # Analyze all missions
        for mission_id, data in debriefings.items():
            summary = data.get('summary', {})
            player = data.get('player', {})
            
            # Combat stats (from summary)
            total_air += summary.get('air_kills', 0)
            total_ground += summary.get('ground_kills', 0)
            total_naval += summary.get('naval_kills', 0)
            
            # Add parked kills from this mission's debriefing
            total_air_parked += summary.get('air_kills_parked', 0)
            
            # Flight time (from summary)
            duration = summary.get('flight_duration', '')
            if duration and duration != 'N/A':
                try:
                    parts = duration.split(':')
                    if len(parts) == 3:
                        hours, minutes, seconds = map(int, parts)
                        total_flight_time_seconds += hours * 3600 + minutes * 60 + seconds
                except:
                    pass
            
            # Aircraft usage (from player)
            aircraft = player.get('aircraft', 'Unknown')
            if aircraft not in aircraft_usage:
                aircraft_usage[aircraft] = {'missions': 0, 'kills': 0}
            aircraft_usage[aircraft]['missions'] += 1
            aircraft_usage[aircraft]['kills'] += summary.get('air_kills', 0) + summary.get('ground_kills', 0) + summary.get('naval_kills', 0)
            
            # Landing status (from summary)
            status = summary.get('final_state', '').lower()
            # Priority: wounded > bailout > KIA/MIA > hard/crash > safe
            if 'wounded' in status:
                wounded_landings += 1
            elif 'bail' in status or 'bailed' in status:
                bailouts += 1
            elif 'kia' in status or 'mia' in status or 'killed' in status:
                kia_mia += 1
            elif 'hard' in status or 'crash' in status:
                hard_landings += 1
            elif 'landed' in status:
                safe_landings += 1
            
            # Target breakdown (from events)
            events_list = data.get('events', [])
            for event in events_list:
                # Get event type (try 'type' first, then 'event' as fallback)
                event_type = event.get('type', event.get('event', ''))
                
                if event_type == "Kill":
                    target = event.get('target', '')
                    # Categorize by target name patterns
                    target_lower = target.lower()
                    
                    # Naval targets
                    if any(naval in target_lower for naval in ['boat', 'ship', 'vessel', 'torpedo']):
                        category = 'naval'
                    # Ground targets  
                    elif any(ground in target_lower for ground in ['aa', 'gun', 'ml-20', 'dshk', '52-k', 'flak', 'tank', 'truck', 'artillery']):
                        category = 'ground'
                    # Air targets (default)
                    else:
                        category = 'air'
                    
                    if category == 'air':
                        target_counts['air'][target] = target_counts['air'].get(target, 0) + 1
                    elif category == 'ground':
                        target_counts['ground'][target] = target_counts['ground'].get(target, 0) + 1
                    elif category == 'naval':
                        target_counts['naval'][target] = target_counts['naval'].get(target, 0) + 1
        
        # Format flight time
        total_hours = total_flight_time_seconds // 3600
        total_minutes = (total_flight_time_seconds % 3600) // 60
        avg_seconds = total_flight_time_seconds // mission_count if mission_count > 0 else 0
        avg_minutes = avg_seconds // 60
        
        # Get campaign dates
        first_mission_date = None
        last_mission_date = None
        if campaign_name in self.mission_dates:
            mission_dates_dict = self.mission_dates[campaign_name]
            mission_ids = sorted(debriefings.keys(), key=smart_mission_sort_key)
            if mission_ids:
                first_mission_id = mission_ids[0]
                last_mission_id = mission_ids[-1]
                first_mission_date = mission_dates_dict.get(first_mission_id, {}).get('date')
                last_mission_date = mission_dates_dict.get(last_mission_id, {}).get('date')
        
        # Calculate campaign duration
        campaign_duration_days = None
        if first_mission_date and last_mission_date:
            try:
                from datetime import datetime
                fmt = '%Y.%m.%d'
                start = datetime.strptime(first_mission_date.replace('.', '-'), '%Y-%m-%d')
                end = datetime.strptime(last_mission_date.replace('.', '-'), '%Y-%m-%d')
                campaign_duration_days = (end - start).days
            except:
                pass
        
        # Get career progression
        promotions = [e for e in events if e.get('type') == 'promotion']
        awards = [e for e in events if e.get('type') == 'award']
        
        starting_rank = promotions[0]['rank'] if promotions else 'Unknown'
        final_rank = promotions[-1]['rank'] if promotions else starting_rank
        
        # Generate HTML
        html = []
        html.append('<div style="page-break-before: always;"></div>')
        html.append('<div style="text-align: center; margin: 40px 0 30px 0;">')
        html.append('<div style="border-top: 3px double #333; border-bottom: 3px double #333; padding: 20px 0; margin: 0 50px;">')
        html.append('<h1 style="margin: 0; font-size: 24pt;">CAMPAIGN SUMMARY</h1>')
        
        campaign_display_name = self.get_campaign_display_name(campaign_name)
        html.append(f'<p style="margin: 10px 0 0 0; font-size: 14pt; font-style: italic;">{campaign_display_name}</p>')
        html.append('</div>')
        html.append('</div>')
        
        # Combat Results
        html.append('<h2 style="border-bottom: 2px solid #333; padding-bottom: 5px; margin-top: 30px;">COMBAT RESULTS</h2>')
        html.append(f'<table style="width: 100%; margin: 10px 0;">')
        
        # total_air already INCLUDES parked kills (it's air_kills from summary which = flying + parked)
        # So total_air_with_parked is just total_air
        total_air_with_parked = total_air
        total_air_flying = total_air - total_air_parked
        
        html.append(f'<tr><td style="padding: 5px 0;"><b>Air Victories:</b></td><td style="text-align: right;">{total_air_with_parked}</td></tr>')
        
        # Show breakdown if there are parked kills
        if total_air_parked > 0:
            html.append(f'<tr><td style="padding: 5px 0 5px 20px; font-size: 10pt; color: #666;">Flying:</td><td style="text-align: right; font-size: 10pt; color: #666;">{total_air_flying}</td></tr>')
            html.append(f'<tr><td style="padding: 5px 0 5px 20px; font-size: 10pt; color: #666;">Parked:</td><td style="text-align: right; font-size: 10pt; color: #666;">{total_air_parked}</td></tr>')
        
        html.append(f'<tr><td style="padding: 5px 0;"><b>Ground Targets:</b></td><td style="text-align: right;">{total_ground}</td></tr>')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Naval Targets:</b></td><td style="text-align: right;">{total_naval}</td></tr>')
        html.append(f'<tr><td colspan="2" style="border-top: 1px solid #333; padding: 5px 0;"></td></tr>')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Total Kills:</b></td><td style="text-align: right;"><b>{total_air_with_parked + total_ground + total_naval}</b></td></tr>')
        html.append('</table>')
        
        # Missions Flown
        html.append('<h2 style="border-bottom: 2px solid #333; padding-bottom: 5px; margin-top: 30px;">MISSIONS FLOWN</h2>')
        html.append(f'<table style="width: 100%; margin: 10px 0;">')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Completed:</b></td><td style="text-align: right;">{mission_count} missions</td></tr>')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Total Flight Time:</b></td><td style="text-align: right;">{total_hours}h {total_minutes}m</td></tr>')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Average Duration:</b></td><td style="text-align: right;">{avg_minutes}m</td></tr>')
        html.append(f'<tr><td colspan="2" style="padding: 10px 0 5px 0;"></td></tr>')
        
        total_outcomes = safe_landings + hard_landings + wounded_landings + bailouts + kia_mia
        if total_outcomes > 0:
            safe_pct = int(safe_landings / total_outcomes * 100)
            html.append(f'<tr><td style="padding: 5px 0;"><b>Safe Landings:</b></td><td style="text-align: right;">{safe_landings} ({safe_pct}%)</td></tr>')
            
            if hard_landings > 0:
                hard_pct = int(hard_landings / total_outcomes * 100)
                html.append(f'<tr><td style="padding: 5px 0;"><b>Hard Landings / Crashes:</b></td><td style="text-align: right;">{hard_landings} ({hard_pct}%)</td></tr>')
            
            if wounded_landings > 0:
                wounded_pct = int(wounded_landings / total_outcomes * 100)
                html.append(f'<tr><td style="padding: 5px 0;"><b>Wounded Landings:</b></td><td style="text-align: right;">{wounded_landings} ({wounded_pct}%)</td></tr>')
            
            if bailouts > 0:
                bailout_pct = int(bailouts / total_outcomes * 100)
                html.append(f'<tr><td style="padding: 5px 0;"><b>Bailouts:</b></td><td style="text-align: right;">{bailouts} ({bailout_pct}%)</td></tr>')
            
            if kia_mia > 0:
                kia_pct = int(kia_mia / total_outcomes * 100)
                html.append(f'<tr><td style="padding: 5px 0;"><b>KIA / MIA:</b></td><td style="text-align: right;">{kia_mia} ({kia_pct}%)</td></tr>')
        
        html.append('</table>')
        
        # Aircraft Flown
        if aircraft_usage:
            html.append('<h2 style="border-bottom: 2px solid #333; padding-bottom: 5px; margin-top: 30px;">AIRCRAFT FLOWN</h2>')
            html.append(f'<table style="width: 100%; margin: 10px 0;">')
            for aircraft, stats in sorted(aircraft_usage.items(), key=lambda x: x[1]['missions'], reverse=True):
                html.append(f'<tr><td style="padding: 5px 0;"><b>{aircraft}:</b></td><td style="text-align: right;">{stats["missions"]} missions ({stats["kills"]} kills)</td></tr>')
            html.append('</table>')
        
        # Career Progression
        html.append('<h2 style="border-bottom: 2px solid #333; padding-bottom: 5px; margin-top: 30px;">CAREER PROGRESSION</h2>')
        html.append(f'<table style="width: 100%; margin: 10px 0;">')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Starting Rank:</b></td><td style="text-align: right;">{starting_rank}</td></tr>')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Final Rank:</b></td><td style="text-align: right;">{final_rank}</td></tr>')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Promotions:</b></td><td style="text-align: right;">{len(promotions)}</td></tr>')
        html.append(f'<tr><td colspan="2" style="padding: 10px 0 5px 0;"></td></tr>')
        html.append(f'<tr><td style="padding: 5px 0;"><b>Awards Received:</b></td><td style="text-align: right;">{len(awards)}</td></tr>')
        html.append('</table>')
        
        if awards:
            html.append('<ul style="margin: 5px 0; padding-left: 20px;">')
            for award in awards:
                html.append(f'<li>{award["name"]}</li>')
            html.append('</ul>')
        
        # Top Targets
        html.append('<h2 style="border-bottom: 2px solid #333; padding-bottom: 5px; margin-top: 30px;">TOP TARGETS DESTROYED</h2>')
        
        # Air targets
        if target_counts['air']:
            html.append('<p style="margin: 10px 0 5px 0;"><b>Air Targets:</b></p>')
            html.append('<ol style="margin: 0; padding-left: 25px;">')
            for target, count in sorted(target_counts['air'].items(), key=lambda x: x[1], reverse=True)[:5]:
                html.append(f'<li>{target} (× {count})</li>')
            html.append('</ol>')
        
        # Ground targets
        if target_counts['ground']:
            html.append('<p style="margin: 15px 0 5px 0;"><b>Ground Targets:</b></p>')
            html.append('<ol style="margin: 0; padding-left: 25px;">')
            for target, count in sorted(target_counts['ground'].items(), key=lambda x: x[1], reverse=True)[:5]:
                html.append(f'<li>{target} (× {count})</li>')
            html.append('</ol>')
        
        # Naval targets
        if target_counts['naval']:
            html.append('<p style="margin: 15px 0 5px 0;"><b>Naval Targets:</b></p>')
            html.append('<ol style="margin: 0; padding-left: 25px;">')
            for target, count in sorted(target_counts['naval'].items(), key=lambda x: x[1], reverse=True)[:5]:
                html.append(f'<li>{target} (× {count})</li>')
            html.append('</ol>')
        
        # Campaign Timeline
        if first_mission_date and last_mission_date:
            html.append('<h2 style="border-bottom: 2px solid #333; padding-bottom: 5px; margin-top: 30px;">CAMPAIGN TIMELINE</h2>')
            html.append(f'<table style="width: 100%; margin: 10px 0;">')
            
            # Format dates nicely
            start_date_formatted = self.format_date(first_mission_date)
            end_date_formatted = self.format_date(last_mission_date)
            
            html.append(f'<tr><td style="padding: 5px 0;"><b>Start Date:</b></td><td style="text-align: right;">{start_date_formatted}</td></tr>')
            html.append(f'<tr><td style="padding: 5px 0;"><b>End Date:</b></td><td style="text-align: right;">{end_date_formatted}</td></tr>')
            if campaign_duration_days is not None:
                html.append(f'<tr><td style="padding: 5px 0;"><b>Campaign Duration:</b></td><td style="text-align: right;">{campaign_duration_days} days</td></tr>')
            html.append('</table>')
        
        return '\n'.join(html)
    
    def export_campaign_to_pdf(self, campaign_name: str, html_content: str) -> bool:
        """
        Export campaign report as PDF
        
        Args:
            campaign_name: Campaign folder name
            html_content: Complete HTML content to export
            
        Returns:
            True if successful, False otherwise
        """
        try:
            import pdfkit
        except ImportError:
            print(f"  ℹ️  PDF export skipped: pdfkit not installed")
            print(f"      Install with: pip install pdfkit")
            return False
        
        # Check if wkhtmltopdf is available
        config = None
        try:
            # First, check if we're running as PyInstaller bundle with embedded wkhtmltopdf
            if getattr(sys, 'frozen', False):
                # Running as compiled EXE
                bundle_dir = Path(sys._MEIPASS)
                wkhtmltopdf_path = bundle_dir / 'wkhtmltopdf.exe'
                
                if wkhtmltopdf_path.exists():
                    # Use bundled wkhtmltopdf
                    config = pdfkit.configuration(wkhtmltopdf=str(wkhtmltopdf_path))
                else:
                    # Try system-installed wkhtmltopdf
                    config = pdfkit.configuration()
            else:
                # Running as Python script - use system wkhtmltopdf
                config = pdfkit.configuration()
                
        except OSError:
            print(f"  ℹ️  PDF export skipped: wkhtmltopdf not found")
            print(f"      Download from: https://wkhtmltopdf.org/downloads.html")
            return False
        
        # Create reports directory if it doesn't exist
        reports_dir = Path('reports')
        reports_dir.mkdir(exist_ok=True)
        
        # Get campaign display name from info file
        campaign_display_name = self.get_campaign_display_name(campaign_name)
        
        # Clean campaign name for filename (remove special chars)
        safe_name = re.sub(r'[^\w\s-]', '', campaign_name).strip().replace(' ', '_')
        pdf_filename = reports_dir / f"{safe_name}_Report.pdf"
        
        try:
            # Create complete HTML document
            full_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{campaign_display_name} - Campaign Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            font-size: 10pt;
        }}
        h1 {{
            text-align: center;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
        }}
        .mission-box {{
            page-break-inside: avoid;
            margin-bottom: 10px;
        }}
    </style>
</head>
<body>
    <h1>{campaign_display_name}</h1>
    <p><i>Campaign Report - Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i></p>
    <hr>
    {html_content}
</body>
</html>
"""
            
            # PDF options
            options = {
                'page-size': 'A4',
                'margin-top': '15mm',
                'margin-right': '15mm',
                'margin-bottom': '15mm',
                'margin-left': '15mm',
                'encoding': 'UTF-8',
                'no-outline': None,
                'enable-local-file-access': None,
                'quiet': ''  # Suppress wkhtmltopdf warnings
            }
            
            # Convert HTML to PDF
            pdfkit.from_string(full_html, str(pdf_filename), options=options, configuration=config)
            
            print(f"  ✓ PDF exported: {pdf_filename}")
            return True
            
        except Exception as e:
            print(f"  ⚠️  PDF export failed: {e}")
            return False
    
    def process_all_campaigns(self):
        """Process all campaigns and generate events"""
        print("="*70)
        print("IL-2 CAMPAIGN EVENTS GENERATOR")
        print("="*70)
        
        results = {}
        files_updated = 0
        
        for campaign_name in self.save_data.keys():
            # Skip if excluded (WW1) - case-insensitive lookup
            campaign_name_lower = campaign_name.lower()
            if campaign_name_lower in self.mission_dates_lower:
                _, mission_data = self.mission_dates_lower[campaign_name_lower]
                if mission_data.get('excluded'):
                    print(f"\nSkipping {campaign_name} (excluded: WW1)")
                    continue
            
            events = self.generate_events_for_campaign(campaign_name)
            
            if events:
                # Get country (case-insensitive)
                if campaign_name_lower in self.mission_dates_lower:
                    _, mission_data = self.mission_dates_lower[campaign_name_lower]
                    country = mission_data.get('country')
                else:
                    country = None
                
                # Generate Events HTML
                events_html = self.generate_events_html(events, country)
                
                # Generate Debriefings HTML (if available)
                completed_missions = list(self.save_data[campaign_name].get('completedMissionsByFileName', {}).keys())
                debriefings_html = ""
                debriefings = {}
                
                if self.log_processor and completed_missions:
                    print(f"  Generating debriefings for {len(completed_missions)} mission(s)...")
                    debriefings_html, debriefings = self.generate_debriefings_html(campaign_name, completed_missions)
                
                # Combine: Debriefings BEFORE Events
                if debriefings_html:
                    combined_html = debriefings_html + "\n" + events_html
                else:
                    combined_html = events_html
                
                results[campaign_name] = {
                    'country': country,
                    'events': events,
                    'debriefings_html': debriefings_html,
                    'events_html': events_html,
                    'html': combined_html
                }
                
                # Update the campaign info file
                if self.update_campaign_info_file(campaign_name, combined_html):
                    files_updated += 1
                
                # Export to PDF (only if campaign has completed missions)
                if completed_missions and not self.dry_run:
                    # Calculate cumulative stats from campaigns_decoded.json
                    cumulative_stats = None
                    try:
                        with open('campaigns_decoded.json', 'r', encoding='utf-8') as f:
                            decoded_data = json.load(f)
                            if campaign_name in decoded_data:
                                stats = decoded_data[campaign_name].get('characterStatisticsByFileName', {})
                                # Get the latest mission stats (highest mission number)
                                if stats:
                                    latest_mission = max(stats.keys(), key=lambda x: int(x) if x.isdigit() else 0)
                                    cumulative_stats = stats.get(latest_mission, {})
                    except (FileNotFoundError, json.JSONDecodeError, KeyError):
                        cumulative_stats = None
                    
                    # Generate PDF-specific HTML with base64-embedded images
                    events_html_pdf = self.generate_events_html(events, country, for_pdf=True)
                    
                    # Combine debriefings + events
                    if debriefings_html:
                        combined_html_pdf = debriefings_html + "\n" + events_html_pdf
                    else:
                        combined_html_pdf = events_html_pdf
                    
                    # Generate campaign summary (PDF only!)
                    # Use the debriefings we already loaded earlier
                    summary_html = self.generate_campaign_summary_html(campaign_name, events, debriefings, country, cumulative_stats)
                    
                    # Add summary at the end
                    if summary_html:
                        combined_html_pdf += "\n" + summary_html
                    
                    self.export_campaign_to_pdf(campaign_name, combined_html_pdf)
        
        # Save results
        with open('campaign_events.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'='*70}")
        print(f"COMPLETE!")
        print(f"{'='*70}")
        print(f"Generated events for {len(results)} campaigns")
        print(f"Updated {files_updated} campaign info files")
        print(f"Results saved to: campaign_events.json")
        print(f"PDF reports saved to: reports/ directory")
        
        # Show sample for kerch if available
        if 'kerch' in results:
            print(f"\n{'='*70}")
            print("SAMPLE OUTPUT (kerch):")
            print(f"{'='*70}")
            print(results['kerch']['html'])
        
        return results


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='IL-2 Campaign Progress Tracker - Event Generator'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually modifying files'
    )
    parser.add_argument(
        '--campaign',
        type=str,
        help='Only process specific campaign (e.g., kerch)'
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("="*70)
        print("DRY RUN MODE - No files will be modified")
        print("="*70)
        print()
    
    generator = EventGenerator(dry_run=args.dry_run)
    
    if args.campaign:
        # Process single campaign
        print(f"Processing single campaign: {args.campaign}")
        events = generator.generate_events_for_campaign(args.campaign)
        if events:
            country = generator.mission_dates[args.campaign].get('country')
            html = generator.generate_events_html(events, country)
            print(f"\n{'='*70}")
            print(f"Generated HTML:")
            print(f"{'='*70}")
            print(html)
            
            if not args.dry_run:
                generator.update_campaign_info_file(args.campaign, html)
    else:
        # Process all campaigns
        results = generator.process_all_campaigns()


if __name__ == "__main__":
    main()
