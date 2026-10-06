"""Refresh named existing objects without deleting or replacing the catalogue.

Example, from backend: python refresh_catalogue.py --norad-id 69980
Space-Track and MongoDB credentials are read from the existing .env file.
Invalid, unavailable or officially decayed objects are retained for investigation;
they are never silently removed from screening.
"""
import argparse
from datetime import datetime, timedelta, timezone
import math
import os

import numpy as np
from pymongo import MongoClient
from skyfield.api import EarthSatellite, load

from ingest import authenticate
from prediction import satellite_positions


def fetch_latest(session, norad_id):
    url = ("https://www.space-track.org/basicspacedata/query/class/gp/"
           f"NORAD_CAT_ID/{norad_id}/orderby/EPOCH%20desc/limit/1/format/json")
    response = session.get(url, timeout=60)
    response.raise_for_status()
    records = response.json()
    if not isinstance(records, list) or not records:
        raise ValueError('Space-Track returned no current record; the existing object was retained.')
    record = records[0]
    if int(record['NORAD_CAT_ID']) != norad_id:
        raise ValueError('Space-Track returned a different object; no update was made.')
    if record.get('DECAY_DATE'):
        raise ValueError('Space-Track reports a decay date. Confirm its catalogue status separately; '
                         'the existing object was retained, not silently excluded.')
    return record


def validated_document(record, timescale, start, validation_hours=8):
    """Check one-minute predictions through the requested horizon before writing.

    This checks data usability, not collision safety or every intervening time.
    Eight hours covers a six-hour launch search plus a two-hour LEO flight.
    """
    if not math.isfinite(validation_hours) or validation_hours <= 0:
        raise ValueError('Validation hours must be finite and positive.')
    norad = int(record['NORAD_CAT_ID'])
    line1, line2 = record['TLE_LINE1'], record['TLE_LINE2']
    if int(line1[2:7]) != norad or int(line2[2:7]) != norad:
        raise ValueError('The TLE lines do not match the requested NORAD ID.')
    sat = EarthSatellite(line1, line2, record.get('OBJECT_NAME', ''), timescale)
    seconds = np.unique(np.append(np.arange(0, validation_hours*3600, 60), validation_hours*3600))
    samples = timescale.from_datetimes([start+timedelta(seconds=float(offset)) for offset in seconds])
    satellite_positions(sat, samples)
    now = timescale.from_datetime(start)
    subpoint = sat.at(now).subpoint()
    lat, lon, alt = subpoint.latitude.degrees, subpoint.longitude.degrees, subpoint.elevation.km
    if not all(math.isfinite(float(value)) for value in (lat, lon, alt)):
        raise ValueError('The refreshed object has an invalid stored position.')
    return {'name': record.get('OBJECT_NAME', ''), 'norad_id': norad,
            'altitude_km': round(float(alt), 2), 'tle_line1': line1, 'tle_line2': line2,
            'location': {'type': 'Point', 'coordinates': [round(float(lon), 4), round(float(lat), 4)]}}


def refresh_object(collection, session, timescale, norad_id, start, validation_hours=8, dry_run=False):
    current = collection.find_one({'norad_id': norad_id})
    if current is None:
        raise ValueError('This NORAD ID is absent from the catalogue; no object was added.')
    record = fetch_latest(session, norad_id)
    document = validated_document(record, timescale, start, validation_hours)
    if current.get('tle_line1') and current.get('tle_line2'):
        previous = EarthSatellite(current['tle_line1'], current['tle_line2'], '', timescale)
        refreshed = EarthSatellite(document['tle_line1'], document['tle_line2'], '', timescale)
        if refreshed.epoch.tt < previous.epoch.tt:
            raise ValueError('Space-Track returned an older TLE; the existing object was retained.')
    if dry_run:
        return 'validated; dry run, no database change'
    # Guard against a concurrent catalogue refresh; update only this document.
    result = collection.update_one({'_id': current['_id'],
                                    'tle_line1': current.get('tle_line1'),
                                    'tle_line2': current.get('tle_line2')}, {'$set': document}, upsert=False)
    if result.matched_count != 1:
        raise ValueError('The object changed during refresh; retry. No replacement was forced.')
    return 'updated' if result.modified_count else 'already current and validated'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--norad-id', type=int, action='append', required=True,
                        help='Existing object to refresh; repeat for multiple IDs.')
    parser.add_argument('--validation-hours', type=float, default=8,
                        help='Prediction usability horizon, default 8h; increase for longer flights.')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if any(norad <= 0 or norad > 99999 for norad in args.norad_id):
        parser.error('NORAD IDs must fit the five-digit TLE fields (1..99999).')
    if not math.isfinite(args.validation_hours) or not 0 < args.validation_hours <= 168:
        parser.error('--validation-hours must be greater than zero and at most 168.')
    missing = [key for key in ('MONGO_URI', 'SPACE_TRACK_USER', 'SPACE_TRACK_PASS') if not os.getenv(key)]
    if missing:
        parser.error('Configure ' + ', '.join(missing) + ' in backend/.env first.')
    client = MongoClient(os.environ['MONGO_URI'], serverSelectionTimeoutMS=10000)
    failures = 0
    try:
        with authenticate() as session:
            timescale = load.timescale()
            start = datetime.now(timezone.utc)
            for norad in dict.fromkeys(args.norad_id):
                try:
                    status = refresh_object(client['opas_db']['debris'], session, timescale, norad,
                                            start, args.validation_hours, args.dry_run)
                    print(f'{norad}: {status} ({args.validation_hours:g}h of one-minute prediction checks)')
                except Exception as error:
                    failures += 1
                    print(f'{norad}: FAILED — {error}')
    finally:
        client.close()
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
