"""A changed orbital TLE must not reuse a propagator for older elements."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ['MONGO_URI']='mongodb://localhost:1/?serverSelectionTimeoutMS=1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db


class SatelliteCacheTests(unittest.TestCase):
    def test_unchanged_both_lines_reuse_propagator(self):
        doc={'norad_id':987654,'tle_line1':'first line','tle_line2':'second line'}
        with patch.dict(db._sat_cache,clear=True), patch.object(db,'EarthSatellite',return_value=object()) as build:
            first=db.get_sat(doc)
            self.assertIs(db.get_sat(doc),first)
            self.assertEqual(build.call_count,1)

    def test_second_line_change_rebuilds_propagator(self):
        doc={'norad_id':987654,'tle_line1':'same first line','tle_line2':'old orbit'}
        old,new=object(),object()
        with patch.dict(db._sat_cache,clear=True), patch.object(db,'EarthSatellite',side_effect=[old,new]) as build:
            self.assertIs(db.get_sat(doc),old)
            self.assertIs(db.get_sat({**doc,'tle_line2':'updated orbit'}),new)
            self.assertEqual(build.call_count,2)
