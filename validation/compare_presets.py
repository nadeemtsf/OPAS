"""Reject incomplete/mismatched evidence and compare full-horizon preset results."""
import argparse,json
from pathlib import Path


def clear_windows(launches, minimum=900):
    result=[];begin=None;last=None
    for entry in sorted(launches,key=lambda x:x['offset_s']):
        if entry['obstructed']:
            if begin is not None and last['offset_s']-begin['offset_s']>=minimum:
                result.append({'start':begin['launch_time'],'end':last['launch_time'],
                               'duration_seconds':last['offset_s']-begin['offset_s']})
            begin=last=None
        else:
            if begin is None:begin=entry
            last=entry
    if begin is not None and last['offset_s']-begin['offset_s']>=minimum:
        result.append({'start':begin['launch_time'],'end':last['launch_time'],
                       'duration_seconds':last['offset_s']-begin['offset_s']})
    return sorted(result,key=lambda w:(-w['duration_seconds'],w['start']))


def compare(root):
    summary={'status':'complete','scope':'Frozen research catalogue, six-hour horizons, exact 5s reference launch grid; sampled nominal post-ascent clearance only.','presets':{}}
    for preset in ['iss','starlink','sso']:
        baseline=json.loads((root/f'baseline_{preset}.json').read_text())
        optimized=json.loads((root/f'optimized_{preset}.json').read_text())
        reference=json.loads((root/f'reference_{preset}.json').read_text())
        for report in [baseline,optimized,reference]:
            if report['status']!='complete' or report['preset']!=preset or report['snapshot_sha256']!=baseline['snapshot_sha256'] or report['t0']!=baseline['t0'] or report['parameters']!=baseline['parameters']:
                raise ValueError('Incomplete or mismatched inputs.')
            offsets=[entry['offset_s'] for entry in report['launches']]
            if len(offsets)!=len(set(offsets)):raise ValueError('Duplicate launch offsets.')
        if [e['offset_s'] for e in reference['launches']]!=list(range(0,21601,5)):
            raise ValueError('Reference does not cover the full six-hour 5s launch grid.')
        old={e['offset_s']:e['obstructed'] for e in baseline['launches']}
        new={e['offset_s']:e['obstructed'] for e in optimized['launches']}
        truth={e['offset_s']:e['obstructed'] for e in reference['launches']}
        if not set(old).issubset(new) or not set(new).issubset(truth):raise ValueError('Missing comparison coverage.')
        changes=[s for s in old if old[s]!=new[s]]
        false_safes=[s for s in new if not new[s] and truth[s]]
        false_obstructions=[s for s in new if new[s] and not truth[s]]
        before_disagreements=[s for s in old if old[s]!=truth[s]]
        ref_windows=clear_windows(reference['launches'])
        ref_pairs=[(w['start'],w['end']) for w in ref_windows[:5]]
        new_pairs=[(w['start'],w['end']) for w in optimized['returned_windows']]
        control=json.loads((root/f'control_{preset}.json').read_text())
        if (control['status']!='complete' or control['prefilter_stride']!=1 or
            any(control[key]!=reference[key] for key in
                ['preset','snapshot_sha256','t0','parameters','candidate_count'])):
            raise ValueError('Incomplete or mismatched unfiltered control.')
        control_offsets=[e['offset_s'] for e in control['launches']]
        if len(control_offsets)!=len(set(control_offsets)) or not set(control_offsets).issubset(truth):
            raise ValueError('Invalid control coverage.')
        control_changes=[e['offset_s'] for e in control['launches'] if e['obstructed']!=truth[e['offset_s']]]
        resolution=json.loads((root/f'resolution_{preset}.json').read_text())
        if (resolution['status']!='complete' or resolution['preset']!=preset or
            resolution['snapshot_sha256']!=reference['snapshot_sha256'] or
            len(resolution['cases'])!=6):
            raise ValueError('Incomplete or mismatched resolution controls.')
        all_spans=clear_windows(reference['launches'], minimum=0)
        summary['presets'][preset]={'candidate_count':baseline['candidate_count'],
            'baseline_seconds':baseline['elapsed_seconds'],'optimized_seconds':optimized['elapsed_seconds'],
            'speedup':baseline['elapsed_seconds']/optimized['elapsed_seconds'],
            'baseline_checks':len(old),'optimized_checks':len(new),'baseline_to_optimized_changes':changes,
            'reference_checks':len(truth),'reference_seconds':reference['elapsed_seconds'],
            'production_clear':optimized['clear'],'production_obstructed':optimized['obstructed'],
            'reference_clear':reference['clear'],'reference_obstructed':reference['obstructed'],
            'baseline_reference_disagreements':before_disagreements,
            'false_safe_offsets_s':false_safes,'false_obstruction_offsets_s':false_obstructions,
            'observed_false_safe_percent':100*len(false_safes)/optimized['clear'] if optimized['clear'] else None,
            'returned_windows':optimized['returned_windows'],'reference_qualifying_spans':ref_windows,
            'longest_reference_clear_span_seconds':all_spans[0]['duration_seconds'] if all_spans else 0,
            'top_five_window_endpoints_equal':new_pairs==ref_pairs,
            'unfiltered_control_checks':len(control['launches']),'unfiltered_control_disagreements':control_changes,
            'resolution_pairs':len(resolution['cases']),
            'resolution_classification_changes':resolution['classification_changes'],
            'resolution_production_pair_disagreements':resolution['production_pair_disagreements']}
    summary['successful']=all(not d['baseline_to_optimized_changes'] and not d['baseline_reference_disagreements'] and not d['false_safe_offsets_s'] and not d['false_obstruction_offsets_s'] and d['top_five_window_endpoints_equal'] and not d['unfiltered_control_disagreements'] and not d['resolution_classification_changes'] and not d['resolution_production_pair_disagreements'] for d in summary['presets'].values())
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--results',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    result=compare(a.results);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    return 0 if result['successful'] else 1
if __name__=='__main__':raise SystemExit(main())
