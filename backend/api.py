import os
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient

load_dotenv()

app = FastAPI(title="OPAS – Orbital Proximity Alert System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = MongoClient(os.getenv("MONGO_URI"))
collection = client["opas_db"]["debris"]


@app.get("/alert")
def alert(
    target_lat: float = Query(..., description="Latitude in degrees"),
    target_lon: float = Query(..., description="Longitude in degrees"),
    target_alt: float = Query(..., description="Altitude in km"),
):
    pipeline = [
        {
            "$geoNear": {
                "near": {
                    "type": "Point",
                    "coordinates": [target_lon, target_lat],
                },
                "maxDistance": 100_000,
                "distanceField": "distance_meters",
                "spherical": True,
            }
        },
        {
            "$match": {
                "$expr": {
                    "$lt": [
                        {"$abs": {"$subtract": ["$altitude_km", target_alt]}},
                        50,
                    ]
                }
            }
        },
        {"$project": {"_id": 0}},
    ]

    threats = list(collection.aggregate(pipeline))

    return {
        "status": "danger" if threats else "safe",
        "target_coordinates": {
            "lat": target_lat,
            "lon": target_lon,
            "alt_km": target_alt,
        },
        "threats": threats,
    }
