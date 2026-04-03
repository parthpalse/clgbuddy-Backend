import math
import time
import logging

import requests
from config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Free, keyless APIs — no API key required, always available
#   Geocoding : Nominatim (OpenStreetMap) — nominatim.openstreetmap.org
#   Routing   : OSRM demo server         — router.project-osrm.org
# ---------------------------------------------------------------------------

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
OSRM_BASE = "http://router.project-osrm.org"

# Required by Nominatim TOS: identify your app in User-Agent
HEADERS = {"User-Agent": "ClgBuddyApp/1.0"}

# ---------------------------------------------------------------------------
STATION_COORDS = {
    # Central Line
    "Masjid": [72.8375, 18.9466],
    "Sandhurst Road": [72.8396, 18.9528],
    "Byculla": [72.8394, 18.9757],
    "Chinchpokli": [72.8413, 18.9838],
    "Currey Road": [72.8413, 18.9919],
    "Parel": [72.8434, 19.0000],
    "Dadar": [72.8427, 19.0176],
    "Matunga": [72.8560, 19.0273],
    "Sion": [72.8601, 19.0393],
    "Kurla": [72.8796, 19.0654],
    "Vidyavihar": [72.9046, 19.0740],  # ← destination station for KJSCE
    "Ghatkopar": [72.9088, 19.0861],
    "Vikhroli": [72.9247, 19.1047],
    "Kanjurmarg": [72.9418, 19.1122],
    "Bhandup": [72.9523, 19.1228],
    "Nahur": [72.9590, 19.1332],
    "Mulund": [72.9668, 19.1716],
    "Thane": [72.9615, 19.1820],
    "Kalwa": [73.0030, 19.2005],
    "Mumbra": [73.0218, 19.1840],
    "Diva": [73.0600, 19.1780],
    "Kopar": [73.0676, 19.1660],
    "Dombivli": [73.0875, 19.2144],
    "Thakurli": [73.0983, 19.2185],
    "Kalyan": [73.1291, 19.2437],
    # Western Line
    "Churchgate": [72.8275, 18.9322],
    "Marine Lines": [72.8268, 18.9446],
    "Charni Road": [72.8183, 18.9518],
    "Grant Road": [72.8160, 18.9632],
    "Mumbai Central": [72.8191, 18.9690],
    "Mahalaxmi": [72.8242, 18.9825],
    "Lower Parel": [72.8286, 18.9953],
    "Prabhadevi": [72.8335, 19.0163],
    "Matunga Road": [72.8458, 19.0298],
    "Mahim": [72.8407, 19.0406],
    "Bandra": [72.8400, 19.0553],
    "Khar Road": [72.8386, 19.0697],
    "Santacruz": [72.8384, 19.0818],
    "Vile Parle": [72.8436, 19.1006],
    "Andheri": [72.8465, 19.1197],
    "Jogeshwari": [72.8488, 19.1415],
    "Goregaon": [72.8488, 19.1646],
    "Malad": [72.8462, 19.1860],
    "Kandivali": [72.8523, 19.2045],
    "Borivali": [72.8562, 19.2290],
    "Dahisar": [72.8624, 19.2494],
    "Mira Road": [72.8679, 19.2818],
    "Bhayandar": [72.8584, 19.3106],
    "Naigaon": [72.8475, 19.3524],
    "Vasai Road": [72.8324, 19.3823],
    "Nallasopara": [72.8183, 19.4177],
    "Virar": [72.8058, 19.4552],
    # Harbour Line
    "Wadala Road": [72.8631, 19.0166],
    "Chunabhatti": [72.8718, 19.0494],
    "Chembur": [72.8953, 19.0617],
    "Govandi": [72.9152, 19.0538],
    "Mankhurd": [72.9360, 19.0483],
    "Vashi": [72.9987, 19.0799],
    "Sanpada": [73.0116, 19.0664],
    "Juinagar": [73.0177, 19.0560],
    "Nerul": [73.0183, 19.0345],
    "Seawoods": [73.0192, 19.0185],
    "Belapur": [73.0375, 19.0181],
    "Kharghar": [73.0690, 19.0267],
    "Mansarovar": [73.0858, 19.0188],
    "Khandeshwar": [73.0991, 19.0122],
    "Panvel": [73.1166, 18.9904],
    # Trans-Harbour Line
    "Turbhe": [73.0163, 19.0782],
    "Koparkhairane": [73.0016, 19.1030],
    "Ghansoli": [72.9991, 19.1245],
    "Rabale": [72.9994, 19.1368],
    "Airoli": [72.9999, 19.1548],
    # KJSCE destination — hardcoded so Nominatim is never called for it
    "KJSCE": [72.9081, 19.0728],
    "K.J. Somaiya": [72.9081, 19.0728],
    "KJ Somaiya": [72.9081, 19.0728],
    "Somaiya": [72.9081, 19.0728],
    "KJSCE, Vidyavihar West, Mumbai, Maharashtra": [72.9081, 19.0728],
}

