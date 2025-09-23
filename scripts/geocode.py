#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geocode a CSV of apartments into data/apartments.json for the Leaflet frontend.

CSV columns expected (case-insensitive, accents allowed):
- loyer, adresse, cuisine_equipee, type, parking, chambres, surface_m2, url
- optional: latitude, longitude, label

Usage:
    python scripts/geocode.py
"""
import csv, json
from pathlib import Path
from typing import Dict, Any

try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
except Exception:
    raise SystemExit("Veuillez installer geopy :  pip install geopy")

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "apartments.csv"
JSON_PATH = ROOT / "data" / "apartments.json"
CACHE_PATH = ROOT / "data" / ".geocode_cache.json"

def norm_key(s: str) -> str:
    return s.strip().lower()

def load_cache() -> Dict[str, Any]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}

def save_cache(cache: Dict[str, Any]):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def to_float(v):
    if v is None: return None
    v = str(v).replace(",", ".").strip()
    try:
        return float(v)
    except ValueError:
        return None

def to_int(v):
    try:
        return int(float(str(v).replace(",", ".").strip()))
    except:
        return None

def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV introuvable: {CSV_PATH}")

    geolocator = Nominatim(user_agent="apartment-map-csv", timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)

    cache = load_cache()

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    out = []
    for row in rows:
        row = {norm_key(k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

        lat = to_float(row.get("latitude"))
        lon = to_float(row.get("longitude"))

        adr = row.get("adresse") or ""
        if (lat is None or lon is None) and adr:
            key = norm_key(adr)
            cached = cache.get(key)
            if cached is None:
                loc = geocode(adr)
                if loc:
                    cached = {"lat": loc.latitude, "lon": loc.longitude}
                cache[key] = cached
            if cached:
                lat, lon = cached["lat"], cached["lon"]

        out.append({
            "loyer": to_int(row.get("loyer")),
            "adresse": row.get("adresse"),
            "cuisine_equipee": row.get("cuisine_equipee"),
            "type": row.get("type"),
            "parking": row.get("parking"),
            "chambres": to_int(row.get("chambres")),
            "surface_m2": to_float(row.get("surface_m2")),
            "url": row.get("url"),
            "label": row.get("label"),
            "latitude": lat,
            "longitude": lon,
        })

    JSON_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    save_cache(cache)
    print(f"Écrit: {JSON_PATH} ({len(out)} lignes)")

if __name__ == "__main__":
    main()