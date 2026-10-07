"""Local, request-scoped reproducible inputs; contains orbital data, no secrets."""
import gzip
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import platform
from proximity import HAS_NATIVE_MATH
from sgp4.api import accelerated
from windows import WindowVerificationError

log = logging.getLogger('opas')


def evidence_root():
    return Path(os.getenv('OPAS_CAPTURE_DIR', str(Path(__file__).parent/'run-evidence')))


class RunEvidence:
    def __init__(self, request_id, inputs):
        self.directory = evidence_root()/request_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.inputs = inputs
        self.checks = []
        root = Path(__file__).parent
        self.inputs.update(schema_version=1, request_id=request_id,
            python=platform.python_version(), platform=platform.platform(),
            native_helpers_available=HAS_NATIVE_MATH, accelerated_sgp4=accelerated,
            native_geometry_source_sha256=hashlib.sha256((root/'native/opas_math.cpp').read_bytes()).hexdigest(),
            package_versions={name: importlib.metadata.version(name)
                              for name in ['skyfield', 'sgp4', 'numpy']},
            source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in root.glob('*.py')},
            thread_environment={k: os.environ.get(k) for k in
                                ['OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS']})
        self.write_inputs()
        (self.directory/'launches.jsonl').write_text('')
        log.info('request=%s | reproducible evidence: %s', request_id, self.directory)

    def write_inputs(self):
        raw = json.dumps(self.inputs, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode()
        target = self.directory/'inputs.json.gz'
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(gzip.compress(raw, mtime=0))
        temporary.replace(target)
        self.sha256 = hashlib.sha256(raw).hexdigest()

    def prepared(self, items):
        radii = {id(doc): radius for _, doc, radius in items}
        self.inputs['frozen_radii_km'] = [radii.get(id(d)) for d in self.inputs['catalogue']]
        self.write_inputs()

    def record(self, point, obstructed, phase):
        entry = {'launch_time': point.isoformat(), 'obstructed': obstructed, 'phase': phase}
        with (self.directory/'launches.jsonl').open('a', encoding='utf-8') as checks:
            checks.write(json.dumps(entry)+'\n')
        self.checks.append(entry)

    def links(self):
        request_id = self.inputs['request_id']
        return {'inputs_sha256_uncompressed': self.sha256,
                'inputs_url': f'/safe-windows/evidence/{request_id}/inputs',
                'checks_url': f'/safe-windows/evidence/{request_id}/checks',
                'result_url': f'/safe-windows/evidence/{request_id}/result'}

    def finish(self, result):
        diagnostics = result.get('diagnostics', {})
        status = result.get('status', diagnostics.get('status'))
        if status == 'complete' and (
                diagnostics.get('checked_launch_samples') != len(self.checks) or
                len({e['launch_time'] for e in self.checks}) != len(self.checks)):
            raise WindowVerificationError('Evidence journal does not cover every completed launch check.')
        # Append during work to preserve interrupted runs. On completion write
        # the complete parent-consumed journal atomically before checksumming it.
        journal = self.directory/'launches.jsonl'
        temporary = journal.with_suffix('.tmp')
        temporary.write_text(''.join(json.dumps(e)+'\n' for e in self.checks), encoding='utf-8')
        temporary.replace(journal)
        raw = json.dumps(result, indent=2, allow_nan=False).encode()
        target = self.directory/'result.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(raw)
        temporary.replace(target)
        manifest = {'schema_version': 1, 'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.directory.iterdir() if p.is_file() and p.name != 'manifest.json'}}
        (self.directory/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
