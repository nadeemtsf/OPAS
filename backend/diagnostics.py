"""Request-correlated runtime evidence, with bounded progress logging."""
import logging
import time

log = logging.getLogger('opas')


class SearchDiagnostics:
    def __init__(self, request_id, publish=None):
        self.started = time.perf_counter()
        self.publish = publish
        self.data = {'request_id': request_id, 'status': 'running'}
        self.last_phase = None
        self.last_log = 0

    def update(self, event):
        self.data.update(event)
        self.data['elapsed_seconds'] = round(time.perf_counter()-self.started, 3)
        phase = self.data.get('phase', 'starting')
        now = time.perf_counter()
        if phase != self.last_phase or now-self.last_log >= 5 or phase == 'complete':
            log.info('request=%s | safe-windows phase=%s elapsed=%.3fs '
                     'checks=%d clear=%d obstructed=%d batch=%s/%s candidates=%s '
                     'qualifying=%s returned=%s extra_validation=%s new_obstructions=%s '
                     'mean_check=%.3fs compute_sum=%.3fs',
                     self.data['request_id'], phase, self.data['elapsed_seconds'],
                     self.data.get('checked_launch_samples', 0), self.data.get('clear_launch_samples', 0),
                     self.data.get('obstructed_launch_samples', 0), self.data.get('phase_completed', 0),
                     self.data.get('phase_total', 0), self.data.get('candidate_spans', 0),
                     self.data.get('qualifying_spans', 0), self.data.get('returned_windows', 0),
                     self.data.get('extra_validation_checks', 0), self.data.get('validation_obstructed_samples', 0),
                     self.data.get('detector_mean_seconds', 0), self.data.get('detector_compute_seconds', 0))
            self.last_log = now
        self.last_phase = phase
        if self.publish:
            self.publish({'event': 'progress', 'data': dict(self.data)})
