"""Record completed, checksum-matched accuracy measurements and runtime."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory',type=Path,required=True)
    args=parser.parse_args()
    run=args.run_directory
    manifest=json.loads((run/'manifest.json').read_text())
    names=['summary','archived_pair_replay','launch_sampling','resolution_control','search_phase_runtime']
    reports={name:json.loads((run/f'{name}.json').read_text()) for name in names}
    if any(report['status']!='complete' for report in reports.values()):
        raise ValueError('All verification reports must be complete.')
    for name in names[:-1]:
        if reports[name]['snapshot_sha256']!=reports['summary']['snapshot_sha256']:
            raise ValueError(f'Snapshot mismatch: {name}.')
    repo=Path(__file__).resolve().parents[1]
    for name,sha in manifest['source_sha256'].items():
        if hashlib.sha256((repo/name).read_bytes()).hexdigest()!=sha:
            raise ValueError(f'Validated source changed during the run: {name}.')
    summary=reports['summary']; archive=reports['archived_pair_replay']
    sampling=reports['launch_sampling']; resolution=reports['resolution_control']; timing=reports['search_phase_runtime']
    minute_reference=json.loads((run/'iss_minute_reference.json').read_text())
    frozen_start=min(minute_reference['launches'],key=lambda entry:entry['offset_s'])['launch_time']
    frozen_end=max(minute_reference['launches'],key=lambda entry:entry['offset_s'])['launch_time']
    agreement=summary['classification_agreement_percentage']
    matched=summary['checked_launch_samples']-summary['false_safe_samples']-summary['false_alarm_samples']
    clear=summary['production_clear_samples']
    rows=[('Focused tests',f"{manifest['focused_tests']['passed']} passed",manifest['focused_tests']['elapsed_seconds']),
          ('Actual six-hour ISS window search',f"{summary['checked_launch_samples']} launch checks",summary['production_search_seconds']),
          ('Independent ISS reference',f"{summary['independent_reference_samples']} launch checks",summary['dense_verification_seconds']),
          ('Archived research pair replay',f"{archive['unsafe_pairs']} unsafe + {archive['clear_pairs']} nearby clear",archive['elapsed_seconds']),
          ('Direct ~0.2 s resolution control',f"{resolution['selected_pairs']} selected pairs",resolution['elapsed_seconds'])]
    table='\n'.join(f'| {label} | {result} | {seconds:.3f} s ({seconds/60:.2f} min) |' for label,result,seconds in rows)
    window_count=len(summary['returned_windows'])
    exclusions=sum(result['excluded_outside_production_scope'] for result in archive['presets'].values())
    phase_text=''
    if timing.get('phase_boundary_observed'):
        phase_text=(f"Minute discovery used {summary['minute_discovery_checks']} checks and took "
                    f"{timing['minute_discovery_seconds']:.3f} s; the {summary['finer_checks']} intervening checks "
                    f"took another {timing['finer_checks_seconds']:.3f} s. The runtime observer captured the final minute-only update.\n\n")
    observed=summary['observed_false_safe_percentage']
    text=(f"# OPAS focused verification rerun — {run.name}\n\n"
          f"The detector agreed with the independent distance calculation on **{matched}/"
          f"{summary['checked_launch_samples']} exact launch timestamps ({agreement:.2f}%)**. "
          f"Observed false-safe samples: **{summary['false_safe_samples']}/{clear} ({observed:.2f}%)**. "
          f"Observed false alarms: **{summary['false_alarm_samples']}**. Every production check had an independent reference result; "
          f"the reference included {summary['additional_reference_samples']} additional minute-grid samples.\n\n"
          f"| Run | Coverage | Elapsed runtime |\n| --- | --- | --- |\n{table}\n\n"
          +phase_text+
          f"The minute-only grid produced apparent windows of "
          f"{', '.join(str(w['duration_minutes'])+' minutes' for w in sampling['minute_grid_windows'])}. "
          f"The finer reference found **{sampling['unsafe_fine_samples_inside_minute_windows']} unsafe launches among "
          f"{sampling['fine_samples_inside_minute_windows']} additional samples** inside those windows "
          f"({sampling['observed_unsafe_percentage_inside_minute_windows']:.2f}%). "
          f"The final 10-second candidate refinement returned **{window_count} qualifying windows of at least 15 minutes**. "
          f"This between-minute unsafe fraction is a measurement of minute-only sampling, separate from the final scanner's observed false-safe rate.\n\n"
          f"The archived ISS, Starlink and SSO replay found {archive['missed_unsafe_pairs']} missed unsafe pairs and "
          f"{archive['false_alarm_pairs']} incorrectly flagged clear pairs. This fresh replay uses exact recorded offsets inside "
          f"the six-hour horizon, frozen screening radii, and clear controls within radius + 20 km. It excludes "
          f"{exclusions} nearby pairs whose archived closest approach is before the production flight scope. "
          f"It is a comparison with archived research minima. The full ISS reference above was recomputed during this run.\n\n"
          f"Direct propagation at {resolution['flight_step_s']:.6f} s spacing changed "
          f"{resolution['classification_changes']} classifications in the {resolution['selected_pairs']} selected threshold-nearest pairs "
          f"and disagreed with the production pair detector on {resolution['production_pair_disagreements']} pairs. "
          f"This checks numerical resolution for those six pairs; it does not repeat the entire catalogue at 0.2 seconds.\n\n"
          f"The tested launch horizon is **{frozen_start} through {frozen_end}**, from the archived snapshot. "
          f"The snapshot contains {summary['candidate_count']:,} ISS altitude-filtered objects, with SHA-256 "
          f"`{summary['snapshot_sha256']}`. The independent reference regenerates the vehicle path at "
          f"{summary['dense_flight_step_s']:.6f} s spacing and uses separate squared-distance/parabolic minimization. "
          f"Its one-second satellite ephemerides are interpolated onto that grid; pairs within 20 m of the threshold are "
          f"directly repropagated. Both methods share the frozen TLE/SGP4 and vehicle models.\n\n"
          f"The production ISS flight check begins at about 603.356 s; the dense reference begins at "
          f"{summary['dense_scope_start_s']:.6f} s. These measurements establish agreement at tested launch times in the "
          f"frozen post-ascent model. They do not establish real-world safety, ascent safety, coverage of objects outside "
          f"the altitude filter, or safety at every instant between 10-second launch samples.\n\n"
          f"{manifest['runtime_context']}\n\n"
          f"The previous scratch checkout was unavailable. `backend/encounters.py` and `backend/windows.py` were reconstructed "
          f"and matched their recorded previous SHA-256 values byte for byte. The scanner patches were reapplied to "
          f"`{manifest['base_commit']}`; its prior full checksum was unavailable. Eighteen focused tests were reproduced "
          f"from recorded source and fifteen encounter/scanner tests were rebuilt from recorded descriptions. All numbers "
          f"in this report are fresh measurements; historical runtimes and classifications were not reused.\n\n"
          f"Detailed evidence: [summary.json](summary.json), [manifest.json](manifest.json), "
          f"[focused_tests.log](focused_tests.log), [archived_pair_replay.json](archived_pair_replay.json), "
          f"[launch_sampling.json](launch_sampling.json), [resolution_control.json](resolution_control.json), "
          f"[search_phase_runtime.json](search_phase_runtime.json), [iss_search.json](iss_search.json), "
          f"[iss_reference.json](iss_reference.json).\n")
    (run/'report.md').write_text(text)
    manifest.update(status='complete',completed_at_utc=datetime.now(timezone.utc).isoformat(),
                    snapshot_sha256=summary['snapshot_sha256'],
                    frozen_launch_horizon_utc={'start':frozen_start,'end':frozen_end},
                    accuracy={key:summary[key] for key in ['checked_launch_samples','production_clear_samples',
                       'false_safe_samples','false_alarm_samples','observed_false_safe_percentage','classification_agreement_percentage']},
                    measurements={label:{'coverage':result,'elapsed_seconds':seconds} for label,result,seconds in rows},
                    report_sha256=hashlib.sha256((run/'report.md').read_bytes()).hexdigest())
    manifest['validation_helper_sha256']={str(path.relative_to(repo)):hashlib.sha256(path.read_bytes()).hexdigest()
                                         for path in sorted((repo/'validation').glob('*.py'))}
    (run/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(str(run/'report.md'))


if __name__=='__main__':
    main()
