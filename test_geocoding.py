#!/usr/bin/env python3
"""
Quick test script for the geocoding functionality.
Tests the GeocodingWorker class with a known location.
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication
from src.solareclipseworkbench.wizard import GeocodingWorker, GEOPY_AVAILABLE

def test_geocoding():
    """Test geocoding with a known location."""
    print(f"Geopy available: {GEOPY_AVAILABLE}")
    
    if not GEOPY_AVAILABLE:
        print("ERROR: geopy not available!")
        return False
    
    # Create QApplication (required for QThread)
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    
    # Test address
    test_address = "Carbondale, Illinois, USA"
    print(f"\nTesting geocoding for: {test_address}")
    print("This will take a few seconds (respecting Nominatim usage policy)...\n")
    
    # Track if we got a result
    result_received = [False]
    
    def on_finished(result):
        """Handle successful result."""
        result_received[0] = True
        print("✓ Geocoding successful!")
        print(f"  Location: {result['display_name']}")
        print(f"  Latitude: {result['latitude']:.5f}°")
        print(f"  Longitude: {result['longitude']:.5f}°")
        print(f"  Altitude: {result['altitude']:.1f} m")
        app.quit()
    
    def on_error(error_msg):
        """Handle error."""
        result_received[0] = True
        print(f"✗ Geocoding failed: {error_msg}")
        app.quit()
    
    # Create and start worker
    worker = GeocodingWorker(test_address)
    worker.finished.connect(on_finished)
    worker.error.connect(on_error)
    worker.start()
    
    # Run event loop
    app.exec()
    
    return result_received[0]

if __name__ == "__main__":
    success = test_geocoding()
    sys.exit(0 if success else 1)
