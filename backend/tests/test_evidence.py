"""Exact input capture survives success/failure and rejects altered replay data."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ['MONGO_URI'] = 'mongodb://localhost:1/?serverSelectionTimeoutMS=1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'validation'))
from fastapi.testclient import TestClient
import api
from evidence import RunEvidence
from replay_capture import load_capture
from reference_presets import sparse_candidates, minimum_distances
from diagnostics import SearchDiagnostics
from windows import WindowVerificationError
import numpy as np


class EvidenceTests(unittest.TestCase):
    def test_final_journal_contains_all_parent_checks_and_rejects_count_mismatch(self):
        from datetime import datetime, timedelta, timezone
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'OPAS_CAPTURE_DIR':directory}):
            capture = RunEvidence('0123456789ab', {})
            start = datetime(2026, 10, 6, tzinfo=timezone.utc)
            for i in range(6):
                capture.record(start+timedelta(seconds=i*5), bool(i%2), 'window_validation')
            # Simulate an interrupted/truncated on-disk append journal.
            (capture.directory/'launches.jsonl').write_text('')
            capture.finish({'status':'complete', 'diagnostics':{'checked_launch_samples':6}})
            checks = [json.loads(line) for line in (capture.directory/'launches.jsonl').read_text().splitlines()]
            self.assertEqual(checks, capture.checks)
            self.assertEqual(len(checks), 6)
            with self.assertRaisesRegex(WindowVerificationError, 'every completed'):
                capture.finish({'status':'complete', 'diagnostics':{'checked_launch_samples':7}})

    def test_real_http_capture_is_downloadable_and_checksum_verified(self):
        docs = [{'altitude_km':420, 'location':{'coordinates':[0,90]}}]
        collection = SimpleNamespace(find=lambda *a: docs, find_one=lambda *a: {})
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'OPAS_CAPTURE_DIR':directory}), \
                patch.object(api, 'collection', collection), TestClient(api.app) as client:
            response = client.get('/safe-windows', params=dict(target_lat=28.573,target_lon=-80.649,
                                      target_alt=420,inclination=51.6,search_hours=1))
            self.assertEqual(response.status_code, 200)
            data = response.json(); evidence = data['diagnostics']['evidence']
            content = client.get(evidence['inputs_url']).content
            raw = gzip.decompress(content)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), evidence['inputs_sha256_uncompressed'])
            inputs = load_capture(Path(directory)/data['diagnostics']['request_id'])
            self.assertEqual(inputs['catalogue'], docs)
            self.assertEqual(inputs['frozen_radii_km'], [10])
            checks = client.get(evidence['checks_url']).text.splitlines()
            self.assertEqual(len(checks), data['diagnostics']['checked_launch_samples'])
            self.assertEqual(client.get(evidence['result_url']).json(), data)
            self.assertEqual(client.get('/safe-windows/evidence/invalid/inputs').status_code,404)
            path = Path(directory)/data['diagnostics']['request_id']/'launches.jsonl'
            path.write_text('altered')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):load_capture(path.parent)

    def test_incomplete_prediction_keeps_inputs_and_never_saves_windows(self):
        doc = {'tle_line1':'invalid', 'altitude_km':420}
        collection = SimpleNamespace(find=lambda *a:[doc],find_one=lambda *a:{})
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'OPAS_CAPTURE_DIR':directory}), \
                patch.object(api, 'collection', collection), TestClient(api.app) as client:
            response = client.get('/safe-windows',params=dict(target_lat=0,target_lon=0,target_alt=420,
                                                           inclination=51.6,search_hours=1))
            self.assertEqual(response.status_code,503)
            run = Path(directory)/response.headers['x-request-id']
            result = json.loads((run/'result.json').read_text())
            self.assertEqual(result['status'],'incomplete')
            self.assertNotIn('windows',result)
            self.assertTrue((run/'inputs.json.gz').is_file())

    def test_independent_sparse_filter_covers_dense_crossings_and_endpoints(self):
        rng = np.random.default_rng(1946)
        xyz = np.cumsum(rng.normal(size=(200,3))*4,axis=0)
        vehicle = np.cumsum(rng.normal(size=(65,3))*4,axis=0)
        lower = np.arange(70)[:,None]+np.arange(65)[None,:]
        fraction = np.full(lower.shape+(1,), .35)
        exact = xyz[lower]*(1-fraction)+xyz[lower+1]*fraction
        distance = minimum_distances(exact,vehicle)
        for stride in [2,15,30]:
            selected,bounds = sparse_candidates(xyz,lower,fraction,vehicle,3,stride,1)
            self.assertTrue(set(np.flatnonzero(distance<3)).issubset(selected))
            excluded = np.setdiff1d(np.arange(70),selected)
            self.assertTrue((bounds[excluded]>3).all())

    def test_cancellation_during_preparation_saves_incomplete_capture(self):
        collection = SimpleNamespace(find=lambda *a:[],find_one=lambda *a:{})
        def publish(event):
            if event['data'].get('phase') == 'orbital_data_ready':
                raise WindowVerificationError('client disconnected')
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'OPAS_CAPTURE_DIR':directory}), \
                patch.object(api,'collection',collection):
            trace=SearchDiagnostics('0123456789ab',publish)
            with self.assertRaisesRegex(WindowVerificationError,'disconnected'):
                api._run_window_search(28.573,-80.649,420,51.6,1,trace)
            result=json.loads((Path(directory)/'0123456789ab/result.json').read_text())
            self.assertEqual(result['status'],'incomplete')
            self.assertEqual(result['diagnostics']['status'],'incomplete')
            self.assertNotIn('windows',result)
            load_capture(Path(directory)/'0123456789ab')

if __name__ == '__main__': unittest.main()