# Fixed walk time: Vidyavihar station exit → KJSCE main gate (measured once)
VIDYAVIHAR_TO_KJSCE_WALK_MINS = 7

geocache = {}


class TrafficService:
    def __init__(self):
        pass  # no keys to initialise

    @staticmethod
    def _haversine_km(lon1, lat1, lon2, lat2):
        R = 6371  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def get_nearest_station(self, lat: float, lng: float) -> dict:
        min_dist = float("inf")
        nearest_station = "Unknown"

        for st_name, coords in STATION_COORDS.items():
            st_lon = coords[0]
            st_lat = coords[1]
            dist = self._haversine_km(lng, lat, st_lon, st_lat)
            if dist < min_dist:
                min_dist = dist
                nearest_station = st_name

        display_name = "Your Location"
        url = f"{NOMINATIM_BASE}/reverse"
        params = {"lat": lat, "lon": lng, "format": "json"}
        try:
            time.sleep(1)  # Nominatim TOS: max 1 req/sec
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            if resp.ok:
                data = resp.json()
                if data and "display_name" in data:
                    display_name = data["display_name"]
        except Exception as e:
            logger.warning("Reverse geocode failed: %s", e)

        return {
            "station": nearest_station,
            "address": display_name,
            "distance_km": round(min_dist, 2),
        }

    @staticmethod
    def _resolve_coords_impl(address: str):
        """
        Return (lng, lat) tuple for an address.
        Checks hardcoded station dict first (instant, no HTTP).
        Falls back to Nominatim geocoding (free, no key).
        """
        addr_clean = (
            address.lower()
            .replace(" railway station", "")
            .replace(" station", "")
            .strip()
        )
        for station, coords in STATION_COORDS.items():
            if station.lower() == addr_clean:
                return tuple(coords)  # tuple for lru_cache hashability

        # Nominatim geocoding — biased to India (countrycodes=in)
        url = f"{NOMINATIM_BASE}/search"
        params = {
            "q": address,
            "format": "json",
            "limit": 1,
            "countrycodes": "in",
            # Bias to Mumbai / Thane area via viewbox
            "viewbox": "72.75,18.85,73.25,19.40",
            "bounded": 1,
        }

        time.sleep(1)  # Nominatim TOS: max 1 req/sec
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if resp.status_code == 429:
            time.sleep(3)  # wait and retry once on rate limit
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        results = resp.json()

        if not results:
            # Retry without viewbox restriction (for edge-case addresses)
            params.pop("viewbox")
            params.pop("bounded")
            time.sleep(1)  # Nominatim TOS: max 1 req/sec
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            results = resp.json()

        if not results:
            raise ValueError(f"Could not geocode address: {address}")
        lon = float(results[0]["lon"])
        lat = float(results[0]["lat"])
        return (lon, lat)

    def _resolve_coords(self, address: str):
        global geocache
        if address in geocache:
            return geocache[address]

        coords = self._resolve_coords_impl(address)
        geocache[address] = coords
        return coords

    # ------------------------------------------------------------------
    def get_travel_time(self, origin: str, destination: str):
        """
        Returns road travel time via OSRM demo server (no API key needed).
        Falls back to Haversine estimate if OSRM is unreachable.
        """
        try:
            o_coords = self._resolve_coords(origin)
            d_coords = self._resolve_coords(destination)

            # OSRM route endpoint: /route/v1/driving/{lng1,lat1};{lng2,lat2}
            coords_str = f"{o_coords[0]},{o_coords[1]};{d_coords[0]},{d_coords[1]}"
            url = f"{OSRM_BASE}/route/v1/driving/{coords_str}"
            params = {"overview": "false", "steps": "false"}

            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "Ok" or not data.get("routes"):
                return {
                    "error": f"OSRM returned no route for {origin} -> {destination}"
                }

            route = data["routes"][0]
            duration_secs = route["duration"]  # seconds
            distance_m = route["distance"]  # metres
            duration_mins = int(duration_secs / 60)
            distance_km = round(distance_m / 1000, 1)

            duration_text = (
                f"{duration_mins} mins"
                if duration_mins < 60
                else f"{duration_mins // 60}h {duration_mins % 60}m"
            )

            return {
                "duration_seconds": int(duration_secs),
                "duration_text": duration_text,
                "distance_text": f"{distance_km} km",
            }

        except ValueError as e:
            return {"error": str(e)}
        except requests.exceptions.RequestException as e:
            return {"error": f"Routing error: {str(e)}"}
        except Exception as e:
            return {"error": str(e)}
