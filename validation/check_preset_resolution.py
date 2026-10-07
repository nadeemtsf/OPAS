"""Direct ~0.2s flight-spacing controls for threshold-nearest reference pairs."""
import argparse,gzip,hashlib,json,math
from datetime import datetime
from pathlib import Path
import time
import numpy as np
from reference_presets import direct,minimum_distances,scanner,PRESETS
from orbital import EARTH_R,generate_trajectory
from proximity import geodetic_to_ecef


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--research-root',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();started=time.perf_counter()
 reference=json.loads(a.reference.read_text())
 if reference['status']!='complete':raise ValueError('Reference incomplete.')
 meta=json.loads((a.research_root/'data/snapshot_meta.json').read_text());raw=gzip.decompress((a.research_root/'data'/meta['file']).read_bytes())
 if hashlib.sha256(raw).hexdigest()!=reference['snapshot_sha256']:raise ValueError('Snapshot mismatch.')
 docs={d['norad_id']:d for line in raw.splitlines() if (d:=json.loads(line))}
 lat,lon,alt,inc=PRESETS[reference['preset']];period=2*math.pi*math.sqrt((EARTH_R+alt)**3/398600.4418);steps=round(period/.2)
 trajectory=generate_trajectory(lat,lon,alt,inc,steps=steps);scope_start=reference['flight_start_seconds'];first=math.floor(scope_start/(period/steps))+1
 flight=np.r_[scope_start,np.arange(first,steps+1)*period/steps]
 production=generate_trajectory(lat,lon,alt,inc);wp=production[round(600/(period/600))]
 vehicle=np.array([geodetic_to_ecef(wp['lat'],wp['lon'],wp['alt'])]+[geodetic_to_ecef(w['lat'],w['lon'],w['alt']) for w in trajectory[first:]])
 selected=[]
 for obstructed in [False,True]:selected+=sorted([e for e in reference['launches'] if e['obstructed']==obstructed and 'clearance_margin_km' in e],key=lambda e:abs(e['clearance_margin_km']))[:3]
 cases=[]
 for e in selected:
  doc=docs[e['closest_norad_id']];sat=scanner.get_sat(doc);t=scanner.ts.from_datetime(datetime.fromisoformat(e['launch_time']))
  xyz=direct(sat,scanner.ts.tt_jd(float(t.tt)+flight/86400));distance=float(minimum_distances(xyz[None,:,:],vehicle)[0]);radius=e['screening_radius_km']
  pair=scanner.count_threats_fast([(sat,doc,radius)],production,alt,t,10,strict=True)>0
  cases.append(dict(offset_s=e['offset_s'],norad_id=doc['norad_id'],radius_km=radius,reference_distance_km=e['minimum_distance_km'],fine_distance_km=distance,distance_change_m=(distance-e['minimum_distance_km'])*1000,reference_obstructed=e['obstructed'],fine_obstructed=distance<radius,production_pair_obstructed=pair))
 result={'status':'complete','preset':reference['preset'],'scope':'Selected near-threshold pairs only; not a full-catalogue 0.2s reference.','flight_step_seconds':period/steps,'cases':cases,'classification_changes':sum(e['reference_obstructed']!=e['fine_obstructed'] for e in cases),'production_pair_disagreements':sum(e['fine_obstructed']!=e['production_pair_obstructed'] for e in cases),'elapsed_seconds':time.perf_counter()-started,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'snapshot_sha256':reference['snapshot_sha256']}
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
 return 0 if result['classification_changes']==result['production_pair_disagreements']==0 else 1
if __name__=='__main__':raise SystemExit(main())
