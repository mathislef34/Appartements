#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ajoute une annonce au CSV à partir d'une URL (SeLoger pour l’instant) en
détectant automatiquement cuisine équipée / parking / type.

Usage:
    python scripts/add_from_url.py "https://www.seloger.com/annonces/..." \
        --csv data/apartments.csv --geocode
"""
import argparse, csv, json, re, subprocess, sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data" / "apartments.csv"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def has_any(text: str, patterns):
    return any(re.search(p, text, re.I) for p in patterns)

def detect_yes_no(text: str, positives, negatives):
    """
    Retourne 'oui' si un motif positif est trouvé,
            'non' si un motif négatif est trouvé,
            None sinon.
    """
    if has_any(text, negatives):
        return "non"
    if has_any(text, positives):
        return "oui"
    return None

def type_from_bedrooms(bedrooms):
    # convention: T1 = studio (0 ch), T2 = 1 ch, T3 = 2 ch, etc.
    if bedrooms is None:
        return None
    return f"T{max(1, bedrooms+1)}"

def try_json_ld(soup: BeautifulSoup):
    """
    lit application/ld+json ; renvoie dict avec:
    price, surface, address, bedrooms, rooms, amenity_features(list[str])
    """
    out = {}
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            obj = json.loads(tag.string or "{}")
        except Exception:
            continue
        cand = obj if isinstance(obj, list) else [obj]
        for o in cand:
            if not isinstance(o, dict):
                continue

            # prix
            price = None
            offers = o.get("offers")
            if isinstance(offers, dict):
                price = offers.get("price")
            elif isinstance(offers, list) and offers:
                price = (offers[0] or {}).get("price")
            if price is not None:
                try:
                    price = int(str(price).replace(" ", "").replace("\u202f", ""))
                except Exception:
                    price = None

            # surface
            surface = None
            fs = o.get("floorSize")
            if isinstance(fs, dict):
                surface = fs.get("value")
            if surface is not None:
                try:
                    surface = float(str(surface).replace(",", "."))
                except Exception:
                    surface = None

            # chambres / pièces
            bedrooms = o.get("numberOfBedrooms") or o.get("bedrooms")
            try:
                bedrooms = int(bedrooms) if bedrooms is not None else None
            except Exception:
                bedrooms = None

            rooms = o.get("numberOfRooms") or o.get("rooms")
            try:
                rooms = int(rooms) if rooms is not None else None
            except Exception:
                rooms = None

            # adresse
            address = None
            addr = o.get("address")
            if isinstance(addr, dict):
                street = addr.get("streetAddress") or ""
                postal = addr.get("postalCode") or ""
                locality = addr.get("addressLocality") or ""
                address = norm_space(", ".join(x for x in [street, postal, locality] if x))

            # amenities
            amenity_features = []
            af = o.get("amenityFeature")
            if isinstance(af, list):
                for it in af:
                    name = (it or {}).get("name")
                    if isinstance(name, str):
                        amenity_features.append(name.lower())

            if any([price, surface, address, bedrooms, rooms, amenity_features]):
                out.update(dict(
                    price=price, surface=surface, address=address,
                    bedrooms=bedrooms, rooms=rooms,
                    amenity_features=amenity_features
                ))
                return out
    return {}

def fallback_scrape_text(soup: BeautifulSoup):
    """Extrait du texte brut pour heuristiques (prix/surface inclus)."""
    text = soup.get_text(" ").lower()

    # prix
    price = None
    m = re.search(r"(\d[\d\u202f\s]{2,})\s*€", text)
    if m:
        try:
            price = int(m.group(1).replace(" ", "").replace("\u202f", ""))
        except Exception:
            pass

    # surface
    surface = None
    m = re.search(r"(\d+[.,]?\d*)\s*m²", text)
    if m:
        try:
            surface = float(m.group(1).replace(",", "."))
        except Exception:
            pass

    # chambres / pièces
    bedrooms = None
    rooms = None
    # "X chambre(s)"
    mc = re.search(r"(\d+)\s*chambre", text)
    if mc:
        bedrooms = int(mc.group(1))
    # "X pièce(s)"
    mr = re.search(r"(\d+)\s*pi[eè]ce", text)
    if mr:
        rooms = int(mr.group(1))

    # adresse: délicat → on ne tente pas ici (on la garde pour JSON-LD ou on demandera)
    return dict(text=text, price=price, surface=surface, bedrooms=bedrooms, rooms=rooms)

def detect_cuisine(text: str, amenity_features=None):
    positives = [
        r"\bcuisine\s+(am[eé]nag[eé]e\s+et\s+)?[eé]quip[eé]e\b",
        r"\bcuisine\s+semi[-\s]*[eé]quip[eé]e\b",
        r"\bkitchenette\s+[eé]quip[eé]e\b",
    ]
    # On considère "cuisine aménagée" comme un signal positif faible : si rien d'autre trouvé, on remonte "oui"
    weak_positives = [r"\bcuisine\s+am[eé]nag[eé]e\b"]
    negatives = [
        r"\bcuisine\s+non\s+[eé]quip[eé]e\b",
        r"\bsans\s+cuisine\b",
        r"\bpas\s+de\s+cuisine\b",
        r"\bcuisine\s+vide\b",
    ]

    val = detect_yes_no(text, positives, negatives)
    if val is None and has_any(text, weak_positives):
        val = "oui"  # interprétation courante FR : aménagée ≈ rangements/plan, souvent acceptée comme "ok"
    # JSON-LD amenityFeature éventuel
    if val is None and amenity_features:
        if any("cuisine" in a and ("équip" in a or "equip" in a) for a in amenity_features):
            val = "oui"
    return val

def detect_parking(text: str, amenity_features=None):
    positives = [
        r"\b(place\s+de\s+)?parking\b",
        r"\bstationnement\b",
        r"\bgarage\b",
        r"\bbox\b",
        r"\bparking\s+priv[eé]\b",
        r"\bresidence\s+avec\s+parking\b",
    ]
    negatives = [
        r"\bpas\s+de\s+parking\b",
        r"\bsans\s+parking\b",
        r"\bstationnement\s+dans\s+la\s+rue\b",
        r"\bstationnement\s+payant\b",
    ]
    val = detect_yes_no(text, positives, negatives)
    if val is None and amenity_features:
        if any(a for a in amenity_features if any(k in a for k in ["parking", "garage", "box"])):
            val = "oui"
    return val

def ensure_csv(path: Path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(
                "loyer,adresse,cuisine_equipee,type,parking,chambres,"
                "surface_m2,url,label,latitude,longitude\n"
            )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="URL de l'annonce (SeLoger)")
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--label", help="Texte court (quartier)")
    ap.add_argument("--geocode", action="store_true", help="Lancer scripts/geocode.py après ajout")
    args = ap.parse_args()

    # Récupération de la page
    r = requests.get(args.url, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    # 1) JSON-LD
    data = try_json_ld(soup)

    # 2) Fallback texte global
    fb = fallback_scrape_text(soup)
    text = fb.get("text", "")

    price = data.get("price") if "price" in data else fb.get("price")
    surface = data.get("surface") if "surface" in data else fb.get("surface")
    address = data.get("address")
    bedrooms = data.get("bedrooms", fb.get("bedrooms"))
    rooms = data.get("rooms", fb.get("rooms"))
    amenity_features = data.get("amenity_features", [])

    # si JSON-LD donne pièces mais pas chambres → approx chambres = pièces-1
    if bedrooms is None and rooms is not None and rooms >= 1:
        bedrooms = max(0, rooms - 1)

    # Détections auto
    cuisine_equipee = detect_cuisine(text, amenity_features)
    parking = detect_parking(text, amenity_features)

    # Type depuis chambres
    tpe = type_from_bedrooms(bedrooms)

    # Compléter via CLI si manquant/ambigu
    if price is None:
        price = int(input("Loyer (€) : ").strip())
    if address is None:
        address = input("Adresse complète (rue + ville) : ").strip()
    if surface is None:
        surface = float(input("Surface (m²) : ").replace(",", "."))
    if bedrooms is None:
        bedrooms = int(input("Nombre de chambres (0/1/2/3) : ").strip())
    if tpe is None:
        tpe = input("Type (T1/T2/T3/...) : ").strip().upper()
    if cuisine_equipee is None:
        cuisine_equipee = input("Cuisine équipée (oui/non) : ").strip().lower()
    if parking is None:
        parking = input("Parking (oui/non) : ").strip().lower()

    label = args.label or ""

    # Append CSV
    csv_path = Path(args.csv)
    ensure_csv(csv_path)
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            price, address, cuisine_equipee, tpe, parking, bedrooms, surface, args.url, label, "", ""
        ])

    print(f"✓ Ajouté au CSV: {csv_path}")
    if args.geocode:
        geo = ROOT / "scripts" / "geocode.py"
        print("→ Géocodage en cours…")
        subprocess.run([sys.executable, str(geo)], check=False)

if __name__ == "__main__":
    main()
