import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
from skyfield.api import load, EarthSatellite

load_dotenv()

log = logging.getLogger("opas")

client = MongoClient(os.getenv("MONGO_URI"))
collection = client["opas_db"]["debris"]
ts = load.timescale()

try:
    debris_count = collection.estimated_document_count()
    log.info("MongoDB connected — debris collection: ~%d documents", debris_count)
except Exception as e:
    log.warning("MongoDB connection check failed: %s", e)

_sat_cache = {}


def get_sat(doc):
    norad = doc.get("norad_id")
    tle1 = doc.get("tle_line1")
    tle2 = doc.get("tle_line2")
    if not tle1 or not tle2:
        return None
    cached = _sat_cache.get(norad)
    if cached and cached[0] == tle1:
        return cached[1]
    try:
        sat = EarthSatellite(tle1, tle2, doc.get("name", ""), ts)
        _sat_cache[norad] = (tle1, sat)
        return sat
    except Exception:
        return None


def make_skyfield_time(iso_str):
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return ts.from_datetime(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
