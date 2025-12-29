"""
il2_mission_debrief_v2_2.py
---------------------------
IL-2 Mission Debrief Parser — refined kill attribution

✅ Fix: indirect (AID:-1) kill attribution based on damage share ≥ 80 %
✅ Fix: no BotPilot/BotGunner duplicates
✅ Fix: proper aircraft name extraction
✅ Direct & indirect kill logic integrated
✅ Tracker-ready JSON output
"""

import re, json, yaml
from collections import defaultdict
from pathlib import Path

# ==========================================================
# === GameObject ==========================================
# ==========================================================
class GameObject:
    _category_config = None
    def __init__(self, gid, name, type_, country):
        self.id = gid
        self.name = name
        
        # Detect and clean static planes
        self.is_static = False
        if type_ and type_.lower().startswith('static_'):
            self.is_static = True
            # Clean name: "static_il2[9337,0]" → "il2"
            clean_type = type_.replace('static_', '', 1).split('[')[0]
            self.type = clean_type
        else:
            self.type = type_
        
        self.country = country
        self.category = self.classify_type(type_)  # Use original type_ for categorization
        self.state = "Alive"
        self.time_of_kill = None
        self.altitude = None  # Altitude when destroyed

    @classmethod
    def _load_config(cls):
        """Load category definitions once from YAML."""
        if cls._category_config is None:
            # Try external file first (for user editing), then embedded
            import sys
            cfg_path = None
            
            if getattr(sys, 'frozen', False):
                # Running as EXE - check directory next to EXE first
                exe_dir = Path(sys.executable).parent
                cfg_path = exe_dir / "object_categories.yaml"
                if not cfg_path.exists():
                    # Fallback to embedded
                    cfg_path = Path(sys._MEIPASS) / "object_categories.yaml"
            else:
                # Running as script
                cfg_path = Path(__file__).with_name("object_categories.yaml")
            
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    cls._category_config = data.get("categories", {})
                    cls._exclude_config = [x.lower() for x in data.get("exclude", [])]
            except Exception:
                cls._category_config = {}
                cls._exclude_config = []

    @classmethod
    def classify_type(cls, type_):
        """Classify an object using YAML configuration with EXACT matching."""
        cls._load_config()
        s = (type_ or "").lower().strip()
        
        # For static planes, remove coordinates for matching but keep static_ prefix
        # e.g., "static_il2[9337,0]" → "static_il2"
        if s.startswith('static_') and '[' in s:
            s = s.split('[')[0]
        
        # Exclude unwanted object types (still using substring for exclude)
        if any(x in s for x in getattr(cls, "_exclude_config", [])):
            return "Excluded"
        
        # EXACT match: Check if the object name exactly matches any category entry
        for cat, keywords in cls._category_config.items():
            if s in [k.lower() for k in keywords]:
                return cat
        
        return "Unknown"


# ==========================================================
# === MissionStats =========================================
# ==========================================================
class MissionStats:
    def __init__(self):
        self.player_id = None
        self.player_name = None
        self.player_aircraft = None
        self.player_pid = None  # Player pilot ID
        self.player_plid = None  # Player aircraft ID
        self.objects = {}
        self.hits = []      # {attacker,target,damage,time}
        self.kills = []     # GameObject list
        self.events = []
        self.wounded = False
        self.total_damage_taken = 0.0  # DEPRECATED - kept for compatibility
        self.total_aircraft_damage = 0.0  # Cumulative damage to aircraft
        self.total_pilot_damage = 0.0     # Cumulative damage to pilot (for wounded status)
        self.landed = False
        self.crashed = False
        self.pilot_separation_time = None  # Time (ticks) when pilot separated from aircraft (bailout)
        self.final_state = "Alive"
        self.takeoff_time = None
        self.landing_time = None
        self.flight_duration = None

    def add_object(self, obj): self.objects[obj.id] = obj
    def add_hit(self, a, t, d, ts): self.hits.append({"attacker": a, "target": t, "damage": d, "time": ts})
    def add_kill(self, tid, ts):
        obj = self.objects.get(tid)
        if obj and obj.category == "Excluded":
            return  # ignore silently
        if tid in self.objects:
            obj = self.objects[tid]
            obj.state, obj.time_of_kill = "Destroyed", ts
            if obj not in self.kills: self.kills.append(obj)


