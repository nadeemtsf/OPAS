import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import baseline          # must come first (sets the offline Mongo env)
import scanner
import scanner_param
import scanner_fixed

docs, meta = baseline.load_snapshot()
t0 = datetime.fromisoformat(meta["exported_at_utc"])
baseline.freeze_tle_age(t0)

tle = next(d["tle_line1"] for d in docs if d.get("tle_line1"))
print(f"scanner (frozen, reference): {scanner.tle_epoch_age_days(tle):8.3f} days")
print(f"scanner_param:               {scanner_param.tle_epoch_age_days(tle):8.3f} days")
print(f"scanner_fixed:               {scanner_fixed.tle_epoch_age_days(tle):8.3f} days")