"""
Unit tests for solar_eclipse.py, covering key functions with mock data and patching file access.
"""

import unittest
from unittest.mock import patch, mock_open
import math
import os
from src.solareclipseworkbench import solar_eclipse

class TestSolarEclipse(unittest.TestCase):
    def test_solve_quadrant(self):
        self.assertAlmostEqual(solar_eclipse.solve_quadrant(1, 1), math.asin(1))
        self.assertAlmostEqual(solar_eclipse.solve_quadrant(-1, 1), math.asin(-1))
        self.assertAlmostEqual(solar_eclipse.solve_quadrant(-1, -1), -math.acos(-1))
        self.assertAlmostEqual(solar_eclipse.solve_quadrant(1, -1), math.acos(-1))

    # Only the two catalogue paths are replaced: pathlib (e.g. looking for the ephemeris) also calls os.path.join
    @patch('os.path.join', side_effect=lambda *parts, _join=os.path.join:
           parts[-1] if parts[-1] in ('eclipse_besselian.csv', 'deltat.csv') else _join(*parts))
    @patch('builtins.open')
    @patch('csv.DictReader')
    def test_get_element_coeffs(self, mock_csv_dictreader, mock_open, mock_join):
        eclipse_row = {'year': '2024', 'month': '4', 'day': '8', 'julian_date': '2460400.5', 'dt': '69.0', 't0': '18.0', 'x0': '0.1', 'x1': '0.2', 'x2': '0.3', 'x3': '0.4', 'y0': '0.5', 'y1': '0.6', 'y2': '0.7', 'y3': '0.8', 'd0': '0.9', 'd1': '1.0', 'd2': '1.1', 'l10': '1.2', 'l11': '1.3', 'l12': '1.4', 'l20': '1.5', 'l21': '1.6', 'l22': '1.7', 'mu0': '1.8', 'mu1': '1.9', 'mu2': '2.0', 'tan_f1': '2.1', 'tan_f2': '2.2', 'eclipse_type': 'P', 'eclipse_date': solar_eclipse.datetime(2024, 4, 8)}
        deltat_row = {'year': '2024', 'deltat': '69.0'}
        class MockFile:
            def __init__(self, name):
                self.name = name
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
        mock_file_eclipse = MockFile('eclipse_besselian.csv')
        mock_file_deltat = MockFile('deltat.csv')
        def open_side_effect(filename, *args, **kwargs):
            if filename == 'eclipse_besselian.csv':
                return mock_file_eclipse
            elif filename == 'deltat.csv':
                return mock_file_deltat
            raise FileNotFoundError
        mock_open.side_effect = open_side_effect
        def dictreader_side_effect(file, *args, **kwargs):
            if file.name == 'eclipse_besselian.csv':
                return iter([eclipse_row])
            elif file.name == 'deltat.csv':
                return iter([deltat_row])
            return iter([])
        mock_csv_dictreader.side_effect = dictreader_side_effect
        result = solar_eclipse.get_element_coeffs('2024-04-08')
        self.assertIsInstance(result, dict)
        self.assertIn('jd', result)
        self.assertEqual(result['type'], 'P')

    def test_get_elements(self):
        e = {
            'X0': 0.1, 'X1': 0.2, 'X2': 0.3, 'X3': 0.4,
            'Y0': 0.5, 'Y1': 0.6, 'Y2': 0.7, 'Y3': 0.8,
            'd0': 0.9, 'd1': 1.0, 'd2': 1.1,
            'M0': 1.2, 'M1': 1.3,
            'L10': 1.4, 'L11': 1.5, 'L12': 1.6,
            'L20': 1.7, 'L21': 1.8, 'L22': 1.9,
            'tanf1': 2.0, 'tanf2': 2.1,
            'Δt': 69.0
        }
        t, phi, lam, height = 0.1, 45.0, 90.0, 0.0
        result = solar_eclipse.get_elements(e, t, phi, lam, height)
        self.assertIsInstance(result, dict)
        self.assertIn('X', result)
        self.assertIn('Y', result)

    def test_compute_estimate_and_refine(self):
        e = {
            'X0': 0.1, 'X1': 0.2, 'X2': 0.3, 'Y0': 0.3, 'Y1': 0.4,
            'd0': 0.5, 'M1': 0.6, 'X3': 0.7, 'Y2': 0.8, 'L10': 0.9, 'L11': 1.0,
            'Y3': 1.1, 'L12': 1.2, 'L20': 1.3, 'L21': 1.4, 'L22': 1.5,
            'd1': 1.6, 'd2': 1.7, 'tanf1': 1.8, 'tanf2': 1.9,
        }
        est = solar_eclipse.compute_estimate(e)
        self.assertIn('tau1', est)
        self.assertIn('tau2', est)
        ref = solar_eclipse.refine_estimate(e, est['tau1'])
        self.assertIn('tau1', ref)
        self.assertIn('tau2', ref)

if __name__ == '__main__':
    unittest.main()
