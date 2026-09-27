"""
Freeze the OPAS debris catalog into a single reproducible file.

Why: the live MongoDB collection changes every time you run backend/ingest.py,
and OPAS computes TLE age relative to "now". For research we need every
experiment to run on exactly the same data. This script exports the collection
once and records when (T0), how many objects, and a checksum.

Run from the repo root (needs backend/.env with MONGO_URI):

    python research/export_snapshot.py

Outputs (in research/data/, which should NOT be committed - see README note):
    debris_snapshot_<UTC timestamp>.jsonl.gz   one JSON document per line
    snapshot_meta.json                         T0, counts, checksum
"""
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"


def tle_epoch(tle_line1):
    """Parse the epoch out of TLE line 1 (same convention as backend/orbital.py)."""
    try:
        yr2 = int(tle_line1[18:20])
        day_frac = float(tle_line1[20:32])
        year = yr2 + (1900 if yr2 >= 57 else 2000)
        return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_frac - 1)
    except Exception:
        return None


def build_snapshot(docs, exported_at, out_dir=DATA_DIR):
    """Write docs to a gzipped JSONL file plus a metadata file. Returns the metadata dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = sorted(docs, key=lambda d: d.get("norad_id", 0))

    stamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
    fname = f"debris_snapshot_{stamp}.jsonl.gz"

    hasher = hashlib.sha256()
    epochs = []
    with_tle = 0
    alts = []
    with gzip.open(out_dir / fname, "wb") as f:
        for d in docs:
            line = (json.dumps(d, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            hasher.update(line)  # hash the uncompressed bytes so the checksum is stable
            f.write(line)
            if d.get("tle_line1") and d.get("tle_line2"):
                with_tle += 1
                ep = tle_epoch(d["tle_line1"])
                if ep is not None:
                    epochs.append(ep)
            if isinstance(d.get("altitude_km"), (int, float)):
                alts.append(d["altitude_km"])

    meta = {
        "file": fname,
        "exported_at_utc": exported_at.isoformat(),
        "n_objects": len(docs),
        "n_with_tle": with_tle,
        "altitude_km_min": min(alts) if alts else None,
        "altitude_km_max": max(alts) if alts else None,
        # The newest TLE epoch is a lower bound on when the catalog was ingested.
        # (ingest.py stores no timestamp, and altitude_km/location are from ingest time.)
        "newest_tle_epoch_utc": max(epochs).isoformat() if epochs else None,
        "oldest_tle_epoch_utc": min(epochs).isoformat() if epochs else None,
        "sha256_uncompressed": hasher.hexdigest(),
    }
    (out_dir / "snapshot_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main():
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv(REPO / "backend" / ".env")
    uri = os.getenv("MONGO_URI")
    if not uri:
        sys.exit("MONGO_URI not found. Create backend/.env first (see README).")

    collection = MongoClient(uri)["opas_db"]["debris"]
    exported_at = datetime.now(timezone.utc)
    print("Reading opas_db.debris ...")
    docs = list(collection.find({}, {"_id": 0}))
    if not docs:
        sys.exit("Collection is empty. Run backend/ingest.py first.")

    meta = build_snapshot(docs, exported_at)
    print(f"Exported {meta['n_objects']} objects ({meta['n_with_tle']} with TLEs)")
    print(f"T0 (export time): {meta['exported_at_utc']}")
    print(f"TLE epochs: {meta['oldest_tle_epoch_utc']}  ->  {meta['newest_tle_epoch_utc']}")
    print(f"sha256: {meta['sha256_uncompressed']}")
    print(f"Wrote {DATA_DIR / meta['file']}")


if __name__ == "__main__":
    main()
