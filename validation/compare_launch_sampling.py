"""Measure finer-grid threats inside the apparent minute-grid ISS windows."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from windows import find_windows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minute',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--production',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    minute,reference,production=[json.loads(path.read_text()) for path in (args.minute,args.reference,args.production)]
    if any(report['status']!='complete' for report in [minute,reference,production]):
        raise ValueError('All reports must be complete.')
    if len({report['snapshot_sha256'] for report in [minute,reference,production]})!=1:
        raise ValueError('Snapshot mismatch.')
    by_time={entry['launch_time']:entry['obstructed'] for entry in minute['launches']}
    first=min(minute['launches'],key=lambda entry:entry['offset_s'])
    t0=datetime.fromisoformat(first['launch_time'])-timedelta(seconds=first['offset_s'])
    end=max(datetime.fromisoformat(entry['launch_time']) for entry in minute['launches'])
    minute_windows=find_windows(lambda launch:by_time[launch.isoformat()],t0,end,workers=1,launch_step_seconds=60)
    fine=[entry for entry in reference['launches'] if entry['offset_s']%60]
    inside=[]
    per_window=[]
    for window in minute_windows:
        start_dt,end_dt=datetime.fromisoformat(window['start']),datetime.fromisoformat(window['end'])
        samples=[entry for entry in fine if start_dt<=datetime.fromisoformat(entry['launch_time'])<end_dt]
        inside.extend(samples)
        per_window.append({'window':window,'extra_fine_samples':len(samples),
                           'unsafe_extra_fine_samples':sum(entry['obstructed'] for entry in samples)})
    unique_inside={entry['launch_time']:entry for entry in inside}
    unsafe=sum(entry['obstructed'] for entry in unique_inside.values())
    report={'status':'complete','snapshot_sha256':minute['snapshot_sha256'],
            'minute_reference_launches':len(minute['launches']),
            'minute_unsafe_launches':minute['obstructed_launches'],
            'minute_grid_windows':minute_windows,'per_window':per_window,
            'extra_fine_launches':len(fine),'unsafe_extra_fine_launches':sum(entry['obstructed'] for entry in fine),
            'fine_samples_inside_minute_windows':len(unique_inside),
            'unsafe_fine_samples_inside_minute_windows':unsafe,
            'observed_unsafe_percentage_inside_minute_windows':100*unsafe/len(unique_inside) if unique_inside else None,
            'final_production_windows':production['returned_windows'],
            'scope':'Exact sampled instants in the frozen model. Unsafe fine samples are missed threats of minute-only launch sampling; this is not the final scanner false-safe rate.'}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
