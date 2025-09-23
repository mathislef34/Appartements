#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geocode a CSV of apartments into data/apartments.json for the Leaflet frontend.

Robust to:
- BOM in header (reads as utf-8-sig)
- Extra unnamed columns (skips keys == None)
- Missing address: fallback to `label` (e.g., neighborhood like "Ovalie")

CSV columns (case-insensitive):
  loyer, adresse, cuisine_equipee, type, parking, chambres, surface_m2, url, label
optional:
  latitude, longitude
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

    # utf-8-sig -> gère un éventuel BOM au début des en-têtes
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    out = []
    for raw in rows:
        # Nettoie: enlève les colonnes sans nom (clé None) et normalise les clés/valeurs
        row = {}
        for k, v in raw.items():
            if k is None:
                # ligne avec plus de colonnes que d'en-têtes -> on ignore proprement
                continue
            kk = norm_key(k)
            row[kk] = v.strip() if isinstance(v, str) else v

        lat = to_float(row.get("latitude"))
        lon = to_float(row.get("longitude"))

        # Adresse prioritaire, sinon fallback sur le label (quartier)
        adr = (row.get("adresse") or "").strip()
        if not adr:
            lab = (row.get("label") or "").strip()
            if lab:
                adr = lab  # ex: "Ovalie" ; Nominatim retournera un centroïde si trouvé

        # Géocode seulement si coordonnées manquantes ET qu'on a une requête (adresse/label)
        if (lat is None or lon is None) and adr:
            key = norm_key(adr)
            # petit cache mémoire/disk pour éviter les répétitions
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
    print(f"Écrit: {JSON_PATH} ({len(out)} lignes)")

if __name__ == "__main__":
    main()
