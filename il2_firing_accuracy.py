#!/usr/bin/env python3
"""
IL-2 Great Battles - Firing Accuracy Tracker
Analyzes weapon accuracy from mission reports
"""

import re
import yaml
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict


class FiringAccuracyTracker:
    """Track firing accuracy per weapon/caliber from mission reports"""
    
    def __init__(self, weapons_yaml_path: str = "weapons_mappings.yaml"):
        """
        Initialize tracker with weapons mappings
        
        Args:
            weapons_yaml_path: Path to weapons_mappings.yaml
        """
        self.weapons_yaml_path = weapons_yaml_path
        self.projectile_to_weapon = {}
        self.projectile_to_caliber = {}
        self.aircraft_weapons = {}
        
        # Load mappings
        self._load_weapons_mappings()
        
        # Ammo tracking
        self.start_ammo = {'bullets': 0, 'shells': 0}
        self.end_ammo = {'bullets': 0, 'shells': 0}
        
        # Accuracy stats
        self.stats = {
            'by_projectile': defaultdict(lambda: {'shots': 0, 'hits': 0}),
            'by_weapon': defaultdict(lambda: {'shots': 0, 'hits': 0}),
            'by_caliber': defaultdict(lambda: {'shots': 0, 'hits': 0}),
            'total': {'shots': 0, 'hits': 0}
        }
    
    def _load_weapons_mappings(self):
        """Load projectile/weapon/aircraft mappings from YAML"""
        try:
            with open(self.weapons_yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            # Build projectile → weapon mapping
            for projectile_name, projectile_data in data.get('projectiles', {}).items():
                weapons = projectile_data.get('weapons', [])
                caliber = projectile_data.get('caliber', 'Unknown')
                
                self.projectile_to_weapon[projectile_name] = weapons
                self.projectile_to_caliber[projectile_name] = caliber
            
            # Build aircraft → weapons mapping
            for aircraft_name, aircraft_data in data.get('aircraft', {}).items():
                weapons = aircraft_data.get('weapons', [])
                self.aircraft_weapons[aircraft_name] = weapons
                
        except FileNotFoundError:
            print(f"Warning: {self.weapons_yaml_path} not found!")
        except Exception as e:
            print(f"Error loading weapons mappings: {e}")
    
    def parse_mission_report(self, report_path: str, player_aircraft: str = None) -> Dict:
        """
        Parse mission report and extract firing accuracy
        
        Args:
            report_path: Path to missionReport.txt
            player_aircraft: Player's aircraft type (optional, for filtering)
            
        Returns:
            Dictionary with accuracy stats
        """
        # Reset stats
        self.stats = {
            'by_projectile': defaultdict(lambda: {'shots': 0, 'hits': 0}),
            'by_weapon': defaultdict(lambda: {'shots': 0, 'hits': 0}),
            'by_caliber': defaultdict(lambda: {'shots': 0, 'hits': 0}),
            'total': {'shots': 0, 'hits': 0}
        }
        self.start_ammo = {'bullets': 0, 'shells': 0}
        self.end_ammo = {'bullets': 0, 'shells': 0}
        
        player_id = None
        player_plid = None
        
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    
                    # Find player ID and initial ammo
                    if 'ISPL:1' in line and 'AType:10' in line:
                        # Extract PLID and PID
                        plid_match = re.search(r'PLID:(\d+)', line)
                        pid_match = re.search(r'PID:(\d+)', line)
                        if plid_match:
                            player_plid = plid_match.group(1)
                        if pid_match:
                            player_id = pid_match.group(1)
                        
                        # Extract starting ammo
                        bul_match = re.search(r'BUL:(\d+)', line)
                        sh_match = re.search(r'SH:(\d+)', line)
                        if bul_match:
                            self.start_ammo['bullets'] = int(bul_match.group(1))
                        if sh_match:
                            self.start_ammo['shells'] = int(sh_match.group(1))
                    
                    # Find player end ammo (AType:4 = mission end OR last position before bailout)
                    if 'AType:4' in line and player_plid:
                        plid_match = re.search(r'PLID:(\d+)', line)
                        if plid_match and plid_match.group(1) == player_plid:
                            # Extract ending ammo
                            bul_match = re.search(r'BUL:(\d+)', line)
                            sh_match = re.search(r'SH:(\d+)', line)
                            if bul_match:
                                self.end_ammo['bullets'] = int(bul_match.group(1))
                            if sh_match:
                                self.end_ammo['shells'] = int(sh_match.group(1))
                    
                    # Also check pilot separation (AType:18) for bailout ammo count
                    if 'AType:18' in line and player_id:
                        pid_match = re.search(r'PID:(\d+)', line)
                        if pid_match and pid_match.group(1) == player_id:
                            # This is bailout - check for ammo in nearby AType:4
                            # (Sometimes AType:4 with ammo comes right before AType:18)
                            pass  # We'll capture it from AType:4 if available
                    
                    # Parse shooting events (AType:1)
                    if 'AType:1' in line and 'AMMO:' in line:
                        self._parse_shot_event(line, player_plid)
            
            # Calculate total shots fired based on ammo consumption
            self._calculate_total_shots()
            
        except FileNotFoundError:
            print(f"Error: Mission report not found: {report_path}")
        except Exception as e:
            print(f"Error parsing mission report: {e}")
        
        return self.get_stats()
    
    def _parse_shot_event(self, line: str, player_id: Optional[str]):
        """
        Parse a single AType:1 (shooting) event
        
        Format: T:12345 AType:1 AMMO:BULLET_GER_13x64_AP DIST:234.5 AID:123456 TID:789012
        
        AID = Attacker ID
        TID = Target ID  
        DIST = Distance
        AMMO = Projectile type
        """
        # Extract attacker ID
        aid_match = re.search(r'AID:(\d+)', line)
        if not aid_match:
            return
        
        attacker_id = aid_match.group(1)
        
        # Only count player shots
        if player_id and attacker_id != player_id:
            return
        
        # Extract projectile type
        ammo_match = re.search(r'AMMO:([A-Za-z0-9_\-x]+)', line)
        if not ammo_match:
            return
        
        projectile = ammo_match.group(1)
        
        # CRITICAL: Skip explosion events (they are secondary effects, not actual shots)
        if projectile == 'explosion':
            return
        
        # Check if it's a hit (TID present means something was hit)
        tid_match = re.search(r'TID:(\d+)', line)
        is_hit = tid_match is not None
        
        # Update stats
        self._record_shot(projectile, is_hit)
    
    def _record_shot(self, projectile: str, is_hit: bool):
        """Record a shot and update all stat categories"""
        
        # Update projectile stats (only hits, shots calculated later)
        if is_hit:
            self.stats['by_projectile'][projectile]['hits'] += 1
        
        # Update weapon stats
        weapons = self.projectile_to_weapon.get(projectile, [])
        for weapon in weapons:
            if is_hit:
                self.stats['by_weapon'][weapon]['hits'] += 1
        
        # Update caliber stats
        caliber = self.projectile_to_caliber.get(projectile, 'Unknown')
        if is_hit:
            self.stats['by_caliber'][caliber]['hits'] += 1
        
        # Update total
        if is_hit:
            self.stats['total']['hits'] += 1
    
    def _calculate_total_shots(self):
        """Calculate total shots fired based on ammo consumption"""
        # Calculate bullets and shells fired
        bullets_fired = self.start_ammo['bullets'] - self.end_ammo['bullets']
        shells_fired = self.start_ammo['shells'] - self.end_ammo['shells']
        
        # Only calculate shots if we have valid ammo tracking
        # (end_ammo will be 0 if player bailed out or unlimited ammo)
        total_fired = bullets_fired + shells_fired
        
        if total_fired > 0:
            # We have valid ammo tracking!
            self.stats['total']['shots'] = total_fired
            self.stats['total']['ammo_tracked'] = True
        else:
            # No ammo tracking (unlimited or bailout)
            self.stats['total']['shots'] = 0
            self.stats['total']['ammo_tracked'] = False
    
    def get_stats(self) -> Dict:
        """Get current accuracy statistics"""
        return {
            'by_projectile': dict(self.stats['by_projectile']),
            'by_weapon': dict(self.stats['by_weapon']),
            'by_caliber': dict(self.stats['by_caliber']),
            'total': self.stats['total']
        }
    
    def calculate_accuracy(self, shots: int, hits: int) -> float:
        """Calculate accuracy percentage"""
        if shots == 0:
            return 0.0
        return (hits / shots) * 100.0
    
    def get_summary(self) -> str:
        """Generate human-readable summary"""
        lines = []
        
        # Check if ammo was tracked
        ammo_tracked = self.stats['total'].get('ammo_tracked', False)
        total_shots = self.stats['total'].get('shots', 0)
        total_hits = self.stats['total']['hits']
        
        lines.append("FIRING STATISTICS")
        lines.append("=" * 60)
        
        if not ammo_tracked:
            lines.append("Note: Ammo tracking unavailable (unlimited ammo or bailout)")
            lines.append("")
        
        lines.append(f"Total Hits: {total_hits:,}")
        if ammo_tracked and total_shots > 0:
            total_acc = self.calculate_accuracy(total_shots, total_hits)
            lines.append(f"Total Shots: {total_shots:,}")
            lines.append(f"Overall Accuracy: {total_acc:.1f}%")
        lines.append("")
        
        # By caliber
        if self.stats['by_caliber']:
            lines.append("BY CALIBER:")
            lines.append("-" * 60)
            for caliber, data in sorted(self.stats['by_caliber'].items()):
                if caliber == 'Unknown':
                    continue  # Skip unknowns
                hits = data['hits']
                
                if ammo_tracked:
                    # Calculate proportional shots for this caliber
                    if total_hits > 0:
                        caliber_shots = int(total_shots * (hits / total_hits))
                        acc = self.calculate_accuracy(caliber_shots, hits)
                        lines.append(f"  {caliber:12s}  Shots: ~{caliber_shots:4,}  Hits: {hits:4,}  Acc: ~{acc:5.1f}%")
                    else:
                        lines.append(f"  {caliber:12s}  Hits: {hits:4,}  Accuracy: N/A")
                else:
                    lines.append(f"  {caliber:12s}  Hits: {hits:4,}  Accuracy: N/A")
            lines.append("")
        
        # By weapon
        if self.stats['by_weapon']:
            lines.append("BY WEAPON:")
            lines.append("-" * 60)
            for weapon, data in sorted(self.stats['by_weapon'].items()):
                hits = data['hits']
                
                if ammo_tracked:
                    # Calculate proportional shots for this weapon
                    if total_hits > 0:
                        weapon_shots = int(total_shots * (hits / total_hits))
                        acc = self.calculate_accuracy(weapon_shots, hits)
                        lines.append(f"  {weapon:20s}  Shots: ~{weapon_shots:4,}  Hits: {hits:4,}  Acc: ~{acc:5.1f}%")
                    else:
                        lines.append(f"  {weapon:20s}  Hits: {hits:4,}  Accuracy: N/A")
                else:
                    lines.append(f"  {weapon:20s}  Hits: {hits:4,}  Accuracy: N/A")
        
        return "\n".join(lines)
    
    def export_to_json(self) -> Dict:
        """Export stats in JSON-friendly format"""
        stats = self.get_stats()
        
        # Add accuracy percentages
        for category in ['by_projectile', 'by_weapon', 'by_caliber']:
            for item, data in stats[category].items():
                data['accuracy'] = self.calculate_accuracy(data['shots'], data['hits'])
        
        stats['total']['accuracy'] = self.calculate_accuracy(
            stats['total']['shots'],
            stats['total']['hits']
        )
        
        return stats


def main():
    """Example usage"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python il2_firing_accuracy.py <mission_report.txt> [weapons_mappings.yaml]")
        sys.exit(1)
    
    mission_report = sys.argv[1]
    weapons_yaml = sys.argv[2] if len(sys.argv) > 2 else "weapons_mappings.yaml"
    
    # Create tracker
    tracker = FiringAccuracyTracker(weapons_yaml)
    
    # Parse mission
    tracker.parse_mission_report(mission_report)
    
    # Print summary
    print(tracker.get_summary())
    
    # Export JSON
    import json
    stats = tracker.export_to_json()
    print("\n\nJSON Export:")
    print(json.dumps(stats, indent=2))


if __name__ == '__main__':
    main()
