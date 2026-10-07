"""Run fixed-input scanner and reference workloads sequentially; retain checkpoints."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--research-root',type=Path,required=True)
    p.add_argument('--baseline-root',type=Path,required=True)
    p.add_argument('--results',type=Path,required=True)
    p.add_argument('--wait-for-baseline-iss',action='store_true',help='join an already running baseline ISS benchmark')
    a=p.parse_args();a.results.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    def run(name,script,options):
        command=[sys.executable,'validation/'+script,*map(str,options)]
        print('START',name,flush=True);started=time.perf_counter()
        with (a.results/(name+'.log')).open('w') as log:process=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
        print('DONE',name,process.returncode,round(time.perf_counter()-started,2),flush=True)
        if process.returncode:raise RuntimeError(f'{name} failed; inspect saved log')
    common=['--research-root',a.research_root]
    if a.wait_for_baseline_iss:
        print('Waiting for existing baseline ISS checkpoint',flush=True)
        while True:
            try:
                report=json.loads((a.results/'baseline_iss.json').read_text())
                if report['status']=='complete':break
            except (FileNotFoundError,json.JSONDecodeError):pass
            time.sleep(2)
        presets=['starlink','sso']
    else:presets=['iss','starlink','sso']
    for preset in presets:
        name='baseline_'+preset
        run(name,'benchmark_scanner.py',common+['--backend-root',a.baseline_root/'backend','--mode','search','--preset',preset,'--output',a.results/(name+'.json')])
    for kind in ['baseline','optimized']:
        extra=['--backend-root',a.baseline_root/'backend'] if kind=='baseline' else []
        run(kind+'_profile','benchmark_scanner.py',common+extra+['--mode','profile','--output',a.results/(kind+'_profile.json')])
        for workers in [1,4]:
            name=f'{kind}_workers_{workers}'
            run(name,'benchmark_scanner.py',common+extra+['--mode','workers','--workers',workers,'--output',a.results/(name+'.json')])
    for preset in ['iss','starlink','sso']:
        name='optimized_'+preset
        run(name,'benchmark_scanner.py',common+['--mode','search','--capture','--preset',preset,'--output',a.results/(name+'.json')])
    for preset in ['iss','starlink','sso']:
        name='reference_'+preset
        run(name,'reference_presets.py',common+['--preset',preset,'--output',a.results/(name+'.json')])
        reference=json.loads((a.results/(name+'.json')).read_text())
        offsets={0,1800,3600,7200,10800,14400,18000,21600}
        for obstructed in [False,True]:
            nearest=sorted([e for e in reference['launches'] if e['obstructed']==obstructed and 'clearance_margin_km' in e],key=lambda e:abs(e['clearance_margin_km']))[:3]
            offsets.update(e['offset_s'] for e in nearest)
        controls=a.results/(f'control_offsets_{preset}.json');controls.write_text(json.dumps({'offsets_s':sorted(offsets)},indent=2)+'\n')
        run('control_'+preset,'reference_presets.py',common+['--preset',preset,'--prefilter-stride',1,'--offsets-file',controls,'--output',a.results/(f'control_{preset}.json')])
        run('resolution_'+preset,'check_preset_resolution.py',common+['--reference',a.results/(name+'.json'),'--output',a.results/(f'resolution_{preset}.json')])
    run('archived_pair_replay','validate_encounters.py',common+['--output',a.results/'archived_pair_replay.json'])
    run('comparison','compare_presets.py',['--results',a.results,'--output',a.results/'comparison.json'])
    run('capture_integrity','check_capture_integrity.py',common+['--results',a.results,'--output',a.results/'capture_integrity.json'])
    print('SUITE COMPLETE',flush=True)
if __name__=='__main__':main()
