#!/usr/bin/env python3
"""
IL-2 Campaign Progress Tracker - Mission Date Extractor

Extracts mission dates from all IL-2 campaigns and stores them in JSON format.
Includes smart update system that preserves existing data and GUI for easy setup.

Usage:
    First run: Opens GUI folder browser to select IL-2 game directory
    Subsequent runs: Auto-loads and checks for new campaigns/missions
    
Command line options:
    --force-new     Start fresh (select directory again via GUI)
    --verbose       Show detailed scanning info
    --include-ww1   Include WW1 Flying Circus campaigns
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


class CampaignDateExtractor:
    def __init__(self, campaigns_folder: str, verbose: bool = False, exclude_ww1: bool = True):
        """
        Initialize the date extractor
        
        Args:
            campaigns_folder: Path to IL-2's data/Campaigns folder
            verbose: If True, show all files checked for each mission
            exclude_ww1: If True, skip WW1 campaigns (Flying Circus)
        """
        self.campaigns_folder = Path(campaigns_folder)
        self.campaign_dates = {}
        self.verbose = verbose
        self.exclude_ww1 = exclude_ww1
        
        # Build stock campaigns mapping immediately
        self._load_stock_campaigns_mapping()
        
        # Extract game directory from campaigns folder
        # campaigns_folder should be: <game_dir>\data\Campaigns
        if 'data' in str(campaigns_folder).lower() and 'campaigns' in str(campaigns_folder).lower():
            # Go up two levels to get game directory
            self.game_directory = str(self.campaigns_folder.parent.parent)
        else:
            self.game_directory = str(campaigns_folder)
        
        # Aircraft to country mapping
        self.aircraft_countries = {
            # German aircraft (WW2)
            'bf109': 'Germany', 'bf110': 'Germany', 'fw190': 'Germany',
            'he111': 'Germany', 'ju87': 'Germany', 'ju88': 'Germany',
            'hs129': 'Germany', 'me262': 'Germany', 'me410': 'Germany',
            'me': 'Germany',  # Catch ME-xxx variants
            
            # Axis allies (use German ranks/awards)
            'iar80': 'Germany', 'iar81': 'Germany',  # Romania
            'mc200': 'Germany', 'mc202': 'Germany',  # Italy
            
            # German aircraft (WW1)
            'fokker': 'Germany', 'albatros': 'Germany', 'pfalz': 'Germany',
            'halberstadt': 'Germany', 'roland': 'Germany',
            
            # Soviet aircraft
            'i16': 'Soviet Union', 'lagg3': 'Soviet Union', 'la5': 'Soviet Union',
            'yak1': 'Soviet Union', 'yak7': 'Soviet Union', 'yak9': 'Soviet Union',
            'il2': 'Soviet Union', 'pe2': 'Soviet Union', 'mig3': 'Soviet Union',
            'p39': 'Soviet Union',  # Lend-lease to USSR
            'p40': 'Soviet Union',  # Also used by USSR (but also USA)
            
            # British aircraft (WW2)
            'spitfire': 'Britain', 'hurricane': 'Britain', 'mosquito': 'Britain',
            'typhoon': 'Britain', 'tempest': 'Britain',
            
            # British aircraft (WW1)
            'sopwith': 'Britain', 'se5': 'Britain', 'bristol': 'Britain',
            'fe2': 'Britain', 'dh': 'Britain', 'nieuport': 'Britain',
            
            # American aircraft  
            'p38': 'USA', 'p40': 'USA', 'p47': 'USA', 'p51': 'USA',
            'a20': 'USA', 'b25': 'USA', 'c47': 'USA',
            'thunderbolt': 'USA', 'mustang': 'USA', 'lightning': 'USA',
            
            # French aircraft (WW1, often used by USA in WW1)
            'spad': 'France',
        }
    
    def is_ww1_campaign(self, campaign_name: str, campaign_data: Dict) -> bool:
        """
        Detect if this is a WW1 Flying Circus campaign
        
        Args:
            campaign_name: Name of campaign
            campaign_data: Campaign data including missions
            
        Returns:
            True if this is a WW1 campaign
        """
        country = campaign_data.get('country')
        campaign_path = self.campaigns_folder / campaign_name
        
        # Check 0: Known WW1 campaign names
        ww1_campaign_names = ['kaiserschlacht', 'springoffensive', 'gallant', 
                             'knights', 'againstthetide', 'bloody april']
        if campaign_name.lower() in ww1_campaign_names:
            return True
        
        # Check 1: Mission dates in WW1 range (1914-1918)
        missions = campaign_data.get('missions', {})
        has_ww1_dates = False
        
        if missions:
            ww1_date_count = 0
            total_dates = 0
            
            for mission in missions.values():
                normalized = mission.get('normalized_date')
                if normalized and len(normalized) >= 4:
                    try:
                        year = int(normalized[:4])
                        total_dates += 1
                        if 1914 <= year <= 1918:
                            ww1_date_count += 1
                    except:
                        pass
            
            # If most dates are in WW1 range, it's definitely a WW1 campaign
            if total_dates > 0 and ww1_date_count / total_dates > 0.5:
                has_ww1_dates = True
        
        # Check 2: WW1 aircraft in country detection
        has_ww1_aircraft = False
        info_file = campaign_path / 'info.txt'
        if info_file.exists():
            try:
                with open(info_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().lower()
                
                ww1_aircraft = ['fokker', 'albatros', 'pfalz', 'sopwith', 'spad', 
                               'se5', 'bristol', 'nieuport', 'halberstadt']
                
                if any(aircraft in content for aircraft in ww1_aircraft):
                    has_ww1_aircraft = True
            except:
                pass
        
        # Check 3: "Flying Circus" or strong WW1 keywords in description
        has_ww1_keywords = False
        info_locale = campaign_path / 'info.locale=eng.txt'
        if info_locale.exists():
            try:
                with open(info_locale, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().lower()
                
                # Strong WW1 indicators (not just year mentions)
                strong_ww1_keywords = ['flying circus', 'world war 1', 'world war i', 
                                      'great war', 'royal flying corps']
                
                if any(keyword in content for keyword in strong_ww1_keywords):
                    has_ww1_keywords = True
            except:
                pass
        
        # Decision logic:
        # - If has WW1 dates OR WW1 aircraft OR strong WW1 keywords, it's WW1
        # - BUT: If country is detected as USA/Britain/Germany/Soviet and NO dates/aircraft match WW1,
        #        then it's probably WW2 with historical references
        
        if has_ww1_dates:
            return True  # Definitive
        
        if has_ww1_aircraft and has_ww1_keywords:
            return True  # Both aircraft and keywords
        
        if has_ww1_keywords and not country:
            return True  # Strong keywords and no country detected
        
        if has_ww1_aircraft and country in ['Germany', 'Britain']:
            # Could be WW1 or WW2 - need dates to confirm
            # If no dates but has WW1 aircraft, assume WW1
            if not any(m.get('normalized_date') for m in missions.values()):
                return True
        
        return False
    
    def _load_stock_campaigns_mapping(self):
        """
        Build a mapping of folder_name -> country by scanning all campaigns
        and matching their &name= against stock_campaigns.yaml
        
        This is done ONCE at startup and cached.
        """
        if hasattr(self, '_stock_folder_mapping'):
            return  # Already loaded
        
        self._stock_folder_mapping = {}  # folder_name -> country
        
        # Load stock campaigns library
        # Try external file first (for user editing), then embedded
        import sys
        if getattr(sys, 'frozen', False):
            # Running as EXE - check directory next to EXE first
            exe_dir = Path(sys.executable).parent
            stock_file = exe_dir / 'stock_campaigns.yaml'
            if not stock_file.exists():
                # Fallback to embedded
                stock_file = Path(sys._MEIPASS) / 'stock_campaigns.yaml'
        else:
            # Running as script
            stock_file = Path(__file__).parent / 'stock_campaigns.yaml'
        
        try:
            import yaml
            # Try UTF-8 first, fallback to ISO-8859-1 for files with umlauts
            try:
                with open(stock_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
            except UnicodeDecodeError:
                with open(stock_file, 'r', encoding='iso-8859-1') as f:
                    data = yaml.safe_load(f)
            
            stock_campaigns = data.get('stock_campaigns', {})
            
            if not stock_campaigns:
                if self.verbose:
                    print("    Warning: No stock campaigns in library")
                return
            
            # Scan all campaign folders
            if not self.campaigns_folder.exists():
                return
            
            campaign_folders = [f for f in self.campaigns_folder.iterdir() if f.is_dir()]
            
            # Always show this important step
            print(f"\n  Building stock campaigns mapping...")
            print(f"  Scanning {len(campaign_folders)} folders...")
            
            matched = 0
            for folder in campaign_folders:
                info_file = folder / "info.locale=eng.txt"
                
                if not info_file.exists():
                    continue
                
                try:
                    import re
                    content = None
                    
                    # Try multiple encodings
                    for encoding in ['utf-8', 'utf-8-sig', 'iso-8859-1', 'cp1252']:
                        try:
                            with open(info_file, 'r', encoding=encoding) as f:
                                content = f.read(1000)  # Read first 1000 chars
                            break  # Success!
                        except UnicodeDecodeError:
                            continue
                    
                    if not content:
                        if self.verbose:
                            print(f"    ✗ {folder.name}: Could not decode file with any encoding")
                        continue
                    
                    # Extract &name="Campaign Name" or &name=Campaign Name
                    # Try quoted version first
                    match = re.search(r'&name="([^"]+)"', content)
                    if not match:
                        # Try unquoted version (some campaigns don't use quotes)
                        match = re.search(r'&name=([^\s\n;]+)', content)
                    
                    if match:
                        display_name = match.group(1)
                        
                        # Check if this matches any stock campaign (case-insensitive)
                        for stock_name, country in stock_campaigns.items():
                            if stock_name.lower() == display_name.lower():
                                self._stock_folder_mapping[folder.name] = country
                                matched += 1
                                if self.verbose:
                                    print(f"    ✓ {folder.name} → '{display_name}' → {country}")
                                break
                    else:
                        if self.verbose:
                            print(f"    ✗ {folder.name}: No &name= found in first 1000 chars")
                
                except Exception as e:
                    if self.verbose:
                        print(f"    Warning: Could not read {folder.name}/info.locale: {e}")
            
            # Always show final count
            print(f"  Mapped {matched} stock campaigns")
            
            # Debug: Show first few mappings
            if matched > 0 and self.verbose:
                print(f"  Sample mappings:")
                for folder, country in list(self._stock_folder_mapping.items())[:5]:
                    print(f"    {folder} → {country}")
        
        except Exception as e:
            print(f"    ERROR: Could not load stock campaigns library: {e}")
            import traceback
            traceback.print_exc()
            self._stock_folder_mapping = {}
    
    def _check_stock_campaign(self, campaign_name: str) -> Optional[str]:
        """
        Check if campaign is a known stock IL-2 campaign
        Returns country if found in mapping, None otherwise
        """
        # Ensure mapping is loaded
        self._load_stock_campaigns_mapping()
        
        # Simple lookup in pre-built mapping
        return self._stock_folder_mapping.get(campaign_name)
    
    def detect_country(self, campaign_name: str) -> Optional[str]:
        """
        Detect which country/faction the campaign is for
        Uses multiple detection methods (in priority order):
        0. Stock campaigns library (official IL-2 campaigns)
        1. Campaign/mission names
        2. Aircraft type from info.txt
        3. Keywords in campaign description
        4. Mission briefings (last resort)
        
        Returns:
            Tuple of (country_name, is_stock) or (None, False) if cannot detect
        """
        campaign_path = self.campaigns_folder / campaign_name
        
        # Method 0: Check stock campaigns library (HIGHEST PRIORITY)
        stock_result = self._check_stock_campaign(campaign_name)
        if stock_result:
            if self.verbose:
                print(f"    Detection method: Stock campaign library")
            return (stock_result, True)  # Return country and is_stock=True
        elif self.verbose:
            print(f"    Method 0 (Stock Library): Not a known stock campaign")
        
        # Method 1: Check campaign name and mission names
        country = self._detect_from_names(campaign_name, campaign_path)
        if country:
            if self.verbose:
                print(f"    Detection method: Campaign/Mission names")
            return (country, False)  # Not a stock campaign
        elif self.verbose:
            print(f"    Method 0 (Names): No match")
        
        # Method 1: Check aircraft from info.txt
        country = self._detect_from_aircraft(campaign_path)
        if country:
            if self.verbose:
                print(f"    Detection method: Aircraft type")
            return (country, False)  # Not a stock campaign
        elif self.verbose:
            print(f"    Method 1 (Aircraft): No match")
        
        # Method 2: Check campaign description
        country, scores = self._detect_from_description(campaign_path)
        if country:
            if self.verbose:
                print(f"    Detection method: Campaign description keywords")
                print(f"    Keyword scores: {scores}")
            return (country, False)  # Not a stock campaign
        elif self.verbose:
            print(f"    Method 2 (Description): No strong match. Scores: {scores}")
        
        # Method 3: Check mission briefings as last resort
        country = self._detect_from_briefings(campaign_path)
        if country:
            if self.verbose:
                print(f"    Detection method: Mission briefing keywords")
            return (country, False)  # Not a stock campaign
        elif self.verbose:
            print(f"    Method 3 (Briefings): No match")
        
        print(f"  ⚠ WARNING: Could not detect country for {campaign_name}")
        
        return (None, False)  # No detection, not stock
    
    def _detect_from_names(self, campaign_name: str, campaign_path: Path) -> Optional[str]:
        """
        Detect country from campaign name and mission filenames
        HIGHEST PRIORITY - names often contain clear indicators
        """
        name_keywords = {
            'Germany': [
                # Luftwaffe specific
                'luftwaffe', 'jg', 'kg', 'stg', 'nachtjagd', 'jagdgeschwader', 
                'kampfgeschwader', 'sturzkampfgeschwader', 'zerstorergeschwader',
                # German aircraft (very distinctive)
                'bf109', 'bf110', 'bf-109', 'bf-110', 'me109', 'me-109', 
                'fw190', 'fw-190', 'focke-wulf', 'me262', 'me-262',
                'ju87', 'ju-87', 'stuka', 'ju88', 'ju-88',
                'he111', 'he-111', 'heinkel', 'do217', 'do-217',
                # Axis allies (use German ranks/awards in game)
                'iar80', 'iar-80', 'iar81', 'iar-81',  # Romania
                'mc202', 'mc-202', 'mc200', 'mc-200',  # Italy
                # Squadron designations
                'i./jg', 'ii./jg', 'iii./jg', 'iv./jg',
                'i./kg', 'ii./kg', 'iii./kg', 'iv./kg',
            ],
            'Soviet Union': [
                # VVS specific
                'vvs', 'voenno-vozdushnye', 'gvardeyskiy',
                # Soviet aircraft
                'yak', 'yak-', 'lagg', 'lagg-', 'la-', 'lavochkin',
                'il-2', 'il2', 'shturmovik', 'pe-2', 'pe2', 'peshka',
                'i-16', 'i16', 'rata', 'mig-3', 'mig3',
                # Soviet squadrons
                'giap', 'gshap', 'iap', 'shap', 'gvap',
            ],
            'USA': [
                # USAAF/USAF
                'usaaf', 'usaf', 'usaac', 'u.s.aaf', 'u.s.af',
                'fighter squadron', 'fighter group', 'bombardment',
                'mighty eighth', '8th air force',
                # US aircraft
                'p-38', 'p38', 'lightning', 'p-39', 'p39', 'airacobra',
                'p-40', 'p40', 'warhawk', 'tomahawk', 'kittyhawk',
                'p-47', 'p47', 'thunderbolt', 'p-51', 'p51', 'mustang',
                'b-17', 'b17', 'b-24', 'b24', 'b-25', 'b25',
                'a-20', 'a20', 'havoc', 'boston',
            ],
            'Britain': [
                # RAF specific
                'raf', 'r.a.f.', 'royal air force',
                'squadron', 'wing', 'group',
                # RAF aircraft
                'spitfire', 'hurricane', 'typhoon', 'tempest',
                'mosquito', 'beaufighter', 'halifax', 'lancaster',
                'wellington', 'blenheim',
                # Specific RAF ops
                'battle of britain', 'bob', 'bomber command',
            ],
        }
        
        # Combine campaign name and mission names for analysis
        text_to_check = campaign_name.lower()
        
        # Add mission filenames
        mission_files = list(campaign_path.glob('*.eng')) + list(campaign_path.glob('*.msnbin'))
        for mission_file in mission_files[:20]:  # Check first 20 missions
            text_to_check += ' ' + mission_file.stem.lower()
        
        # Count keyword matches per country
        scores = {}
        for country, keywords in name_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text_to_check)
            if score > 0:
                scores[country] = score
        
        if not scores:
            return None
        
        # Find highest score
        best_country = max(scores, key=scores.get)
        max_score = scores[best_country]
        
        # Threshold: at least 1 match
        if max_score < 1:
            return None
        
        # Tie-breaking: if multiple countries have same score, unclear → return None
        countries_with_max = [c for c, s in scores.items() if s == max_score]
        if len(countries_with_max) > 1:
            # Ambiguous! Let later methods decide
            return None
        
        return best_country
    
    def _detect_from_aircraft(self, campaign_path: Path) -> Optional[str]:
        """Detect country from aircraft type in info.txt OR info.locale=eng.txt"""
        
        # Method 1: Check info.txt for &planes= line
        info_file = campaign_path / 'info.txt'
        
        if info_file.exists():
            try:
                # Try UTF-16 LE first
                try:
                    with open(info_file, 'r', encoding='utf-16-le') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                
                # Look for &planes= line
                plane_match = re.search(r'&planes=(.+)', content, re.IGNORECASE)
                
                if plane_match:
                    plane_path = plane_match.group(1).strip().lower()
                    
                    # Check against aircraft database
                    for aircraft_key, country in self.aircraft_countries.items():
                        if aircraft_key in plane_path:
                            return country
            except:
                pass
        
        # Method 2: Check info.locale=eng.txt for aircraft mentions
        info_locale_file = campaign_path / 'info.locale=eng.txt'
        
        if info_locale_file.exists():
            try:
                # Try UTF-16 LE first
                try:
                    with open(info_locale_file, 'r', encoding='utf-16-le') as f:
                        content = f.read().lower()
                except UnicodeDecodeError:
                    with open(info_locale_file, 'r', encoding='utf-8') as f:
                        content = f.read().lower()
                
                # Look for aircraft mentions in the description
                # Common patterns: "Flyable Aircraft: Bf-109 G-6"
                #                  "fly the ME 410"
                #                  "P-47 Thunderbolt"
                
                # Check against aircraft database
                for aircraft_key, country in self.aircraft_countries.items():
                    # Look for the aircraft name with word boundaries or common separators
                    # Handle both "fw190" and "fw 190" formats (with space before number)
                    aircraft_with_space = re.sub(r'([a-z]+)(\d+)', r'\1 \2', aircraft_key)  # "fw190" -> "fw 190"
                    
                    patterns = [
                        rf'\b{aircraft_key}[\s\-]',       # "p47-" or "p47 "
                        rf'\b{aircraft_key}\b',            # "p47" as whole word
                        rf'\b{aircraft_with_space}[\s\-]', # "p 47-" or "p 47 "
                        rf'\b{aircraft_with_space}\b',     # "p 47" as whole words
                    ]
                    
                    for pattern in patterns:
                        if re.search(pattern, content):
                            return country
            except:
                pass
        
        return None
    
    def _detect_from_description(self, campaign_path: Path) -> tuple[Optional[str], Dict[str, int]]:
        """Detect country from campaign description keywords
        
        Returns:
            Tuple of (country_name, scores_dict)
        """
        info_locale_file = campaign_path / 'info.locale=eng.txt'
        
        scores = {'Germany': 0, 'Soviet Union': 0, 'Britain': 0, 'USA': 0}
        
        if not info_locale_file.exists():
            return None, scores
        
        try:
            # Try different encodings
            content = None
            encodings_to_try = ['utf-8', 'utf-16-le', 'utf-16-be', 'latin-1']
            
            for encoding in encodings_to_try:
                try:
                    with open(info_locale_file, 'r', encoding=encoding) as f:
                        test_content = f.read()
                    
                    # Validate that content looks reasonable (has normal ASCII characters)
                    # Check for common words that should be in English descriptions
                    test_lower = test_content.lower()
                    if any(word in test_lower for word in ['campaign', 'mission', 'pilot', 'aircraft', 'the ', 'and ']):
                        content = test_lower
                        if self.verbose:
                            print(f"    Successfully read with {encoding}")
                        break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            
            if not content:
                if self.verbose:
                    print(f"    Warning: Could not decode file with any encoding")
                return None, scores
            
            if self.verbose:
                print(f"    Read {len(content)} chars from description")
                print(f"    First 200 chars: {content[:200]}")
                if len(content) < 100:
                    print(f"    WARNING: Description seems too short!")
            
            if not content or len(content) < 50:
                # File read but empty or too short
                return None, scores
            
            # German indicators
            german_keywords = [
                r'\biar[\s-]?80',        # IAR-80, IAR 80 (Romanian Axis aircraft) - STRONG INDICATOR
                r'\biar[\s-]?80',        # Double weight for IAR80 (unique identifier)
                r'\biar[\s-]?81',        # IAR-81 - STRONG INDICATOR
                r'\biar[\s-]?81',        # Double weight for IAR81
                r'\bmc[\s-]?20[02]',     # MC-200, MC-202 (Italian Axis aircraft)
                r'\bjg\s*\d+',           # JG 52, JG 54, etc. (Jagdgeschwader)
                r'\bkg\s*\d+',           # KG 51, etc. (Kampfgeschwader)
                r'\bstg\s*\d+',          # StG 77, etc. (Stukageschwader)
                r'\bzg\s*\d+',           # ZG (Zerstörergeschwader)
                r'\bluftwaf+e',          # Luftwaffe
                r'\bwehrmacht\b',        # Wehrmacht
                r'\bbf[\s-]?109',        # Bf-109, Bf 109
                r'\bfw[\s-]?190',        # Fw-190
                r'\bme[\s-]?410',        # ME-410
                r'\bme[\s-]?262',        # ME-262
                r'\bmesserschmitt\b',    # Messerschmitt
                r'\bfocke.wulf\b',       # Focke-Wulf
                r'\bjunkers\b',          # Junkers
                r'\bgerman\s+pilot',     # German pilot
                r'\bgerman\s+forces',    # German forces
                r'\bgerman\s+air\s+force', # German Air Force
            ]
            
            # Soviet indicators
            soviet_keywords = [
                r'\biap\s*\d+',          # IAP (Fighter Aviation Regiment)
                r'\bgvap\s*\d+',         # GVAP (Guards Fighter Aviation Regiment)
                r'\bshap\s*\d+',         # ShAP (Ground Attack Aviation Regiment)
                r'\bvvs\b',              # VVS (Soviet Air Force)
                r'\bred\s+air\s+force',  # Red Air Force
                r'\bred\s+army',         # Red Army
                r'\bsoviet\s+pilot',     # Soviet pilot
                r'\bsoviet\s+forces',    # Soviet forces
                r'\byak[\s-]?[0-9]',     # Yak-1, Yak-9, etc.
                r'\bila[\s-]?2',         # Il-2
                r'\bla[\s-]?[0-9]',      # La-5, La-7
                r'\blagg[\s-]?3',        # LaGG-3
                r'\bpe[\s-]?2',          # Pe-2
            ]
            
            # British indicators
            british_keywords = [
                r'\braf\b',              # RAF
                r'\broyal\s+air\s+force', # Royal Air Force
                r'\bsquadron\s+\d+',     # Squadron 601, etc.
                r'\bbritish\s+pilot',    # British pilot
                r'\bspitfire\b',         # Spitfire
                r'\bhurricane\b',        # Hurricane
                r'\btyphoon\b',          # Typhoon
                r'\btempest\b',          # Tempest
                r'\bmosquito\b',         # Mosquito
            ]
            
            # American indicators
            american_keywords = [
                r'\busaaf\b',            # USAAF
                r'\busaf\b',             # USAF
                r'\b\d+th\s+fighter',    # 56th Fighter Group, etc.
                r'\b\d+th\s+bomb',       # 305th Bomb Group
                r'\b\d+fg\b',            # 366FG format (Fighter Group abbreviation)
                r'\b365th\b',            # 365th Fighter Group (hawks campaign)
                r'\b366th\b',            # 366th Fighter Group (hurtgen)
                r'\bamerican\s+pilot',   # American pilot
                r'\bus\s+air\s+force',   # US Air Force
                r'\bp[\s-]?38',          # P-38
                r'\bp[\s-]?47',          # P-47
                r'\bp[\s-]?51',          # P-51
                r'\bmustang\b',          # Mustang
                r'\bthunderbolt\b',      # Thunderbolt
                r'\blightning\b.*p.?38', # Lightning (with P-38 nearby)
                r'\brepublic\s+p',       # Republic P-47
                r'\b361st\b',            # 361st Fighter Group
                r'\b362nd\b',            # 362nd Fighter Group  
                r'\b368th\b',            # 368th Fighter Group
                r'\b370th\b',            # 370th Fighter Group
                r'\bhurtgen\b',          # Hurtgen Forest (US battle)
                r'\baachen\b',           # Battle of Aachen (US involvement)
                r'\bbastogne\b',         # Bastogne (US)
                r'\bbulge\b',            # Battle of the Bulge (US)
                r'\bninth\s+air\s+force', # Ninth Air Force (US)
            ]
            
            # Count matches for each country
            scores = {
                'Germany': sum(1 for pattern in german_keywords if re.search(pattern, content)),
                'Soviet Union': sum(1 for pattern in soviet_keywords if re.search(pattern, content)),
                'Britain': sum(1 for pattern in british_keywords if re.search(pattern, content)),
                'USA': sum(1 for pattern in american_keywords if re.search(pattern, content)),
            }
            
            # Return country with highest score (if > 0)
            max_score = max(scores.values())
            if max_score > 0:
                for country, score in scores.items():
                    if score == max_score:
                        return country, scores
            
            return None, scores
            
        except UnicodeDecodeError as e:
            if self.verbose:
                print(f"    Warning: Encoding error reading description: {e}")
            return None, scores
        except Exception as e:
            if self.verbose:
                print(f"    Warning: Error in description detection: {e}")
            return None, scores
    
    def _detect_from_briefings(self, campaign_path: Path) -> Optional[str]:
        """Detect country from mission briefing keywords (last resort)"""
        # Check first mission briefing file
        for lang in ['eng', 'ger', 'fra', 'rus']:
            briefing_file = campaign_path / f'01.{lang}'
            if briefing_file.exists():
                try:
                    with open(briefing_file, 'r', encoding='utf-16-le', errors='ignore') as f:
                        content = f.read(1000).lower()  # Just check first 1000 chars
                    
                    # Quick keyword check
                    if any(word in content for word in ['luftwaffe', 'wehrmacht', 'jagdgeschwader']):
                        return 'Germany'
                    if any(word in content for word in ['vvs', 'red army', 'soviet']):
                        return 'Soviet Union'
                    if any(word in content for word in ['raf', 'royal air force', 'squadron']):
                        return 'Britain'
                    if any(word in content for word in ['usaaf', 'usaf', 'fighter group']):
                        return 'USA'
                except:
                    continue
        
        return None
        
    def find_all_campaigns(self) -> List[str]:
        """Find all campaign folders"""
        campaigns = []
        
        if not self.campaigns_folder.exists():
            print(f"Error: Campaign folder not found: {self.campaigns_folder}")
            return campaigns
        
        # Each subfolder is a campaign
        for item in self.campaigns_folder.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                campaigns.append(item.name)
        
        return sorted(campaigns)
    
    def get_mission_files(self, campaign_name: str) -> Dict[str, List[Path]]:
        """
        Get all mission briefing files for a campaign
        
        NEW APPROACH: Use .msnbin files as source of truth
        - Find all .msnbin files (these are the actual missions)
        - For each .msnbin, find matching .eng/.ger/etc briefing file
        - Use the base filename (without extension) as mission ID
        
        This supports:
        - Standard: 01.msnbin, 02.msnbin
        - Custom: 1943-07-04a-FW190-A5U17-IISG1.msnbin
        - Any naming scheme
        
        Returns:
            Dict mapping mission_id -> list of language files
            e.g., {"01": [Path("01.eng"), Path("01.ger")]}
            or {"1943-07-04a-FW190-A5U17-IISG1": [Path("1943-07-04a-FW190-A5U17-IISG1.eng")]}
        """
        campaign_path = self.campaigns_folder / campaign_name
        mission_files = {}
        
        # Find all .msnbin files (these define the missions)
        msnbin_files = list(campaign_path.glob('*.msnbin'))
        
        if not msnbin_files:
            # Fallback: No .msnbin files found, try old method (for very old campaigns)
            if self.verbose:
                print(f"  No .msnbin files found, using fallback detection")
            return self._get_mission_files_fallback(campaign_path)
        
        # For each .msnbin, find corresponding language files
        for msnbin_file in msnbin_files:
            # Get base name without extension
            # e.g., "01.msnbin" -> "01"
            # e.g., "1943-07-04a-FW190-A5U17-IISG1.msnbin" -> "1943-07-04a-FW190-A5U17-IISG1"
            mission_id = msnbin_file.stem
            
            # Find matching language files (same base name, different extension)
            # PREFER .eng (English) files - if .eng exists, use it exclusively
            lang_extensions = ['.eng', '.ger', '.fra', '.rus', '.spa', '.pol', '.chs']
            lang_files = []
            
            # Check if .eng file exists first
            eng_file = campaign_path / f"{mission_id}.eng"
            if eng_file.exists():
                # Use .eng file only (preferred language)
                lang_files.append(eng_file)
            else:
                # No .eng file - check other languages in order
                for ext in lang_extensions[1:]:  # Skip .eng since we already checked
                    lang_file = campaign_path / f"{mission_id}{ext}"
                    if lang_file.exists():
                        lang_files.append(lang_file)
            
            # Store mission (even if no language files found - we know it exists from .msnbin)
            mission_files[mission_id] = lang_files
            
            if self.verbose and not lang_files:
                print(f"  Warning: Mission {mission_id} has .msnbin but no language files")
        
        return mission_files
    
    def _get_mission_files_fallback(self, campaign_path: Path) -> Dict[str, List[Path]]:
        """
        Fallback method for campaigns without .msnbin files
        (Old method - looks for numbered files starting with digits)
        """
        mission_files = {}
        
        for file in campaign_path.iterdir():
            if file.is_file():
                # Match files starting with digits
                match = re.match(r'^(\d+)', file.name)
                if match:
                    mission_num = match.group(1)
                    
                    # Check if it's a text file
                    if file.suffix.lower() in ['.eng', '.ger', '.fra', '.rus', '.spa', '.pol', '.chs']:
                        if mission_num not in mission_files:
                            mission_files[mission_num] = []
                        mission_files[mission_num].append(file)
        
        return mission_files
    
    def extract_date_from_briefing(self, briefing_file: Path) -> Optional[Dict[str, str]]:
        """
        Extract date from a mission briefing file
        Search for "Date:" keyword anywhere in the file
        
        Returns:
            Dict with 'raw_date' and 'normalized_date' or None if not found
        """
        try:
            # Try UTF-16 LE encoding first (common for IL-2 files)
            try:
                with open(briefing_file, 'r', encoding='utf-16-le') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Fall back to UTF-8
                with open(briefing_file, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            # Search for "Date:" anywhere in the file (case insensitive)
            # Handle various formats:
            # "Date: September 3rd 1942"
            # "<b>Date:</b>Sept 18th, 1942"
            # "<b>Date: </b>20.10.1940"  (tags around "Date: ")
            # "Date: 4 November, 1943<br>"
            
            # First try: <b>Date:</b> (colon inside tags)
            date_match = re.search(
                r'<b>Date:</b>\s*(?:</?[\w\s]+>)*\s*([^<\n\r]+)',
                content,
                re.IGNORECASE
            )
            
            # Second try: <b>Date: </b> (colon outside closing tag)
            if not date_match:
                date_match = re.search(
                    r'<b>Date:\s*</b>\s*(?:</?[\w\s]+>)*\s*([^<\n\r]+)',
                    content,
                    re.IGNORECASE
                )
            
            # Third try: Date: with possible tags after
            if not date_match:
                date_match = re.search(
                    r'Date:\s*(?:</?[\w\s]+>)*\s*([^<\n\r]+)',
                    content,
                    re.IGNORECASE
                )
            
            # Fourth try: within <u>Date</u> tags
            if not date_match:
                date_match = re.search(
                    r'<u>Date</u>\s*(?:<br>)*\s*([^<\n\r]+)',
                    content,
                    re.IGNORECASE
                )

            
            if not date_match:
                return None
            
            raw_date = date_match.group(1).strip()
            
            # Clean up the date string
            # Remove trailing text like "Time", "Weather", etc.
            raw_date = re.split(r'\s+(Time|Weather|Airfield|Callsign|Wind)', raw_date, flags=re.IGNORECASE)[0].strip()
            
            # Try to normalize the date
            normalized_date = self.normalize_date(raw_date)
            
            return {
                'raw_date': raw_date,
                'normalized_date': normalized_date,
                'mission_file': briefing_file.name
            }
            
        except Exception as e:
            print(f"  Warning: Could not read {briefing_file.name}: {e}")
            return None
    
    def normalize_date(self, date_string: str) -> Optional[str]:
        """
        Try to normalize date string to YYYY-MM-DD format
        
        Handles formats like:
        - "September 3rd 1942"
        - "4 November, 1943"
        - "November 4th 1943"
        - "Sept 18th, 1942"
        - "Oct 23rd, 1942"
        """
        # Remove ordinal suffixes (st, nd, rd, th)
        date_string = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_string)
        
        # Remove extra commas
        date_string = date_string.replace(',', '')
        
        # Expand abbreviated month names
        month_abbrev = {
            'Jan': 'January', 'Feb': 'February', 'Mar': 'March', 'Apr': 'April',
            'May': 'May', 'Jun': 'June', 'Jul': 'July', 'Aug': 'August',
            'Sept': 'September', 'Oct': 'October', 'Nov': 'November', 'Dec': 'December'
        }
        
        for abbr, full in month_abbrev.items():
            # Use word boundary to avoid partial matches
            date_string = re.sub(r'\b' + abbr + r'\b', full, date_string, flags=re.IGNORECASE)
        
        # Try different date formats
        formats = [
            '%B %d %Y',      # September 3 1942
            '%d %B %Y',      # 3 September 1942
            '%B %d, %Y',     # September 3, 1942
            '%d %B, %Y',     # 3 September, 1942
            '%m/%d/%Y',      # 09/03/1942
            '%Y-%m-%d',      # 1942-09-03 (already normalized)
        ]
        
        for fmt in formats:
            try:
                date_obj = datetime.strptime(date_string.strip(), fmt)
                return date_obj.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        # Could not parse - return original
        return date_string
    
    def scan_campaign(self, campaign_name: str) -> Dict:
        """Scan a single campaign and extract all mission dates"""
        print(f"\nScanning campaign: {campaign_name}")
        
        # Detect country (returns tuple: (country, is_stock))
        detection_result = self.detect_country(campaign_name)
        country, is_stock = detection_result if detection_result else (None, False)
        
        if country:
            stock_label = " (Stock)" if is_stock else ""
            print(f"  Country: {country}{stock_label}")
        
        mission_files_dict = self.get_mission_files(campaign_name)
        
        if not mission_files_dict:
            print(f"  No mission files found")
            return {}
        
        print(f"  Found {len(mission_files_dict)} missions")
        
        campaign_data = {
            'campaign_name': campaign_name,
            'country': country,
            'is_stock': is_stock,  # NEW: Add is_stock flag
            'starting_rank_offset': 0,  # Default starting rank (lowest rank)
            'mission_count': len(mission_files_dict),
            'missions': {}
        }
        
        # Process missions to get dates
        # Smart sort: Try numeric first, fall back to alphabetic
        def smart_sort_key(mission_id):
            # If it starts with digits, use those for sorting
            match = re.match(r'^(\d+)', mission_id)
            if match:
                # Return tuple: (numeric_part, full_string) for proper sorting
                # This ensures "01" < "02" < "10", and "01a" < "01b"
                return (int(match.group(1)), mission_id)
            else:
                # No leading digits, sort alphabetically
                # Use large number to put these after numeric missions
                return (999999, mission_id)
        
        for mission_num in sorted(mission_files_dict.keys(), key=smart_sort_key):
            files_for_mission = mission_files_dict[mission_num]
            
            if self.verbose:
                file_list = ', '.join(f.name for f in files_for_mission)
                print(f"    Mission {mission_num}: Checking {len(files_for_mission)} files: {file_list}")
            
            date_info = None
            
            # Try each file variant until we find a date
            for mission_file in files_for_mission:
                date_info = self.extract_date_from_briefing(mission_file)
                if date_info:
                    break  # Found a date, stop searching
            
            if date_info:
                campaign_data['missions'][mission_num] = date_info
                if self.verbose:
                    print(f"      ✓ Found: {date_info['raw_date']} (from {date_info['mission_file']})")
                else:
                    print(f"    Mission {mission_num}: {date_info['raw_date']} (from {date_info['mission_file']})")
            else:
                # No date found in any file variant
                print(f"    Mission {mission_num}: No date found (checked {len(files_for_mission)} files)")
                campaign_data['missions'][mission_num] = {
                    'raw_date': None,
                    'normalized_date': None,
                    'mission_file': files_for_mission[0].name if files_for_mission else None
                }
        
        # Check if WW1 and should be excluded
        if self.exclude_ww1 and self.is_ww1_campaign(campaign_name, campaign_data):
            print(f"  ⚠ WW1 campaign detected - EXCLUDED")
            campaign_data['excluded'] = True
            campaign_data['exclusion_reason'] = 'WW1 Flying Circus campaign'
        
        return campaign_data
    
    def scan_all_campaigns(self) -> Dict:
        """Scan all campaigns and extract mission dates"""
        print("="*70)
        print("SCANNING ALL IL-2 CAMPAIGNS FOR MISSION DATES")
        print("="*70)
        print(f"Campaign folder: {self.campaigns_folder}")
        
        campaigns = self.find_all_campaigns()
        
        if not campaigns:
            print("\nNo campaigns found!")
            return {}
        
        print(f"\nFound {len(campaigns)} campaigns:")
        for campaign in campaigns:
            print(f"  - {campaign}")
        
        # Scan each campaign
        all_data = {}
        
        for campaign_name in campaigns:
            try:
                campaign_data = self.scan_campaign(campaign_name)
                if campaign_data:
                    all_data[campaign_name] = campaign_data
            except Exception as e:
                print(f"  Error scanning {campaign_name}: {e}")
        
        return all_data
    
    def load_existing_data(self, json_file: str) -> Dict:
        """
        Load existing campaign data from JSON file
        
        Returns:
            Existing data dict or empty dict if file doesn't exist
        """
        json_path = Path(json_file)
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Extract game directory if present
                if 'game_directory' in data:
                    stored_game_dir = data['game_directory']
                    print(f"✓ Found existing data with game directory: {stored_game_dir}")
                    return data
                else:
                    print(f"✓ Found existing data (no game directory stored)")
                    return data
            except Exception as e:
                print(f"⚠ Warning: Could not load existing data: {e}")
                return {}
        return {}
    
    def merge_campaign_data(self, existing_campaign: Dict, new_campaign: Dict) -> Dict:
        """
        Merge new campaign data with existing, preserving existing mission data
        
        Args:
            existing_campaign: Existing campaign data
            new_campaign: Newly scanned campaign data
            
        Returns:
            Merged campaign data
        """
        merged = existing_campaign.copy()
        
        # Update campaign name
        merged['campaign_name'] = new_campaign.get('campaign_name', existing_campaign.get('campaign_name'))
        
        # PRESERVE manually validated country (is_stock or existing country)
        # Priority: existing country (if is_stock or manually set) > new detected country
        if existing_campaign.get('is_stock') or existing_campaign.get('country'):
            # Campaign was manually validated or is stock - PRESERVE country!
            merged['country'] = existing_campaign.get('country')
            merged['is_stock'] = existing_campaign.get('is_stock', False)
            if self.verbose:
                stock_label = " (stock)" if existing_campaign.get('is_stock') else " (manual)"
                print(f"  ✓ Preserving country{stock_label}: {merged['country']}")
        else:
            # No existing country - use new detection
            merged['country'] = new_campaign.get('country')
            merged['is_stock'] = new_campaign.get('is_stock', False)
        
        # PRESERVE starting_rank_offset (user may have manually set it)
        # Priority: existing value > new default (0)
        if 'starting_rank_offset' in existing_campaign:
            merged['starting_rank_offset'] = existing_campaign['starting_rank_offset']
            if self.verbose and existing_campaign['starting_rank_offset'] != 0:
                print(f"  ✓ Preserving starting rank offset: {existing_campaign['starting_rank_offset']}")
        else:
            # No existing value - use new default
            merged['starting_rank_offset'] = new_campaign.get('starting_rank_offset', 0)
        
        # Update excluded status
        merged['excluded'] = new_campaign.get('excluded', existing_campaign.get('excluded'))
        merged['exclusion_reason'] = new_campaign.get('exclusion_reason', existing_campaign.get('exclusion_reason'))
        
        # Merge missions - add NEW missions, keep existing ones
        existing_missions = existing_campaign.get('missions', {})
        new_missions = new_campaign.get('missions', {})
        
        merged_missions = existing_missions.copy()
        
        # Add only NEW missions (not in existing data)
        new_mission_count = 0
        for mission_num, mission_data in new_missions.items():
            if mission_num not in existing_missions:
                merged_missions[mission_num] = mission_data
                new_mission_count += 1
                if self.verbose:
                    print(f"    + New mission {mission_num}")
        
        merged['missions'] = merged_missions
        merged['mission_count'] = len(merged_missions)
        
        if new_mission_count > 0 and not self.verbose:
            print(f"  ✓ Added {new_mission_count} new mission(s)")
        
        return merged
    
    def save_to_json(self, output_file: str, existing_data: Dict = None):
        """Save extracted dates to JSON file, merging with existing data if provided"""
        print(f"\n{'='*70}")
        print("SCANNING CAMPAIGNS")
        print(f"{'='*70}")
        
        # Scan all campaigns
        new_data = self.scan_all_campaigns()
        
        # If existing data provided, merge instead of overwrite
        if existing_data:
            print(f"\n{'='*70}")
            print("MERGING WITH EXISTING DATA")
            print(f"{'='*70}")
            
            final_data = {}
            new_campaigns = []
            updated_campaigns = []
            
            # Process each campaign
            all_campaigns = set(list(existing_data.keys()) + list(new_data.keys()))
            all_campaigns.discard('game_directory')  # Remove metadata key
            
            for campaign_name in all_campaigns:
                if campaign_name in existing_data and campaign_name in new_data:
                    # Existing campaign - merge
                    print(f"\nUpdating: {campaign_name}")
                    final_data[campaign_name] = self.merge_campaign_data(
                        existing_data[campaign_name],
                        new_data[campaign_name]
                    )
                    updated_campaigns.append(campaign_name)
                elif campaign_name in new_data:
                    # New campaign
                    print(f"\n✓ New campaign: {campaign_name}")
                    final_data[campaign_name] = new_data[campaign_name]
                    new_campaigns.append(campaign_name)
                else:
                    # Only in existing (campaign was removed from game?)
                    final_data[campaign_name] = existing_data[campaign_name]
            
            # Add game directory
            final_data['game_directory'] = self.game_directory
            
            data = final_data
            
            print(f"\n{'='*70}")
            print("MERGE SUMMARY")
            print(f"{'='*70}")
            if new_campaigns:
                print(f"✓ New campaigns added: {len(new_campaigns)}")
                for name in new_campaigns:
                    print(f"    - {name}")
            if updated_campaigns:
                print(f"✓ Campaigns checked for updates: {len(updated_campaigns)}")
            print(f"✓ Total campaigns: {len(final_data) - 1}")  # -1 for game_directory key
        else:
            # No existing data - save as new
            data = new_data
            data['game_directory'] = self.game_directory
        
        # Save to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'='*70}")
        print(f"✓ Mission dates saved to: {output_file}")
        print(f"{'='*70}")
        
        # Print summary (excluding game_directory key)
        campaign_data = {k: v for k, v in data.items() if k != 'game_directory'}
        
        total_missions = sum(camp['mission_count'] for camp in campaign_data.values())
        missions_with_dates = sum(
            sum(1 for m in camp['missions'].values() if m['normalized_date'])
            for camp in campaign_data.values()
        )
        
        print(f"\nSummary:")
        print(f"  Total campaigns: {len(campaign_data)}")
        
        # Count excluded
        excluded_count = sum(1 for c in campaign_data.values() if c.get('excluded'))
        active_count = len(campaign_data) - excluded_count
        
        if excluded_count > 0:
            print(f"  Active campaigns: {active_count}")
            print(f"  Excluded (WW1): {excluded_count}")
        
        total_missions = sum(camp['mission_count'] for camp in campaign_data.values() if not camp.get('excluded'))
        missions_with_dates = sum(
            sum(1 for m in camp['missions'].values() if m['normalized_date'])
            for camp in campaign_data.values() if not camp.get('excluded')
        )
        
        print(f"  Total missions: {total_missions}")
        print(f"  Missions with dates: {missions_with_dates}")
        print(f"  Missing dates: {total_missions - missions_with_dates}")
        
        # Country breakdown (excluding WW1)
        country_counts = {}
        for camp in campaign_data.values():
            if camp.get('excluded'):
                continue
            country = camp.get('country', 'Unknown')
            if country:
                country_counts[country] = country_counts.get(country, 0) + 1
        
        if country_counts:
            print(f"\n  Active campaigns by country:")
            for country, count in sorted(country_counts.items()):
                print(f"    {country}: {count}")
        
        if excluded_count > 0:
            print(f"\n  Excluded campaigns:")
            for name, camp in campaign_data.items():
                if camp.get('excluded'):
                    print(f"    - {name} ({camp.get('exclusion_reason', 'Unknown')})")
        
        return data


def main():
    """Main entry point"""
    import sys
    from pathlib import Path
    
    print("="*70)
    print("IL-2 CAMPAIGN PROGRESS TRACKER - Date Extractor")
    print("="*70)
    
    # Output file
    output_file = "campaign_mission_dates.json"
    
    # Check for command line arguments
    force_new = '--force-new' in sys.argv
    verbose = '--verbose' in sys.argv or '-v' in sys.argv
    include_ww1 = '--include-ww1' in sys.argv
    auto_mode = '--auto' in sys.argv  # Silent mode with provided path
    
    # Try to load existing data
    existing_data = {}
    campaigns_folder = None
    
    if Path(output_file).exists() and not force_new:
        print(f"\n✓ Found existing {output_file}")
        
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            
            # Extract game directory from existing data
            if 'game_directory' in existing_data:
                game_dir = existing_data['game_directory']
                campaigns_folder = str(Path(game_dir) / 'data' / 'Campaigns')
                
                if not auto_mode:
                    print(f"✓ Game directory: {game_dir}")
                    print(f"✓ Campaigns folder: {campaigns_folder}")
                    print(f"\nChecking for new campaigns or missions...")
            else:
                if not auto_mode:
                    print("⚠ Warning: No game directory stored in existing file.")
                    print("  Will ask for IL-2 path...")
        except Exception as e:
            if not auto_mode:
                print(f"⚠ Warning: Could not read existing file: {e}")
                print("  Will create new file...")
    
    # If no existing data or no game directory, check arguments or ask user
    if not campaigns_folder:
        # Check for --auto with path argument
        if auto_mode and len(sys.argv) > 2:
            game_dir = sys.argv[2]  # Path after --auto
            campaigns_folder = str(Path(game_dir) / 'data' / 'Campaigns')
        elif len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
            # First argument is path
            game_dir = sys.argv[1]
            campaigns_folder = str(Path(game_dir) / 'data' / 'Campaigns')
        else:
            # Use GUI to select directory
            game_dir = select_game_directory_gui()
            
            if not game_dir:
                print("\n⚠ No directory selected. Exiting.")
                return
            
            # Construct campaigns folder path
            campaigns_folder = str(Path(game_dir) / 'data' / 'Campaigns')
            
            # Validate path exists
            if not Path(campaigns_folder).exists():
                print(f"\n⚠ Error: Campaigns folder not found at: {campaigns_folder}")
                print("  Please check your IL-2 installation path.")
                
                # Ask if user wants to try again
                try_again = input("\nTry selecting another folder? (y/n): ").strip().lower()
                if try_again == 'y':
                    return main()  # Recursive call to try again
                return
            
            print(f"\n✓ Campaigns folder found: {campaigns_folder}")
    
    # Validate campaigns folder exists
    if not Path(campaigns_folder).exists():
        if not auto_mode:
            print(f"\n⚠ Error: Campaigns folder not found: {campaigns_folder}")
            print("  The game directory may have changed.")
            print("  Run with --force-new to select a new directory.")
        return
    
    # Run extraction
    if auto_mode:
        # Suppress print statements in auto mode
        import io
        import sys as sys_module
        old_stdout = sys_module.stdout
        sys_module.stdout = io.StringIO()
        
        extractor = CampaignDateExtractor(campaigns_folder, verbose=False, exclude_ww1=not include_ww1)
        extractor.save_to_json(output_file, existing_data if existing_data else None)
        
        sys_module.stdout = old_stdout
    else:
        extractor = CampaignDateExtractor(campaigns_folder, verbose=verbose, exclude_ww1=not include_ww1)
        extractor.save_to_json(output_file, existing_data if existing_data else None)
    
    if not auto_mode:
        print(f"\n{'='*70}")
        print("COMPLETE!")
        print(f"{'='*70}")
        print(f"\n✓ Data saved to: {output_file}")
        print(f"✓ Configuration: campaign_progress_config.yaml")
        print(f"\nNext run: Just execute the script - it will auto-update!")
    
    if not include_ww1:
        print(f"\nNote: WW1 Flying Circus campaigns excluded by default.")
        print(f"      Use --include-ww1 flag to include them.")


def select_game_directory_gui():
    """
    Open a GUI folder browser to select IL-2 game directory
    
    Returns:
        Selected directory path or None if cancelled
    """
    import tkinter as tk
    from tkinter import filedialog
    import os
    
    print("\n" + "="*70)
    print("FIRST TIME SETUP - Select IL-2 Game Directory")
    print("="*70)
    print("\nA folder browser will open...")
    print("Please select your IL-2 Sturmovik installation folder")
    print("(The main game folder, NOT the Campaigns subfolder)")
    print("\nExample: IL-2 Sturmovik Battle of Stalingrad")
    
    # Create invisible root window
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    root.attributes('-topmost', True)  # Bring to front
    
    # Try to find common IL-2 installation paths as initial directory
    possible_paths = [
        r"C:\Program Files (x86)\Steam\steamapps\common",
        r"C:\Program Files\Steam\steamapps\common",
        r"D:\SteamLibrary\steamapps\common",
        r"C:\Games",
        os.path.expanduser("~"),
    ]
    
    initial_dir = None
    for path in possible_paths:
        if os.path.exists(path):
            initial_dir = path
            break
    
    # Open folder dialog
    selected_path = filedialog.askdirectory(
        title="Select IL-2 Sturmovik Game Directory",
        initialdir=initial_dir,
        mustexist=True
    )
    
    root.destroy()  # Clean up
    
    if selected_path:
        print(f"\n✓ Selected: {selected_path}")
        return selected_path
    else:
        print("\n⚠ No folder selected")
        return None


if __name__ == "__main__":
    main()
