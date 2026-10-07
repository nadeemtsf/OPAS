"""Sequential fixed-input search/profiling; accepts a separate baseline checkout."""
import argparse,cProfile,gzip,hashlib,json,os,platform,pstats,sys,time
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch

PRESETS={'iss':(28.573,-80.649,420,51.6),'starlink':(28.573,-80.649,550,53.),'sso':(34.632,-120.611,705,98.2)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend-root',type=Path,default=Path(__file__).resolve().parents[1]/'backend')
    p.add_argument('--research-root',type=Path,required=True)
    p.add_argument('--preset',choices=PRESETS,default='iss')
    p.add_argument('--mode',choices=['profile','search','workers'],required=True)
    p.add_argument('--capture',action='store_true',help='save an exact replay bundle (current backend only)')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--hours',type=float,default=6)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    os.environ['MONGO_URI']='mongodb://localhost:1/?serverSelectionTimeoutMS=1'
    sys.path.insert(0,str(a.backend_root.resolve()))
    import scanner
    from orbital import generate_trajectory
    from proximity import screening_radius_km
    from windows import find_windows
    meta=json.loads((a.research_root/'data/snapshot_meta.json').read_text())
    raw=gzip.decompress((a.research_root/'data'/meta['file']).read_bytes())
    assert hashlib.sha256(raw).hexdigest()==meta['sha256_uncompressed']
    lat,lon,alt,inc=PRESETS[a.preset]
    docs=[json.loads(l) for l in raw.splitlines()]
    docs=[d for d in docs if alt-100<=d['altitude_km']<=alt+100]
    t0=datetime.fromisoformat(meta['exported_at_utc'])
    def age(line):
        yr=int(line[18:20]);epoch=datetime(yr+(1900 if yr>=57 else 2000),1,1,tzinfo=t0.tzinfo)+timedelta(days=float(line[20:32])-1)
        return (t0-epoch).total_seconds()/86400
    scanner.tle_epoch_age_days=age
    trajectory=generate_trajectory(lat,lon,alt,inc)
    sources=['scanner.py','encounters.py','prediction.py','windows.py','orbital.py','batch_prediction.py','scan_plan.py']
    report={'status':'running','preset':a.preset,'parameters':dict(lat=lat,lon=lon,alt_km=alt,inclination=inc,hours=a.hours),'t0':t0.isoformat(),'snapshot_sha256':meta['sha256_uncompressed'],'candidate_count':len(docs),'workers':a.workers,'python':platform.python_version(),'platform':platform.platform(),'cpu_count':os.cpu_count(),'threads':{k:os.environ.get(k) for k in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS']},'source_sha256':{n:hashlib.sha256((a.backend_root/n).read_bytes()).hexdigest() for n in sources if (a.backend_root/n).exists()},'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'launches':[]}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    def save():a.output.write_text(json.dumps(report,indent=2)+'\n')
    save();start=time.perf_counter()
    if a.mode=='profile':
        items=[(scanner.get_sat(d),d,screening_radius_km(10,age(d['tle_line1']))) for d in docs]
        profiler=cProfile.Profile()
        for offset in [0,60,120]:
            before=time.perf_counter();profiler.enable()
            obstruction=scanner.count_threats_fast(items,trajectory,alt,scanner.ts.from_datetime(t0+timedelta(seconds=offset)),10,stop_after_first=True,strict=True)
            profiler.disable();report['launches'].append({'offset_s':offset,'obstructed':bool(obstruction),'seconds':time.perf_counter()-before})
        profiler.dump_stats(str(a.output.with_suffix('.pstats')))
        with a.output.with_suffix('.profile.txt').open('w') as f:pstats.Stats(profiler,stream=f).strip_dirs().sort_stats('cumulative').print_stats(45)
    elif a.mode=='workers':
        from concurrent.futures import ProcessPoolExecutor
        from multiprocessing import get_context
        documents=[(d,screening_radius_km(10,age(d['tle_line1'])),True) for d in docs]
        points=[t0+timedelta(seconds=i*60) for i in range(4)]
        with ProcessPoolExecutor(max_workers=a.workers,mp_context=get_context('spawn'),
                initializer=scanner._prepare_window_worker,
                initargs=(documents,trajectory,alt,10)) as executor:
            results=list(executor.map(timed_worker,points))
        report['launches']=[dict(offset_s=(point-t0).total_seconds(),obstructed=state,
                                compute_seconds=elapsed) for point,(state,elapsed) in zip(points,results)]
        report['worker_compute_seconds']=sum(elapsed for _,elapsed in results)
    else:
        capture=None
        if a.capture:
            from evidence import RunEvidence
            from uuid import uuid4
            os.environ['OPAS_CAPTURE_DIR']=str(a.output.parent/'captures')
            capture=RunEvidence(uuid4().hex[:12],dict(catalogue=docs,trajectory=trajectory,
                parameters=dict(target_lat=lat,target_lon=lon,target_alt=alt,inclination=inc,search_hours=a.hours),
                search_start_utc=t0.isoformat(),search_end_utc=(t0+timedelta(hours=a.hours)).isoformat(),
                proximity_km=10,launch_step_seconds=10,verification_step_seconds=5,
                catalogue_sha256=hashlib.sha256(json.dumps(docs,sort_keys=True).encode()).hexdigest()))
            report['capture_directory']=str(capture.directory.relative_to(a.output.parent))
        def measured(check,first,end,**kw):
            def record(points,states):
                for point,state in zip(points,states):
                    report['launches'].append({'offset_s':(point-t0).total_seconds(),'launch_time':point.isoformat(),'obstructed':bool(state)})
                    if len(report['launches'])%100==0:save();print(a.preset,len(report['launches']),round(time.perf_counter()-start,2),flush=True)
                    yield state
            batch=kw.get('check_many')
            if batch:kw['check_many']=lambda points:record(points,batch(points))
            def traced(point):return next(record([point],[check(point)]))
            return find_windows(traced,first,end,**kw)
        diag={}
        options=dict(workers=a.workers,verification_step_seconds=5,diagnostics=diag)
        if capture:options.update(record_check=capture.record,on_prepared=capture.prepared)
        with patch.object(scanner,'find_windows',side_effect=measured):
            report['returned_windows']=scanner.scan_windows(docs,trajectory,lat,lon,alt,t0,t0+timedelta(hours=a.hours),10,**options)
        if capture:capture.finish(dict(status='complete',windows=report['returned_windows'],diagnostics=diag))
        report['diagnostics']=diag
        report['launches'].sort(key=lambda x:x['offset_s'])
    report.update(status='complete',elapsed_seconds=time.perf_counter()-start,launch_count=len(report['launches']),clear=sum(not l['obstructed'] for l in report['launches']),obstructed=sum(l['obstructed'] for l in report['launches']))
    save();print(json.dumps({k:v for k,v in report.items() if k not in ['launches','source_sha256']}),flush=True)
def timed_worker(point):
    import scanner
    before=time.perf_counter()
    state=scanner._window_launch_obstructed(point)
    return state,time.perf_counter()-before

if __name__=='__main__':main()
