import os
import requests
from dotenv import load_dotenv
from skyfield.api import load, EarthSatellite
from pymongo import MongoClient

load_dotenv()

SPACE_TRACK_USER = os.getenv("SPACE_TRACK_USER")
SPACE_TRACK_PASS = os.getenv("SPACE_TRACK_PASS")
MONGO_URI = os.getenv("MONGO_URI")

LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
QUERY_URL = (
    "https://www.space-track.org/basicspacedata/query"
    "/class/gp"
    "/DECAY_DATE/null-val"
    "/EPOCH/>now-30"
    "/orderby/NORAD_CAT_ID"
    "/format/json"
)


def authenticate():
    session = requests.Session()
    resp = session.post(LOGIN_URL, data={
        "identity": SPACE_TRACK_USER,
        "password": SPACE_TRACK_PASS,
    })
    resp.raise_for_status()
    return session


def fetch_tle_data(session):
    resp = session.get(QUERY_URL)
    resp.raise_for_status()
    return resp.json()


def compute_positions(satellites):
    ts = load.timescale()
    t = ts.now()
    documents = []

    for sat in satellites:
        name = sat["OBJECT_NAME"]
        norad_id = int(sat["NORAD_CAT_ID"])
        line1 = sat["TLE_LINE1"]
        line2 = sat["TLE_LINE2"]

        try:
            satellite = EarthSatellite(line1, line2, name, ts)
            subpoint = satellite.at(t).subpoint()

            documents.append({
                "name": name,
                "norad_id": norad_id,
                "altitude_km": round(subpoint.elevation.km, 2),
                "tle_line1": line1,
                "tle_line2": line2,
                "location": {
                    "type": "Point",
                    "coordinates": [
                        round(subpoint.longitude.degrees, 4),
                        round(subpoint.latitude.degrees, 4),
                    ],
                },
            })
        except Exception as e:
            print(f"  SKIP {name} (NORAD {norad_id}): {e}")

    return documents


def load_to_mongodb(documents):
    client = MongoClient(MONGO_URI)
    db = client["opas_db"]
    collection = db["debris"]

    collection.delete_many({})
    result = collection.insert_many(documents)
    collection.create_index([("location", "2dsphere")])

    return len(result.inserted_ids)


def main():
    print("[1/5] Authenticating with Space-Track...")
    session = authenticate()
    print("  Done.")

    print("[2/5] Fetching TLE data (full catalog)...")
    satellites = fetch_tle_data(session)
    print(f"  Received {len(satellites)} records.")

    print("[3/5] Computing orbital positions (skyfield)...")
    documents = compute_positions(satellites)
    print(f"  Computed {len(documents)} positions.")

    print("[4/5] Loading to MongoDB (opas_db.debris)...")
    count = load_to_mongodb(documents)
    print(f"  Inserted {count} documents.")

    print("[5/5] 2dsphere index created on 'location'.")
    print("\nIngestion complete.")


if __name__ == "__main__":
    main()
