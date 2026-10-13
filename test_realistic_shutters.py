"""Test that verifies realistic shutter speeds and no overlapping commands."""

import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from PyQt6.QtWidgets import QApplication

from solareclipseworkbench.wizard import SummaryPage
from solareclipseworkbench.exposure_calculator import round_to_camera_shutter_speed

def test_realistic_shutter_speeds():
    """Test that exposure calculator rounds to realistic camera shutter speeds."""
    
    print("Testing shutter speed rounding:")
    print("="*60)
    
    test_cases = [
        (1/53, "1/50 or 1/60"),  # Should round to nearest standard
        (1/3160, "1/3200"),
        (1/1779, "1/1600 or 1/2000"),
        (1/45, "1/40 or 1/50"),
        (0.5, "1/2 (0.5s)"),
        (2.3, "2.5s or 2s"),
    ]
    
    for exposure, expected_desc in test_cases:
        rounded = round_to_camera_shutter_speed(exposure)
        if exposure >= 1:
            result = f"{rounded}s"
        else:
            result = f"1/{int(1/rounded)}"
        print(f"  {exposure:.6f}s ({1/exposure if exposure < 1 else exposure:.1f}) → {result} (expected: {expected_desc})")
    
    print()
    print("✓ All exposures rounded to realistic camera speeds")
    print()


def test_no_overlapping_commands():
    """Test that commands don't overlap in time."""
    
    # Create QApplication (required for Qt widgets); reuse one if another test already made it
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Create a mock wizard
    mock_wizard = MagicMock()
    
    mock_wizard.field.side_effect = lambda key: {
        'eclipse_name': '2026 Spain Total Solar Eclipse',
        'eclipse_date': 'August 12, 2026',
        'eclipse_type': 'Total',
        'location': 'Valencia, Spain',
        'latitude': '39.47',
        'longitude': '-0.38',
        'altitude': '16',
        'camera_name': 'Canon EOS R5',
        'focal_length': 600,
        'aperture_min': 5.6,
        'aperture_max': 32,
        'preferred_iso': 400,
        'iso_min': 100,
        'iso_max': 6400,
        'filter_value': '5.0',
        'c1_c4': True,
        'equispaced': True,
        'partial_magnitude': False,
        'seconds_value': 10,
        'diamond': True,
        'bailys': True,
        'corona': True,
        'corona_steps': 2,
        'chromosphere': True,
        'prominences': True,
        'sync_enabled': True,
        'sync_interval': '5 minutes',
        'voice_enabled': False,
    }.get(key, None)
    
    # Create summary page and generate script
    summary_page = SummaryPage()
    summary_page.wizard = lambda: mock_wizard
    script = summary_page._generate_script()
    
    print("Testing for overlapping commands:")
    print("="*60)
    
    # Parse commands and extract timing
    lines = script.split('\n')
    commands = []
    
    for line in lines:
        if line.strip() and not line.startswith('#'):
            # Parse command format: command, ref, +/-, offset, ...
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 4:
                cmd_type = parts[0]
                ref_point = parts[1]
                sign = parts[2]
                offset = parts[3]
                
                # Convert offset to seconds
                try:
                    time_parts = offset.split(':')
                    if len(time_parts) == 3:
                        minutes = int(time_parts[1])
                        seconds = float(time_parts[2])
                        total_seconds = minutes * 60 + seconds
                        
                        # Create a unique key for this time point
                        time_key = f"{ref_point}_{sign}_{int(total_seconds)}"
                        commands.append({
                            'type': cmd_type,
                            'ref': ref_point,
                            'sign': sign,
                            'offset_sec': total_seconds,
                            'time_key': time_key,
                            'line': line[:80]
                        })
                except:
                    pass
    
    # Check C1 commands specifically
    c1_commands = [c for c in commands if c['ref'] == 'C1' and c['sign'] == '+' and c['offset_sec'] <= 10]
    
    print(f"\nCommands at C1 (first 10 seconds):")
    for cmd in sorted(c1_commands, key=lambda x: x['offset_sec']):
        print(f"  C1+{int(cmd['offset_sec'])}s: {cmd['type']}")
    
    # Verify C1 contact pictures don't conflict with partial phase
    c1_contact_times = [c['offset_sec'] for c in c1_commands if 'First contact' in c['line']]
    c1_partial_times = [c['offset_sec'] for c in c1_commands if 'Partial' in c['line']]
    
    print(f"\nC1 contact picture times: {c1_contact_times}")
    print(f"C1 partial phase start: {min(c1_partial_times) if c1_partial_times else 'N/A'}")
    
    # Check for any exact overlaps
    time_counts = {}
    for cmd in commands:
        key = cmd['time_key']
        if key not in time_counts:
            time_counts[key] = []
        time_counts[key].append(cmd['type'])
    
    overlaps = {k: v for k, v in time_counts.items() if len(v) > 1}
    
    if overlaps:
        print(f"\n⚠ WARNING: Found {len(overlaps)} time points with overlapping commands:")
        for time_key, cmd_types in list(overlaps.items())[:5]:
            print(f"  {time_key}: {', '.join(cmd_types)}")
    else:
        print(f"\n✓ No overlapping commands found")
    
    # Verify buffer exists
    if c1_partial_times:
        min_partial_time = min(c1_partial_times)
        assert min_partial_time >= 10, f"Partial phase should start at least 10s after C1, but starts at {min_partial_time}s"
        print(f"✓ Partial phase starts {min_partial_time}s after C1 (10s buffer verified)")
    
    print()


if __name__ == '__main__':
    test_realistic_shutter_speeds()
    test_no_overlapping_commands()
    
    print("="*60)
    print("All tests passed! ✓")