# ==========================================================
# === MissionDebriefParser ================================
# ==========================================================
class MissionDebriefParser:
    def __init__(self, path, verbose=False):
        self.path = path
        self.stats = MissionStats()
        self.verbose = verbose

    @staticmethod
    def mission_time_to_hhmmss(t):
        # IL-2 uses 50 ticks per second (20ms per tick)
        # NOTE: This is GAME TIME (includes time compression!)
        sec = t / 50.0
        h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
        return f"{h:02}:{m:02}:{s:02}"

    # ------------------------------------------------------
    def parse(self):
        with open(self.path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if "AType" in l]

        # --- register objects ---
        for ln in lines:
            if "AType:10" in ln:
                if "ISPL:1" in ln:
                    # 🧠 Capture both IDs for robustness
                    plid = self._i(ln, r"PLID:(\d+)")
                    pid  = self._i(ln, r"PID:(\d+)")

                    # Store both, in case IL-2 swaps them (as seen in your logs)
                    self.stats.player_plid = plid
                    self.stats.player_pid = pid
                    self.stats.player_id = pid or plid  # use plane ID primarily

                    self.stats.player_name = self._s(ln, r"NAME:([^ ]+)")
                    self.stats.player_aircraft = (
                        self._s(ln, r"TYPE:([^\r\n]+?)\s+COUNTRY:") or self._s(ln, r"TYPE:([^ ]+)")
                    )
                    # Debug output (optional)
                    print(f"[DEBUG] Player detected: {self.stats.player_name} (PLID={plid}, PID={pid})")
                gid = self._i(ln, r"AID:(\d+)")
                self.stats.add_object(GameObject(gid,
                    self._s(ln, r"NAME:([^ ]+)"),
                    self._s(ln, r"TYPE:([^\r\n]+?)\s+COUNTRY:") or self._s(ln, r"TYPE:([^ ]+)"),
                    self._s(ln, r"COUNTRY:(\d+)")
                ))

            elif "AType:12" in ln:
                gid = self._i(ln, r"ID:(\d+)")
                self.stats.add_object(GameObject(gid,
                    self._s(ln, r"NAME:([^ ]+)"),
                    self._s(ln, r"TYPE:([^\r\n]+?)\s+COUNTRY:") or self._s(ln, r"TYPE:([^ ]+)"),
                    self._s(ln, r"COUNTRY:(\d+)")
                ))

        # --- collect events ---
        destroyed = {}  # {tid: (timestamp, altitude)}
        for ln in lines:
            t = self._i(ln, r"T:(\d+)")
            ts = self.mission_time_to_hhmmss(t)
                        
            if "AType:2" in ln:
                a, tgt, dmg = self._i(ln, r"AID:(-?\d+)"), self._i(ln, r"TID:(-?\d+)"), self._f(ln, r"DMG:([\d.]+)")
                pos_match = re.search(r"POS\(([\d.]+),([\d.]+),([\d.]+)\)", ln)
                
                self.stats.add_hit(a, tgt, dmg, ts)
                
                # Track damage to player or player's aircraft
                # Create SEPARATE events for aircraft and pilot damage
                damage_target_type = None
                
                if tgt == self.stats.player_plid and dmg > 0:
                    # Aircraft took damage
                    damage_target_type = "Aircraft"
                    self.stats.total_aircraft_damage += dmg
                    
                    # Add aircraft damage event
                    altitude = int(float(pos_match.group(2))) if pos_match else None
                    attacker_obj = self.stats.objects.get(a)
                    attacker_name = attacker_obj.type if attacker_obj else f"Unknown (ID:{a})"
                    
                    self.stats.events.append({
                        "time": ts,
                        "type": "Damage Taken",
                        "target": attacker_name,
                        "damage": f"{dmg*100:.1f}% aircraft",  # Include "aircraft" in string for aggregation
                        "altitude": altitude,
                        "time_raw": t
                    })
                    
                if tgt in (self.stats.player_pid, self.stats.player_id) and dmg > 0:
                    # Pilot took damage (separate event!)
                    self.stats.total_pilot_damage += dmg
                    
                    # Add pilot damage event
                    altitude = int(float(pos_match.group(2))) if pos_match else None
                    attacker_obj = self.stats.objects.get(a)
                    attacker_name = attacker_obj.type if attacker_obj else f"Unknown (ID:{a})"
                    
                    self.stats.events.append({
                        "time": ts,
                        "type": "Damage Taken",
                        "target": attacker_name,
                        "damage": f"{dmg*100:.1f}% pilot",  # Include "pilot" in string for aggregation
                        "altitude": altitude,
                        "time_raw": t
                    })
                
                # Wounded status: ONLY based on PILOT damage (not aircraft!)
                # Threshold: > 0.01 (1%) pilot damage
                if self.stats.total_pilot_damage > 0.01:
                    self.stats.wounded = True

            elif "AType:3" in ln:
                a, tgt = self._i(ln, r"AID:(-?\d+)"), self._i(ln, r"TID:(-?\d+)")
                pos_match = re.search(r"POS\(([\d.]+),([\d.]+),([\d.]+)\)", ln)
                altitude = int(float(pos_match.group(2))) if pos_match else None
                destroyed[tgt] = (ts, altitude)  # Store with altitude
                
                obj = self.stats.objects.get(tgt)
                # 🚫 Skip excluded object types (from YAML)
                if obj and obj.category == "Excluded":
                    continue
                    
                if a in (self.stats.player_pid, self.stats.player_plid):
                    # Store altitude with the kill
                    if obj and altitude is not None:
                        obj.altitude = altitude
                    self.stats.add_kill(tgt, ts)
                elif a == -1:
                    self._resolve_indirect_kill(tgt, ts, pos_match)

            elif "AType:5" in ln:  # ✅ Takeoff
                pid = self._i(ln, r"PID:(-?\d+)")
                pos_match = re.search(r"POS\(([\d.]+),([\d.]+),([\d.]+)\)", ln)
                if pid in (self.stats.player_pid, self.stats.player_plid) and not self.stats.takeoff_time:
                    self.stats.takeoff_time = t
                    altitude = int(float(pos_match.group(2))) if pos_match else None
                    self.stats.events.append({
                        "time": ts,
                        "type": "Takeoff",
                        "altitude": altitude,
                        "time_raw": t
                    })
            
            elif "AType:18" in ln:  # ✅ Pilot Separation (Bailout indicator)
                # BOTID = pilot that separated, PARENTID = aircraft they left
                botid = self._i(ln, r"BOTID:(-?\d+)")
                parentid = self._i(ln, r"PARENTID:(-?\d+)")
                
                # Check if player pilot separated from player aircraft
                # (only if player IDs are known)
                if (self.stats.player_pid and self.stats.player_plid and 
                    botid == self.stats.player_pid and parentid == self.stats.player_plid):
                    self.stats.pilot_separation_time = t  # Store time (ticks)
                    if self.verbose:
                        print(f"  Pilot separation detected at {ts} (T:{t})")

            elif "AType:6" in ln or "AType:7" in ln:  # ✅ Landing / Crash / Bailout
                pid = self._i(ln, r"PID:(-?\d+)")
                pos_match = re.search(r"POS\(([\d.]+),([\d.]+),([\d.]+)\)", ln)
                
                if pid in (self.stats.player_pid, self.stats.player_plid) and not self.stats.landing_time:
                    self.stats.landing_time = t
                    altitude = int(float(pos_match.group(2))) if pos_match else None
                    
                    # BAILOUT vs CRASH: Check if pilot separated AND time difference
                    # If pilot separated > 40 seconds before landing → Bailout
                    # If pilot separated < 40 seconds before landing → Crash/Hard Landing
                    # Threshold: 2000 ticks (40 seconds at 50 ticks/second)
                    # NOTE: Lowered from 60s to account for time compression effects
                    if self.stats.pilot_separation_time:
                        time_since_separation = t - self.stats.pilot_separation_time
                        
                        if time_since_separation > 2000:
                            # Long time → Player bailed out and descended with parachute
                            self.stats.crashed = False
                            self.stats.landed = False
                            if self.stats.wounded:
                                self.stats.final_state = "Bailout (Wounded)"
                            else:
                                self.stats.final_state = "Bailout"
                            event_type = "Bailout"
                        else:
                            # Short time → Crash separated pilot from aircraft
                            if "AType:7" in ln:
                                self.stats.crashed = True
                                if self.stats.wounded:
                                    self.stats.final_state = "Crashed (Wounded)"
                                else:
                                    self.stats.final_state = "Crashed"
                                event_type = "Crash"
                            else:
                                # AType:6 with quick separation = Hard Landing
                                self.stats.landed = True
                                if self.stats.wounded:
                                    self.stats.final_state = "Landed (Wounded)"
                                else:
                                    self.stats.final_state = "Landed"
                                event_type = "Landing"
                    
                    elif "AType:7" in ln:
                        self.stats.crashed = True
                        # Wounded status combines with crash
                        if self.stats.wounded:
                            self.stats.final_state = "Crashed (Wounded)"
                        else:
                            self.stats.final_state = "Crashed"
                        event_type = "Crash"
                    else:
                        self.stats.landed = True
                        # Wounded status combines with landing
                        if self.stats.wounded:
                            self.stats.final_state = "Landed (Wounded)"
                        else:
                            self.stats.final_state = "Landed"
                        event_type = "Landing"
                    
                    self.stats.events.append({
                        "time": ts,
                        "type": event_type,
                        "altitude": altitude,
                        "time_raw": t
                    })

        # --- retroactive proportional kills ---
        for tid, (kill_time, altitude) in destroyed.items():
            hits = [h for h in self.stats.hits if h["target"] == tid]
            if not hits: continue
            total = sum(h["damage"] for h in hits)
            player_dmg = sum(h["damage"] for h in hits if h["attacker"] in (self.stats.player_pid, self.stats.player_plid))
            if total > 0 and player_dmg / total >= 0.8:
                if all(k.id != tid for k in self.stats.kills):
                    obj = self.stats.objects.get(tid)
                    if obj and altitude is not None:
                        obj.altitude = altitude
                    self.stats.add_kill(tid, hits[-1]["time"])
                    
        # --- detect bail-out ---
        parachute_found = any("AType:13" in l and "Paratrooper" in l for l in lines)
        if parachute_found and not self.stats.crashed and not self.stats.landed:
            # Bailout combines with wounded status
            if self.stats.wounded:
                self.stats.final_state = "Bailed Out (Wounded)"
            else:
                self.stats.final_state = "Bailed Out"

        # --- compute flight duration ---
        if self.stats.takeoff_time:
            # Use landing time if available, otherwise use last event time (mission end)
            end_time = self.stats.landing_time
            if not end_time and self.stats.events:
                # No landing recorded - use last event as mission end
                end_time = max((e.get('time_raw', 0) for e in self.stats.events), default=self.stats.takeoff_time)
                # Add Mission End event if no landing
                if end_time > self.stats.takeoff_time:
                    last_ts = self._format_time(end_time)
                    self.stats.events.append({"time": last_ts, "type": "Mission End", "time_raw": end_time})
            
            if end_time:
                duration = end_time - self.stats.takeoff_time
                # IL-2 uses 50 ticks per second (20ms per tick)
                # NOTE: This is GAME TIME (includes time compression!)
                sec = duration / 50.0
                h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
                self.stats.flight_duration = f"{h:02}:{m:02}:{s:02}"

        return self.stats

    # ------------------------------------------------------
    def _resolve_indirect_kill(self, tid, ts, pos_match=None):
        hits = [h for h in self.stats.hits if h["target"] == tid]
        total = sum(h["damage"] for h in hits)
        player = sum(h["damage"] for h in hits if h["attacker"] in (self.stats.player_pid, self.stats.player_plid))
        if total > 0 and player / total >= 0.8:
            obj = self.stats.objects.get(tid)
            if obj and pos_match:
                obj.altitude = int(float(pos_match.group(2)))
            self.stats.add_kill(tid, ts)

    # ------------------------------------------------------
    def _detect_landing_damage(self, events, data):
        """
        Detect and mark landing damage events.
        
        Criteria (ALL must match):
        1. Attacker = Player's aircraft
        2. Time before landing < 30 seconds
        3. Time since last kill > 60 seconds (not in combat)
        4. Relative altitude < 150m above airfield
        
        Args:
            events: List of events
            data: Mission data dict with player info
            
        Returns:
            Modified events list with landing damage marked
        """
        player_aircraft = data['player']['aircraft']
        
        # Find takeoff and landing altitudes (airfield elevation)
        takeoff_alt = None
        landing_alt = None
        landing_time = None
        
        for evt in events:
            if evt.get('type') == 'Takeoff' and evt.get('altitude') is not None:
                takeoff_alt = evt['altitude']
            if evt.get('type') in ['Landing', 'Crash']:
                landing_time = evt.get('time')
                if evt.get('altitude') is not None:
                    landing_alt = evt['altitude']
        
        # Use average of takeoff/landing as airfield elevation
        airfield_alt = None
        if takeoff_alt is not None and landing_alt is not None:
            airfield_alt = (takeoff_alt + landing_alt) / 2
        elif takeoff_alt is not None:
            airfield_alt = takeoff_alt
        elif landing_alt is not None:
            airfield_alt = landing_alt
        
        if not landing_time:
            return events  # No landing, can't detect landing damage
        
        # Find last kill time
        last_kill_time = None
        for evt in reversed(events):
            if evt.get('type') == 'Kill':
                last_kill_time = evt.get('time')
                break
        
        # Check each damage event
        modified_events = []
        has_hard_landing = False
        
        for evt in events:
            if evt.get('type') == 'Damage Taken':
                is_landing_dmg = False
                
                # Criterion 1: Attacker is player's own aircraft
                if evt.get('target') == player_aircraft:
                    damage_time = evt.get('time')
                    damage_alt = evt.get('altitude')
                    
                    # Criterion 2: Time before landing < 60 seconds (increased from 30s)
                    time_diff = self._time_diff_seconds(damage_time, landing_time)
                    if 0 < time_diff < 60:
                        
                        # Criterion 3: Time since last kill > 60 seconds (or no kills)
                        if last_kill_time is None:
                            time_since_kill = 999999  # No kills = not in combat
                        else:
                            time_since_kill = self._time_diff_seconds(last_kill_time, damage_time)
                        
                        if time_since_kill > 60:
                            
                            # Criterion 4: Relative altitude < 150m above airfield
                            if airfield_alt is not None and damage_alt is not None:
                                relative_alt = damage_alt - airfield_alt
                                if relative_alt < 150:
                                    is_landing_dmg = True
                            else:
                                # No altitude data, use other criteria only
                                is_landing_dmg = True
                
                if is_landing_dmg:
                    # Mark as landing damage
                    evt_copy = evt.copy()
                    evt_copy['type'] = 'Landing Damage'
                    evt_copy['original_target'] = evt['target']  # Keep original for reference
                    modified_events.append(evt_copy)
                    has_hard_landing = True
                else:
                    modified_events.append(evt)
            else:
                # Mark landing event as "hard" if we detected landing damage
                if evt.get('type') in ['Landing', 'Crash'] and has_hard_landing:
                    evt_copy = evt.copy()
                    evt_copy['hard_landing'] = True
                    modified_events.append(evt_copy)
                else:
                    modified_events.append(evt)
        
        # Update final state if hard landing detected
        if has_hard_landing and data['summary']['final_state'] == 'Landed':
            data['summary']['final_state'] = 'Landed (Hard Landing)'
        
        return modified_events
    
    # ------------------------------------------------------
    def _time_diff_seconds(self, time1, time2):
        """Calculate difference in seconds between two time strings (HH:MM or HH:MM:SS)"""
        try:
            def parse_time(t):
                parts = t.split(':')
                if len(parts) == 3:
                    h, m, s = map(int, parts)
                elif len(parts) == 2:
                    h, m, s = int(parts[0]), int(parts[1]), 0
                else:
                    return 0
                return h * 3600 + m * 60 + s
            
            return parse_time(time2) - parse_time(time1)
        except:
            return 0

    # ------------------------------------------------------
    def to_json(self, out_path):
        # Filter out BotPilot/BotGunner from kills
        def valid(k): return not any(x in k.type.lower() for x in ["botpilot", "botgunner"])
        kills = [k for k in self.stats.kills if valid(k)]
        
        # Note: static plane name cleaning and is_static flag are now set in GameObject __init__
        
        # Calculate total damage to aircraft and pilot separately
        aircraft_damage = 0.0
        pilot_damage = 0.0
        
        for hit in self.stats.hits:
            if hit["target"] == self.stats.player_plid:
                aircraft_damage += hit["damage"]
            elif hit["target"] in (self.stats.player_pid, self.stats.player_id):
                pilot_damage += hit["damage"]
        
        # Count air kills separately (flying vs parked)
        air_kills_all = [k for k in kills if k.category == "Air"]
        air_kills_flying = sum(1 for k in air_kills_all if not getattr(k, 'is_static', False))
        air_kills_parked = sum(1 for k in air_kills_all if getattr(k, 'is_static', False))

        data = {
            "player": {
                "id": self.stats.player_id,
                "name": self.stats.player_name,
                "aircraft": self.stats.player_aircraft
            },
            "summary": {
                "air_kills": len(air_kills_all),
                "air_kills_flying": air_kills_flying,
                "air_kills_parked": air_kills_parked,
                "ground_kills": sum(1 for k in kills if k.category in ["Ground", "Building"]),
                "naval_kills": sum(1 for k in kills if k.category == "Naval"),
                "flight_duration": self.stats.flight_duration or "N/A",
                "wounded": self.stats.wounded,
                "total_damage_taken": round(self.stats.total_damage_taken, 2),
                "aircraft_damage": round(aircraft_damage * 100, 1),  # As percentage
                "pilot_damage": round(pilot_damage * 100, 1),  # As percentage
                "landed": self.stats.landed,
                "crashed": self.stats.crashed,
                "final_state": self.stats.final_state
            }
        }
        
        # Start with existing events (Takeoff, Landing, Damage)
        events = list(self.stats.events)
        
        # Add kill events (filter out BotPilot/BotGunner)
        for k in kills:
            if k.time_of_kill:
                evt = {
                    "time": k.time_of_kill,
                    "type": "Kill",
                    "target": k.type,
                    "category": k.category
                }
                if k.altitude is not None:
                    evt["altitude"] = k.altitude
                events.append(evt)
        
        # Aggregate damage events by minute (not exact second)
        damage_by_time = {}
        non_damage_events = []
        
        for evt in events:
            if evt.get("type") == "Damage Taken":
                # Group by minute (HH:MM) instead of exact time
                full_time = evt.get("time")
                if full_time and len(full_time.split(':')) >= 2:
                    time_key = ':'.join(full_time.split(':')[:2])  # Take HH:MM only for grouping
                else:
                    time_key = full_time
                
                if time_key not in damage_by_time:
                    damage_by_time[time_key] = {
                        "time": full_time,  # Keep full time with seconds from first event
                        "time_raw": evt.get("time_raw"),
                        "aircraft_damage": 0.0,
                        "pilot_damage": 0.0,
                        "attacker": evt.get("target"),
                        "altitude": evt.get("altitude")
                    }
                
                # Accumulate damage
                damage_str = evt.get("damage", "")
                
                # Parse aggregated damage strings like "4.2% aircraft, 19.2% pilot"
                if "aircraft" in damage_str and "pilot" in damage_str:
                    parts = damage_str.split(",")
                    for part in parts:
                        if "aircraft" in part:
                            dmg_val = float(part.strip().split("%")[0])
                            damage_by_time[time_key]["aircraft_damage"] += dmg_val
                        elif "pilot" in part:
                            dmg_val = float(part.strip().split("%")[0])
                            damage_by_time[time_key]["pilot_damage"] += dmg_val
                elif "aircraft" in damage_str:
                    dmg_val = float(damage_str.split("%")[0])
                    damage_by_time[time_key]["aircraft_damage"] += dmg_val
                elif "pilot" in damage_str:
                    dmg_val = float(damage_str.split("%")[0])
                    damage_by_time[time_key]["pilot_damage"] += dmg_val
            else:
                non_damage_events.append(evt)
        
        # Convert aggregated damage back to events
        for time_key, dmg_data in damage_by_time.items():
            if dmg_data["aircraft_damage"] > 0 and dmg_data["pilot_damage"] > 0:
                # Both aircraft and pilot hit
                non_damage_events.append({
                    "time": dmg_data["time"],
                    "type": "Damage Taken",
                    "target": dmg_data["attacker"],
                    "damage": f"{dmg_data['aircraft_damage']:.1f}% aircraft, {dmg_data['pilot_damage']:.1f}% pilot",
                    "altitude": dmg_data["altitude"],
                    "time_raw": time_key
                })
            elif dmg_data["aircraft_damage"] > 0:
                # Only aircraft
                non_damage_events.append({
                    "time": dmg_data["time"],
                    "type": "Damage Taken",
                    "target": dmg_data["attacker"],
                    "damage": f"{dmg_data['aircraft_damage']:.1f}% aircraft",
                    "altitude": dmg_data["altitude"],
                    "time_raw": time_key
                })
            elif dmg_data["pilot_damage"] > 0:
                # Only pilot
                non_damage_events.append({
                    "time": dmg_data["time"],
                    "type": "Damage Taken",
                    "target": dmg_data["attacker"],
                    "damage": f"{dmg_data['pilot_damage']:.1f}% pilot",
                    "altitude": dmg_data["altitude"],
                    "time_raw": time_key
                })
        
        # Detect landing damage and mark appropriately
        non_damage_events = self._detect_landing_damage(non_damage_events, data)
        
        # Sort all events by time
        def _time_key(evt):
            t = evt.get("time")
            if not t:
                return 999999
            try:
                parts = t.split(":")
                if len(parts) == 3:
                    h, m, s = [int(x) for x in parts]
                elif len(parts) == 2:
                    h, m = [int(x) for x in parts]
                    s = 0  # No seconds, assume :00
                else:
                    return 999999
                return h * 3600 + m * 60 + s
            except Exception:
                return 999999

        non_damage_events.sort(key=_time_key)
        data["events"] = non_damage_events
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✓ JSON exported to {out_path}")

    # ------------------------------------------------------
    @staticmethod
    def _i(t, p): m = re.search(p, t); return int(m.group(1)) if m else -1
    @staticmethod
    def _f(t, p): m = re.search(p, t); return float(m.group(1)) if m else 0.0
    @staticmethod
    def _s(t, p): m = re.search(p, t); return m.group(1).strip() if m else ""


# ==========================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python il2_mission_debrief_v2_2.py <missionReport.txt>")
        sys.exit(1)
    f = sys.argv[1]
    p = MissionDebriefParser(f)
    s = p.parse()
    p.to_json(f.replace(".txt", ".events.json"))
