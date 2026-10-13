"""Test that all partial phase actions are generated without limits and sync_cameras are included."""

import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from solareclipseworkbench.wizard import SummaryPage

def test_full_partial_generation():
    """Test that generates all partial phase shots and includes sync_cameras."""
    
    # Create QApplication (required for Qt widgets); reuse one if another test already made it
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Create a mock wizard with all necessary fields
    mock_wizard = MagicMock()
    
    # Eclipse configuration
    mock_wizard.field.side_effect = lambda key: {
        'eclipse_name': '2026 Spain Total Solar Eclipse',
        'eclipse_date': 'August 12, 2026',
        'eclipse_type': 'Total',
        'location': 'Valencia, Spain',
        'latitude': '39.47',
        'longitude': '-0.38',
        'altitude': '16',
        
        # Camera settings
        'camera_name': 'Canon EOS R5',
        'focal_length': 600,
        'aperture_min': 5.6,
        'aperture_max': 32,
        'preferred_iso': 400,
        'iso_min': 100,
        'iso_max': 6400,
        'filter_value': '5.0',
        
        # Phenomena
        'c1_c4': True,
        'equispaced': True,
        'partial_magnitude': False,
        'seconds_value': 10,  # 10 seconds interval - should generate 150+ shots per phase
        'diamond': True,
        'bailys': True,
        'corona': True,
        'corona_steps': 2,
        'chromosphere': True,
        'prominences': True,
        
        # Sync settings
        'sync_enabled': True,
        'sync_interval': '5 minutes',
        
        # Voice settings
        'voice_enabled': True,
        'voice_basic': False,  # Use extended voice prompts
    }.get(key, None)
    
    # Create summary page
    summary_page = SummaryPage()
    summary_page.wizard = lambda: mock_wizard
    
    # Generate the script
    script = summary_page._generate_script()
    
    print("="*80)
    print("FULL PARTIAL PHASE GENERATION TEST")
    print("="*80)
    print()
    
    # Count different types of commands
    lines = script.split('\n')
    take_picture_c1_c2 = [l for l in lines if 'take_picture' in l and 'Partial C1-C2' in l]
    take_picture_c3_c4 = [l for l in lines if 'take_picture' in l and 'Partial C3-C4' in l]
    # Total eclipses anchor C1-C2 syncs to C2 (counting back), partial eclipses to C1
    sync_cameras_c1_c2 = [l for l in lines if 'sync_cameras, C2, -' in l or 'sync_cameras, C1, +' in l]
    sync_cameras_c3_c4 = [l for l in lines if 'sync_cameras, C3, +' in l]
    voice_prompts = [l for l in lines if 'voice_prompt,' in l]
    
    # Check for example sync commands that should be removed
    example_sync = [l for l in lines if 'Example sync commands' in l]
    
    # Check for shots below horizon (should be none)
    below_horizon = [l for l in lines if 'sun -' in l and 'take_picture' in l]
    
    print(f"Partial C1-C2 shots generated: {len(take_picture_c1_c2)}")
    print(f"Partial C3-C4 shots generated: {len(take_picture_c3_c4)}")
    print(f"Total partial shots: {len(take_picture_c1_c2) + len(take_picture_c3_c4)}")
    print()
    print(f"Sync commands C1-C2: {len(sync_cameras_c1_c2)}")
    print(f"Sync commands C3-C4: {len(sync_cameras_c3_c4)}")
    print(f"Total sync commands: {len(sync_cameras_c1_c2) + len(sync_cameras_c3_c4)}")
    print()
    print(f"Voice prompts included: {len(voice_prompts)}")
    print(f"Example sync commands (should be 0): {len(example_sync)}")
    print(f"Shots below horizon (should be 0): {len(below_horizon)}")
    print()
    
    # Show first and last few C1-C2 shots
    print("First 5 C1-C2 shots:")
    for line in take_picture_c1_c2[:5]:
        print(f"  {line}")
    print()
    
    print("Last 5 C1-C2 shots:")
    for line in take_picture_c1_c2[-5:]:
        print(f"  {line}")
    print()
    
    # Show some sync commands
    if sync_cameras_c1_c2:
        print("First few sync_cameras commands during C1-C2:")
        for line in sync_cameras_c1_c2[:5]:
            print(f"  {line}")
        print()
    
    # Show some voice prompts
    if voice_prompts:
        print("First 10 voice prompts:")
        for line in voice_prompts[:10]:
            print(f"  {line}")
        print()
        print("Last 5 voice prompts:")
        for line in voice_prompts[-5:]:
            print(f"  {line}")
        print()
    
    # Verify we have MORE than 50 shots (the old limit)
    # With 10-second intervals and ~25-50 minute phases, we should get 150+ shots per phase
    print(f"Expected: C1-C2 duration ~25min = ~150 shots at 10s intervals")
    print(f"Expected: C3-C4 duration ~50min = ~300 shots at 10s intervals")
    print()
    
    assert len(take_picture_c1_c2) > 100, f"Expected >100 C1-C2 shots, got {len(take_picture_c1_c2)} (old limit was 50)"
    assert len(take_picture_c3_c4) > 100, f"Expected >100 C3-C4 shots, got {len(take_picture_c3_c4)} (old limit was 50)"
    
    # Verify sync commands are present
    assert len(sync_cameras_c1_c2) > 0, "Expected sync_cameras during C1-C2 phase"
    assert len(sync_cameras_c3_c4) > 0, "Expected sync_cameras during C3-C4 phase"
    
    # Verify voice prompts are included
    assert len(voice_prompts) > 50, f"Expected >50 voice prompts, got {len(voice_prompts)}"
    
    # Verify no example sync commands
    assert len(example_sync) == 0, f"Example sync commands should be removed, found {len(example_sync)}"
    
    # Verify no shots below horizon
    assert len(below_horizon) == 0, f"Shots below horizon should be filtered out, found {len(below_horizon)}"
    
    print("✓ All tests passed!")
    print(f"✓ Generated {len(take_picture_c1_c2)} C1-C2 shots (exceeds old 50-shot limit)")
    print(f"✓ Generated {len(take_picture_c3_c4)} C3-C4 shots (exceeds old 50-shot limit)")
    print(f"✓ sync_cameras commands interspersed throughout partial phases")
    print(f"✓ Voice prompts included: {len(voice_prompts)} prompts")
    print(f"✓ Example sync commands removed")
    print(f"✓ All shots are above horizon (no negative sun altitudes)")
    
    # Save sample output for inspection
    output_file = Path(__file__).parent / 'test_full_script_output.txt'
    output_file.write_text(script, encoding='utf-8')
    print()
    print(f"Full script saved to: {output_file}")
    
if __name__ == '__main__':
    test_full_partial_generation()
