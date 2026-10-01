import re
from pathlib import Path

WRAPPER = '''

def tle_epoch_age_days(tle_line1):
    # resolved at call time so baseline.freeze_tle_age(t0) takes effect
    return scanner.tle_epoch_age_days(tle_line1)
'''

OLD = "from orbital import EARTH_R, tle_epoch_age_days, generate_trajectory"
NEW = "import scanner\nfrom orbital import EARTH_R, generate_trajectory"

for name in ("scanner_param.py", "scanner_fixed.py"):
    p = Path("research") / name
    src = p.read_text(encoding="utf-8")
    if "return scanner.tle_epoch_age_days" in src:
        print(f"{name}: already patched")
        continue
    assert OLD in src, f"{name}: expected import line not found"
    src = src.replace(OLD, NEW)
    m = re.search(r"^from proximity import .*$", src, flags=re.M)
    assert m, f"{name}: proximity import line not found"
    src = src[:m.end()] + "\n" + WRAPPER + src[m.end():]
    p.write_text(src, encoding="utf-8")
    print(f"{name}: patched")