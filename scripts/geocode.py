#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geocode a CSV of apartments into data/apartments.json (Leaflet frontend).

- Tolère BOM (utf-8-sig)
- Ignore colonnes sans en-tête (clé None)
- Fallback géocodage sur `label` (quartier) + ville par défaut
- RESTRICTION Montpellier: viewbox + bounded + countrycodes=fr
- Rejette les résultats trop éloignés (> GEO_MAX_KM km) pour éviter les faux positifs
"""
import csv, json, os
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
except Exception:
    raise SystemExit("Veuillez installer geopy :  pip install geopy")

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "apartments.csv"
JSON_PATH = ROOT / "data" / "apartments.json"
CACHE_PATH = ROOT / "data" / ".geocode_cache.json"

# ====== Configuration via variables d'environnement (avec valeurs par défaut) ======
CITY_HINT = os.getenv("GEO_CITY_HINT", "Montpellier, France")
# viewbox = "left,top,right,bottom" (lon_min, lat_max, lon_max, lat_min)
# Cette box couvre Montpellier + communes limitrophes (Castelnau, Juvignac, Lattes, St-Jean-de-Védas…)
VIEWBOX_STR = os.getenv("GEO_VIEWBOX", "3.75,43.72,4.05,43.53")
COUNTRY_CODES = os.getenv("GEO_COUNTRY_CODES", "fr")
MAX_KM = float(os.getenv("GEO_MAX_KM", "30"))  # distance max du centre avant rejet

def parse_viewbox(s: str) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """
    Retourne (viewbox_str, center_lat, center_lon) où viewbox_str est gardé tel quel
    pour l'appel Nominatim, et centre calculé pour la vérif distance.
    Format attendu: "left,top,right,bottom"
    """
    try:
        left, top, right, bottom = [float(x.strip()) for x in s.split(",")]
        center_lat = (top + bottom) / 2.0
        center_lon = (left + right) / 2.0
        return s, center_lat, center_lon
    except Exception:
        return None, None, None

VIEWBOX_PARAM, CENTER_LAT, CENTER_LON = parse_viewbox(VIEWBOX_STR)

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(p1) * cos(p2) * sin(dlambda/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

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

def geocode_query(geocode_fn, query: str):
    """
    Appelle Nominatim avec viewbox/countrycodes/langue, + filtrage distance autour de Montpellier.
    """
    params = dict(
        language="fr",
        country_codes=COUNTRY_CODES,
        exactly_one=True,
        addressdetails=False,
    )
    if VIEWBOX_PARAM:
        # Passe la viewbox telle quelle et borne la recherche
        params.update(dict(viewbox=VIEWBOX_PARAM, bounded=True))

    loc = geocode_fn(query, **params)
    if loc and CENTER_LAT is not None and CENTER_LON is not None and MAX_KM > 0:
        d = haversine_km(CENTER_LAT, CENTER_LON, loc.latitude, loc.longitude)
        if d > MAX_KM:
            print(f"[WARN] '{query}' trop éloigné ({d:.1f} km) — rejeté.")
            return None
    return loc

def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV introuvable: {CSV_PATH}")

    geolocator = Nominatim(user_agent="apartment-map-csv", timeout=15)
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

        # Requête de géocodage:
        # 1) Adresse si dispo
        query = (row.get("adresse") or "").strip()

        # 2) Sinon label (quartier) + ville par défaut
        if not query:
            lab = (row.get("label") or "").strip()
            if lab:
                query = f"Quartier {lab}, {CITY_HINT}"

        # Géocoder si coords manquantes et qu'on a une requête
        if (lat is None or lon is None) and query:
            key = norm_key(f"{query}|{VIEWBOX_PARAM}|{COUNTRY_CODES}")
            cached = cache.get(key)
            if cached is None:
                loc = geocode_query(geocode, query)
                if not loc and "quartier" not in query.lower() and (row.get("label") or "").strip():
                    # Retente avec mot-clé Quartier si pas déjà fait
                    loc = geocode_query(geocode, f"Quartier {row.get('label').strip()}, {CITY_HINT}")
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
