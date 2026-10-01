"""
Prints every specific number the LaTeX Results section cites, read directly
from the actual result files, so you can eyeball-diff against the draft
before it's considered final.

Run from the repo root:
    python research/verify_report_numbers.py
"""
import json
from pathlib import Path

RESULTS = Path("research/results")


def show(label, path, extract):
    p = RESULTS / path
    if not p.exists():
        print(f"[MISSING] {label}: {path} not found -- can't verify")
        return
    d = json.loads(p.read_text())
    print(f"[{label}] {path}")
    extract(d)
    print()


print("=" * 60)
print("TABLE 1 -- Baseline false-safe rates (F5)")
print("=" * 60)

show("ISS baseline", "compare_iss_20260922T070022Z.json", lambda d: [
    print(f"  {w['window']['duration_minutes']} min | "
          f"samples={w['clipped_to_requested_range']['reference_samples']} | "
          f"unsafe={w['clipped_to_requested_range']['marked_unsafe']} | "
          f"rate={w['clipped_to_requested_range']['false_safe_rate']:.0%}")
    for w in d["windows"]
])

show("Starlink baseline", "compare_starlink_20260922T071627Z.json", lambda d: [
    print(f"  {w['window']['duration_minutes']} min | "
          f"samples={w['clipped_to_requested_range']['reference_samples']} | "
          f"unsafe={w['clipped_to_requested_range']['marked_unsafe']} | "
          f"rate={w['clipped_to_requested_range']['false_safe_rate']:.0%}")
    for w in d["windows"]
])

show("SSO baseline", "compare_sso_20260922T072131Z.json", lambda d: [
    print(f"  {w['window']['duration_minutes']} min | "
          f"samples={w['clipped_to_requested_range']['reference_samples']} | "
          f"unsafe={w['clipped_to_requested_range']['marked_unsafe']} | "
          f"rate={w['clipped_to_requested_range']['false_safe_rate']:.0%}")
    for w in d["windows"]
])

show("GEO baseline (check the CLIPPED row, not raw)", "compare_geo_20260922T073520Z.json", lambda d: [
    print(f"  raw={w['window']['duration_minutes']}min | "
          f"clipped_samples={w['clipped_to_requested_range']['reference_samples']} | "
          f"clipped_unsafe={w['clipped_to_requested_range']['marked_unsafe']} | "
          f"clipped_rate={w['clipped_to_requested_range']['false_safe_rate']:.0%}")
    for w in d["windows"]
])

print("=" * 60)
print("F3 -- mean objects within 50km radius (prose claim, not tabled)")
print("=" * 60)

for label, path in [("ISS", "reference_iss_20260921T102002Z.json"),
                    ("Starlink", "reference_starlink_20260922T071313Z.json"),
                    ("SSO", "reference_sso_20260922T072024Z.json")]:
    show(label, path, lambda d: print(
        f"  50km unsafe rate={d['summary']['by_radius_km']['50']['frac_launch_times_unsafe']:.0%} | "
        f"mean objects={d['summary']['by_radius_km']['50']['mean_objects_within_R_per_launch']:.1f}"
    ))

print("=" * 60)
print("Sweep result (prose: 'tightening to 24 reduced windows to zero')")
print("=" * 60)

# Post-fix sweep files (2026-09-28)
for label, path in [("ISS", "sweep_iss_20260928T192528Z.jsonl"),
                    ("Starlink", "sweep_starlink_20260928T190843Z.jsonl"),
                    ("SSO", "sweep_sso_20260928T185956Z.jsonl")]:
    p = RESULTS / path
    if not p.exists():
        print(f"[MISSING] {label}: {path}")
        continue
    print(f"[{label}] {path}")
    for line in p.read_text().splitlines():
        rec = json.loads(line)
        if rec["n_intervals"] == 24:
            print(f"  n_intervals=24, coarse={rec['coarse_min']}min: n_windows={rec['n_windows']}")
    print()

print("=" * 60)
print("TABLE 2 -- Fixed scanner (F9)")
print("=" * 60)

show("Fixed ISS validation", "compare_fixed_iss_20260928T185703Z.json", lambda d: [
    print(f"  {w['window']['duration_minutes']} min | "
          f"samples={w['raw']['reference_samples']} | "
          f"unsafe={w['raw']['marked_unsafe']} | "
          f"rate={w['raw']['false_safe_rate']:.1%}")
    for w in d["windows"]
])

show("Fixed Starlink validation", "compare_fixed_starlink_20260928T185705Z.json", lambda d: [
    print(f"  {w['window']['duration_minutes']} min | "
          f"samples={w['raw']['reference_samples']} | "
          f"unsafe={w['raw']['marked_unsafe']} | "
          f"rate={w['raw']['false_safe_rate']:.1%}")
    for w in d["windows"]
])

print("=" * 60)
print("F9 mechanism proof -- 5/5 sampling gap per preset (ISS + Starlink)")
print("=" * 60)

for label, path in [("ISS", "prove_sampling_gap_iss_20260928T185708Z.json"),
                    ("Starlink", "prove_sampling_gap_starlink_20260928T185711Z.json")]:
    p = RESULTS / path
    if p.exists():
        d = json.loads(p.read_text())
        print(f"[{label}] {path}")
        print(f"  checked={d['checked']} | confirmed_gap_miss={d['confirmed_gap_miss']} "
              f"({d['confirmed_gap_miss']/d['checked']:.0%})")
    else:
        print(f"[MISSING] {label}: {path}")

print()
print("=" * 60)
print("Done. Compare every number above against the LaTeX draft.")
print("=" * 60)