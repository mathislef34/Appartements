#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geocode a CSV of apartments into data/apartments.json (Leaflet frontend).

- Tolère BOM (utf-8-sig)
- Ignore colonnes sans en-tête (clé None)
- Fallback géocodage sur `label` (quartier) avec "city hint"
- Logs explicites quand une ligne n'est pas géocodée
"""
import csv, json, os
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

# Indice ville par défaut si seule un label/quartier est fourni
CITY_HINT = os.getenv("GEO_CITY_HINT", "Montpellier, France")

def norm_key(s) -> str:
    if s is None:
        return ""
    return str(s).strip().lower()

def load_cache() -> Dict[str, Any]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}

def save_cache(cache: Dict[str, Any]):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def to_float(v):
    if v is None or v == "":
        return None
    v = str(v).replace(",", ".").strip()
    try:
        return float(v)
    except ValueError:
        return None

def to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", ".").strip()))
    except Exception:
        return None

def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV introuvable: {CSV_PATH}")

    geolocator = Nominatim(user_agent="apartment-map-csv", timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)

    cache = load_cache()

    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    out = []
    missing_geo = 0

    for i, raw in enumerate(rows, start=1):
        # Nettoie: enlève colonnes sans nom et normalise les clés
        row = {}
        for k, v in raw.items():
            if k is None:
                continue
            kk = norm_key(k)
            row[kk] = v.strip() if isinstance(v, str) else v

        lat = to_float(row.get("latitude"))
        lon = to_float(row.get("longitude"))

        # 1) Adresse si dispo
        query = (row.get("adresse") or "").strip()

        # 2) Sinon label + ville par défaut
        if not query:
            lab = (row.get("label") or "").strip()
            if lab:
                query = f"{lab}, {CITY_HINT}"

        # Géocoder si coords manquantes et qu'on a une requête
        if (lat is None or lon is None) and query:
            key = norm_key(query)
            cached = cache.get(key)
            if cached is None:
                loc = geocode(query)
                if loc:
                    cached = {"lat": loc.latitude, "lon": loc.longitude}
                cache[key] = cached
            if cached:
                lat, lon = cached["lat"], cached["lon"]
            else:
                missing_geo += 1
                print(f"[WARN] Ligne {i}: géocodage introuvable pour '{query}'")

        out.append({
            "loyer": to_int(row.get("loyer")),
            "adresse": row.get("adresse") or None,
            "cuisine_equipee": row.get("cuisine_equipee") or None,
            "type": row.get("type") or None,
            "parking": row.get("parking") or None,
            "chambres": to_int(row.get("chambres")),
            "surface_m2": to_float(row.get("surface_m2")),
            "url": row.get("url") or None,
            "label": row.get("label") or None,
            "latitude": lat,
            "longitude": lon,
        })

    JSON_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    save_cache(cache)
    print(f"Écrit: {JSON_PATH} ({len(out)} lignes) ; sans géocodage: {missing_geo}")

if __name__ == "__main__":
    main()
