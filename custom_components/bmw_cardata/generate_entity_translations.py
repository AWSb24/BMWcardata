"""
Generate entity.sensor name translations for all KNOWN_CARDATA_KEYS.
Run from repo root: python custom_components/bmw_cardata/generate_entity_translations.py
Reads descriptors.py to get the key list (no Home Assistant dependency).
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _load_known_keys() -> list[str]:
    """Parse KNOWN_CARDATA_KEYS from descriptors.py without importing the integration."""
    base = Path(__file__).resolve().parent
    desc_path = base / "descriptors.py"
    text = desc_path.read_text(encoding="utf-8")
    keys = []
    in_list = False
    for line in text.splitlines():
        if "KNOWN_CARDATA_KEYS = [" in line:
            in_list = True
            continue
        if in_list:
            if line.strip() == "]":
                break
            # Line like:     "vehicle_vehicle_antiTheftAlarmSystem_alarm_activationTime",
            m = re.match(r'\s*"([^"]+)"', line)
            if m:
                keys.append(m.group(1))
    return keys


def key_to_display_name(key: str) -> str:
    """Convert key to title case, split camelCase, and remove consecutive duplicate words."""
    # Split camelCase: antiTheftAlarmSystem -> anti Theft Alarm System
    def split_camel(s: str) -> list[str]:
        return re.sub(r"([a-z])([A-Z])", r"\1 \2", s).split()

    words = []
    for part in key.split("_"):
        words.extend(split_camel(part))
    if not words:
        return key
    # Title case each word and deduplicate consecutive same (case-insensitive)
    titled = [w.title() for w in words]
    result = [titled[0]]
    for w in titled[1:]:
        if w.lower() != result[-1].lower():
            result.append(w)
    return " ".join(result)


# Map English segment (lowercase) -> German for building German entity names
DE_WORDS: dict[str, str] = {
    "vehicle": "Fahrzeug",
    "door": "Tür",
    "driver": "Fahrer",
    "passenger": "Beifahrer",
    "row1": "Reihe 1",
    "row2": "Reihe 2",
    "row3": "Reihe 3",
    "left": "Links",
    "right": "Rechts",
    "battery": "Batterie",
    "charging": "Laden",
    "fuel": "Kraftstoff",
    "level": "Füllstand",
    "engine": "Motor",
    "electric": "Elektro",
    "drivetrain": "Antrieb",
    "cabin": "Innenraum",
    "trunk": "Kofferraum",
    "hood": "Motorhaube",
    "status": "Status",
    "distance": "Strecke",
    "time": "Zeit",
    "speed": "Geschwindigkeit",
    "tire": "Reifen",
    "pressure": "Druck",
    "temperature": "Temperatur",
    "latitude": "Breitengrad",
    "longitude": "Längengrad",
    "navigation": "Navigation",
    "location": "Standort",
    "current": "Aktuell",
    "body": "Karosserie",
    "chassis": "Fahrwerk",
    "axle": "Achse",
    "wheel": "Rad",
    "open": "Offen",
    "lock": "Verriegelung",
    "lights": "Lichter",
    "port": "Anschluss",
    "combined": "Kombiniert",
    "moving": "In Bewegung",
    "travelled": "Zurückgelegt",
    "avg": "Durchschn.",
    "seat": "Sitz",
    "heating": "Heizung",
    "steering": "Lenkrad",
    "sunroof": "Schiebedach",
    "overall": "Gesamt",
    "window": "Fenster",
    "row": "Reihe",
    "driverSide": "Fahrerseite",
    "passengerSide": "Beifahrerseite",
    "check": "Prüfung",
    "control": "Kontrolle",
    "messages": "Meldungen",
    "condition": "Zustand",
    "based": "basiert",
    "services": "Dienste",
    "service": "Service",
    "next": "Nächster",
    "inspection": "Inspektion",
    "date": "Datum",
    "legal": "Gesetzlich",
    "trip": "Fahrt",
    "segment": "Abschnitt",
    "end": "Ende",
    "preconditioning": "Vorklimatisierung",
    "activity": "Aktivität",
    "remaining": "Verbleibend",
    "hvac": "Klima",
    "progress": "Fortschritt",
    "climate": "Klima",
    "timers": "Timer",
    "weekdays": "Wochentage",
    "timer": "Timer",
    "action": "Aktion",
    "method": "Methode",
    "connector": "Stecker",
    "connection": "Verbindung",
    "type": "Typ",
    "powertrain": "Antriebsstrang",
    "traction": "Traktions",
    "any": "Beliebig",
    "position": "Position",
    "plugged": "Eingesteckt",
    "front": "Vorne",
    "rear": "Hinten",
    "middle": "Mitte",
    "flap": "Klappe",
    "target": "Ziel",
    "state": "Zustand",
    "charge": "Ladung",
    "range": "Reichweite",
    "profile": "Profil",
    "mode": "Modus",
    "preference": "Einstellung",
    "phase": "Phase",
    "number": "Anzahl",
    "channel": "Kanal",
    "display": "Anzeige",
    "unit": "Einheit",
    "mobile": "Mobil",
    "phone": "Telefon",
    "connected": "Verbunden",
    "sim": "SIM",
    "setting": "Einstellung",
    "lower": "Untere",
    "bound": "Grenze",
    "upper": "Obere",
    "average": "Durchschnitt",
    "weekly": "Wöchentlich",
    "long": "Lang",
    "term": "Frist",
    "short": "Kurz",
    "convertible": "Cabrio",
    "roof": "Dach",
    "retractable": "Einziehbar",
    "locked": "Verriegelt",
    "permanently": "Dauerhaft",
    "unlocked": "Entriegelt",
    "air": "Luft",
    "purification": "Filterung",
    "configuration": "Konfiguration",
    "default": "Standard",
    "settings": "Einstellungen",
    "direct": "Direkt",
    "start": "Start",
    "comfort": "Komfort",
    "defrost": "Entfrostung",
    "active": "Aktiv",
    "remote": "Fern",
    "allowed": "Erlaubt",
    "error": "Fehler",
    "destination": "Ziel",
    "set": "Gesetzt",
    "arrival": "Ankunft",
    "points": "Punkte",
    "interests": "Interessen",
    "available": "Verfügbar",
    "max": "Max",
    "learning": "Lernen",
    "count": "Anzahl",
    "per": "Pro",
    "day": "Tag",
    "yellow": "Gelb",
    "preferred": "Bevorzugt",
    "partner": "Partner",
    "demand": "Anforderung",
    "defect": "Defekt",
    "id": "ID",
    "teleservice": "Teleservice",
    "last": "Letzter",
    "automatic": "Automatisch",
    "call": "Anruf",
    "manual": "Manuell",
    "breakdown": "Panne",
    "report": "Bericht",
    "diagnosis": "Diagnose",
    "accumulated": "Kumuliert",
    "transmission": "Getriebe",
    "fraction": "Anteil",
    "drive": "Fahren",
    "ecopro": "Eco Pro",
    "ecoproplus": "Eco Pro Plus",
    "energy": "Energie",
    "consumption": "Verbrauch",
    "acceleration": "Beschleunigung",
    "brake": "Bremse",
    "stars": "Sterne",
    "relative": "Relativ",
    "tilt": "Kipp",
    "shade": "Sonnenschutz",
    "overwrite": "Überschreiben",
    "hour": "Stunde",
    "minute": "Minute",
    "hospitality": "Gastfreundschaft",
    "duration": "Dauer",
    "departure": "Abfahrt",
    "climatization": "Klimatisierung",
    "reason": "Grund",
    "route": "Route",
    "optimized": "Optimiert",
    "cooling": "Kühlung",
    "lifetime": "Lebensdauer",
    "overall": "Gesamt",
    "reference": "Referenz",
    "privacy": "Datenschutz",
    "data": "Daten",
    "collection": "Sammlung",
    "regulations": "Vorschriften",
    "identification": "Identifikation",
    "contract": "Vertrag",
    "list": "Liste",
    "disclaimer": "Hinweis",
    "electrical": "Elektrisch",
    "system": "System",
    "recharge": "Aufladen",
    "replace": "Ersetzen",
    "plausibility": "Plausibilität",
    "voltage": "Spannung",
    "health": "Zustand",
    "displayed": "Angezeigt",
    "power": "Leistung",
    "management": "Verwaltung",
    "header": "Kopf",
    "size": "Größe",
    "internal": "Intern",
    "combustion": "Verbrennung",
    "ect": "Kühlmitteltemp.",
    "infotainment": "Infotainment",
    "altitude": "Höhe",
    "heading": "Richtung",
    "satellites": "Satelliten",
    "fix": "Fix",
    "antitheftalarmsystem": "Diebstahlwarnanlage",
    "alarm": "Alarm",
    "activation": "Aktivierung",
    "arm": "Bewaffnet",
    "ison": "An",
    "timetofullycharged": "Zeit bis voll geladen",
    "remainingelectricrange": "Verbl. Elektro-Reichweite",
    "kombiremainingelectricrange": "Kombi verbl. Elektro-Reichweite",
    "hvsmaxenergyabsolute": "HVS max. Energie absolut",
    "fuelsystem": "Kraftstoffsystem",
    "remainingfuel": "Verbl. Kraftstoff",
    "lastremainingrange": "Letzte verbl. Reichweite",
    "totalremainingrange": "Gesamt verbl. Reichweite",
    "avgelectricrangeconsumption": "Ø Elektro-Reichweitenverbrauch",
    "isactive": "Aktiv",
    "isignitionon": "Zündung an",
    "internalcombustionengine": "Verbrennungsmotor",
    "currentlocation": "Aktueller Standort",
    "numberofsatellites": "Anzahl Satelliten",
    "fixstatus": "Fix-Status",
    "trunkdoor": "Kofferraumtür",
    "chargingport": "Ladeanschluss",
    "isrunningon": "Läuft",
    "ismoving": "In Bewegung",
    "travelleddistance": "Zurückgelegte Strecke",
    "avgspeed": "Durchschn. Geschwindigkeit",
    "isopen": "Offen",
    "combinedstatus": "Kombinierter Status",
    "isplugged": "Eingesteckt",
    "anyposition": "Beliebige Position",
    "frontleft": "Vorne links",
    "frontright": "Vorne rechts",
    "rearleft": "Hinten links",
    "rearright": "Hinten rechts",
    "stateofcharge": "Ladezustand",
    "connectiontype": "Verbindungstyp",
    "connectorstatus": "Steckerstatus",
    "acampere": "AC-Ampere",
    "acvoltage": "AC-Spannung",
    "phasenumber": "Phasenanzahl",
    "timevehicle": "Fahrzeugzeit",
    "displayunit": "Anzeigeeinheit",
    "distanceunit": "Streckeneinheit",
    "ismobilephoneconnected": "Handy verbunden",
    "simstatus": "SIM-Status",
    "timesetting": "Zeiteinstellung",
    "avgauxpower": "Durchschn. Hilfsleistung",
    "deepsleepmodeactive": "Tiefschlafmodus aktiv",
    "speedrange": "Geschwindigkeitsbereich",
    "lowerbound": "Untere Grenze",
    "upperbound": "Obere Grenze",
    "averageweeklydistancelongterm": "Ø wöchentl. Strecke langfristig",
    "averageweeklydistanceshortterm": "Ø wöchentl. Strecke kurzfristig",
    "roofstatus": "Dachstatus",
    "roofretractablestatus": "Dach einziehbar Status",
    "islocked": "Verriegelt",
    "ispermanentlyunlocked": "Dauerhaft entriegelt",
    "statusairpurification": "Status Luftfilterung",
    "defaultsettings": "Standardeinstellungen",
    "targettemperature": "Zieltemperatur",
    "directstartsettings": "Direktstart-Einstellungen",
    "comfortstate": "Komfortzustand",
    "reardefrostactive": "Heckentfrostung aktiv",
    "isremoteenginerunning": "Fernmotor läuft",
    "isremoteenginestartallowed": "Fernstart erlaubt",
    "preconditioningerror": "Vorklimatisierungsfehler",
    "pointsofinterests": "Points of Interest",
    "remainingrange": "Verbl. Reichweite",
    "learningnavigation": "Navigation lernen",
    "conditionbasedservicescount": "Zustandsb. Dienste Anzahl",
    "conditionbasedservicesaveragedistanceperday": "Zustandsb. Dienste Ø Strecke/Tag",
    "servicedistance": "Service-Strecke",
    "servicetime": "Service-Zeit",
    "huandaauserviceyellow": "HU und AU Service Gelb",
    "preferredsevicepartner": "Bevorzugter Service-Partner",
    "sevice": "Service",
    "lastautomaticservicecalltime": "Letzter automat. Service-Anruf",
    "lastmanualcalltime": "Letzter manueller Anruf",
    "lastbreakdowncalltime": "Letzter Pannen-Anruf",
    "lastteleservicereporttime": "Letzter Teleservice-Bericht",
    "pressuretarget": "Soll-Druck",
    "displaycontrol": "Anzeigesteuerung",
    "chargingduration": "Ladedauer",
    "departuretime": "Abfahrtszeit",
    "timertype": "Timer-Typ",
    "climatizationactive": "Klimatisierung aktiv",
    "smeenergydeltafullycharged": "SME Energie Delta voll geladen",
    "reasonchargingend": "Grund Ladeende",
    "hvpmfinishreason": "HVPM Beendigungsgrund",
    "hvstatus": "HV-Status",
    "routeoptimizedchargingstatus": "Routenoptimierter Lade-Status",
    "consumptionoverlifetime": "Verbrauch Lebensdauer",
    "datacollection": "Datensammlung",
    "obfcm": "OBFCM",
    "connecteddrivecontractlist": "ConnectedDrive Vertragsliste",
    "isremoteenginestartdisclaimer": "Hinweis Fernstart",
}


def key_to_german_name(key: str) -> str:
    """Build German display name from key by translating segments and deduplicating."""
    parts = key.replace("_", " ").split()
    out = []
    for p in parts:
        # Split camelCase: timeRemaining -> time, Remaining
        sub = re.sub(r"([a-z])([A-Z])", r"\1 \2", p).split()
        segment_words = []
        for s in sub:
            seg_lower = s.lower()
            if seg_lower in DE_WORDS:
                segment_words.append(DE_WORDS[seg_lower])
            else:
                segment_words.append(s.title())
        trans = " ".join(segment_words) if segment_words else (DE_WORDS.get(p.lower()) or p.title())
        out.append(trans)
    # Deduplicate consecutive same (case-insensitive)
    result = [out[0]] if out else []
    for w in out[1:]:
        if not result or (result[-1].lower() != w.lower()):
            result.append(w)
    return " ".join(result)


def main() -> None:
    known_keys = _load_known_keys()
    sensor_entity: dict[str, dict[str, str]] = {}
    sensor_entity_de: dict[str, dict[str, str]] = {}
    for key in dict.fromkeys(known_keys):
        trans_key = key.lower()
        sensor_entity[trans_key] = {"name": key_to_display_name(key)}
        sensor_entity_de[trans_key] = {"name": key_to_german_name(key)}

    out_en = {"entity": {"sensor": sensor_entity}}
    out_de = {"entity": {"sensor": sensor_entity_de}}

    base = Path(__file__).resolve().parent
    (base / "entity_translations_en.json").write_text(
        json.dumps(out_en, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (base / "entity_translations_de.json").write_text(
        json.dumps(out_de, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Generated {len(sensor_entity)} sensor name translations")

    # Merge into main translation files so Home Assistant loads them
    merge_into_main_translations(base, out_en, out_de)


def merge_into_main_translations(
    base: Path, gen_en: dict, gen_de: dict
) -> None:
    """Merge generated entity.sensor into strings.json, translations/en.json, translations/de.json."""
    for path, gen in [
        (base / "strings.json", gen_en),
        (base / "translations" / "en.json", gen_en),
        (base / "translations" / "de.json", gen_de),
    ]:
        if not path.exists():
            print(f"  Skip {path} (not found)")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if "entity" not in data:
            data["entity"] = {}
        if "sensor" not in data["entity"]:
            data["entity"]["sensor"] = {}
        # Keep existing status, vin (and their state) if present; merge generated sensor keys
        existing = data["entity"]["sensor"]
        data["entity"]["sensor"] = {**gen["entity"]["sensor"]}
        for key in ("status", "vin"):
            if key in existing:
                data["entity"]["sensor"][key] = existing[key]
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  Merged into {path.name}")


if __name__ == "__main__":
    main()
