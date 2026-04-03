from datetime import datetime, timedelta
import logging

from services.traffic_service import TrafficService
from services.train_service import TrainService
from config import Config

logger = logging.getLogger(__name__)


class CommuteService:
    """
    Calculates road-only vs hybrid (road + train) commute options.

    Destination is always KJSCE Vidyavihar (hardcoded via Config).
    Leg structure:
        Leg 1 — Home  → Origin station       (road, live OSRM)
        Leg 2 — Origin station → Vidyavihar   (Slow Local train, hardcoded timetable)
        Leg 3 — Vidyavihar → KJSCE gate       (road/walk, live OSRM — NO default)
        Road  — Home  → KJSCE                 (direct drive, live OSRM)

    IMPORTANT: This service never silently uses hardcoded duration defaults.
    If any OSRM leg fails to return a real time, an exception is raised and
    propagated to the caller so the user gets an explicit error message.
    """

    DESTINATION   = Config.KJSCE_ADDRESS   # "KJSCE, Vidyavihar West, Mumbai..."
    DEST_STATION  = Config.KJSCE_STATION   # "Vidyavihar"

    # Vidyavihar station address used for OSRM leg3 origin
    VV_STATION_ADDRESS = "Vidyavihar Railway Station, Vidyavihar West, Mumbai, Maharashtra, India"

    # Keyword → nearest Central Line station (used by _nearest_station)
    STATION_MAP = {
        # Central Line
        "thane":       "Thane",
        "mulund":      "Thane",
        "dombivli":    "Dombivli",
        "kalyan":      "Kalyan",
        "ghatkopar":   "Ghatkopar",
        "kurla":       "Kurla",
        "dadar":       "Dadar",
        "csmt":        "CSMT",
        "fort":        "CSMT",
        "vidyavihar":  "Vidyavihar",

        # Trans-Harbour Line
        "airoli":         "Thane",
        "rabale":         "Thane",
        "ghansoli":       "Thane",
        "koparkhairane":  "Thane",
        "turbhe":         "Thane",
        "vashi":          "Kurla",   # faster via Harbour → Kurla

        # Harbour Line (mostly maps to Kurla)
        "panvel":       "Kurla",
        "nerul":        "Kurla",
        "sanpada":      "Kurla",
        "mankhurd":     "Kurla",
        "govandi":      "Kurla",
        "chembur":      "Kurla",
        "chunabhatti":  "Kurla",
        "wadala":       "Kurla",

        # Western Line (maps to Dadar interchange)
        "churchgate":      "Dadar",
        "marine lines":    "Dadar",
        "charni road":     "Dadar",
        "grant road":      "Dadar",
        "mumbai central":  "Dadar",
        "mahalaxmi":       "Dadar",
        "lower parel":     "Dadar",
        "prabhadevi":      "Dadar",
        "matunga road":    "Dadar",
        "mahim":           "Dadar",
        "bandra":          "Dadar",
        "khar":            "Dadar",
        "santacruz":       "Dadar",
        "vile parle":      "Dadar",
        "andheri":         "Dadar",
        "jogeshwari":      "Dadar",
        "goregaon":        "Dadar",
        "malad":           "Dadar",
        "kandivali":       "Dadar",
        "borivali":        "Dadar",
        "dahisar":         "Dadar",
        "mira road":       "Dadar",
        "bhayandar":       "Dadar",
        "vasai":           "Dadar",
        "virar":           "Dadar",
    }

    def __init__(self):
        self.traffic = TrafficService()
        self.trains  = TrainService()

    # ------------------------------------------------------------------
    def calculate_best_route(
        self,
        origin: str,
        arrival_time_str: str,
        delay_buffer_mins: int = 0,
    ) -> dict:
        """
        Returns a dict with road_route, train_route, and recommendation.

        :param origin:            Free-text home address
        :param arrival_time_str:  "HH:MM" — desired arrival at KJSCE
        :param delay_buffer_mins: Extra buffer added to train leg for expected delays

        Raises Exception if any required OSRM call fails.
        Never uses hardcoded duration defaults for any road leg.
        """
        arrival_dt = datetime.combine(
            datetime.now().date(),
            datetime.strptime(arrival_time_str, "%H:%M").time(),
        )

        # Clamp delay_buffer_mins to [0, 60] — guard against corrupt/malicious input.
        delay_buffer_mins = max(0, min(60, delay_buffer_mins))

        # ── Leg 3 via OSRM: Vidyavihar station → KJSCE gate ─────────────────
        # Resolved once here so both road and train branches use the same value.
        leg3_trip = self.traffic.get_travel_time(
            self.VV_STATION_ADDRESS, self.DESTINATION
        )
        if "error" in leg3_trip:
            raise Exception(
                f"OSRM could not calculate Vidyavihar Station → KJSCE gate time: "
                f"{leg3_trip['error']}. Cannot proceed without a real travel time."
            )
        leg3_mins = leg3_trip["duration_seconds"] / 60

        # ── Road-only route ──────────────────────────────────────────────────
        road_trip = self.traffic.get_travel_time(origin, self.DESTINATION)
        if "error" in road_trip:
            raise Exception(
                f"OSRM could not calculate Home → KJSCE road time: "
                f"{road_trip['error']}. Cannot proceed without a real travel time."
            )

        road_mins      = road_trip["duration_seconds"] / 60
        road_depart_dt = arrival_dt - timedelta(minutes=road_mins)

        road_route = {
            "mode":                "Road Only",
            "leave_at":            road_depart_dt.strftime("%H:%M"),
            "total_duration_mins": int(road_mins),
            "details": {
                "summary":  f"Drive directly ({road_trip['distance_text']})",
                "duration": road_trip["duration_text"],
            },
        }

        # ── Hybrid route (road + Slow Local train) ───────────────────────────
        origin_station = self._nearest_station(origin)
        train_route    = None

        if origin_station and origin_station != self.DEST_STATION:
            # Leg 1: Home → origin station (real OSRM time)
            leg1_trip = self.traffic.get_travel_time(
                origin, f"{origin_station} Railway Station, Mumbai"
            )
            if "error" in leg1_trip:
                raise Exception(
                    f"OSRM could not calculate Home → {origin_station} Station road time: "
                    f"{leg1_trip['error']}. Cannot proceed without a real travel time."
                )
            leg1_mins = leg1_trip["duration_seconds"] / 60

            # Latest acceptable Vidyavihar arrival:
            # Must leave walking time (leg3) + any expected train delay buffer.
            train_must_arrive_by = arrival_dt - timedelta(
                minutes=leg3_mins + delay_buffer_mins
            )

            # Find the LATEST Slow Local that still gets us there in time.
            # Use the new API that does this selection internally.
            best_train = self.trains.get_best_train_for_arrival(
                origin_station,
                train_must_arrive_by.strftime("%H:%M"),
            )

            if best_train:
                dept_t  = datetime.strptime(best_train["departure"], "%H:%M").time()
                dept_dt = datetime.combine(datetime.now().date(), dept_t)

                # Leave home early enough to catch the train
                home_depart_dt = dept_dt - timedelta(minutes=leg1_mins)

                # Total journey: home → platform → train → walk → KJSCE gate
                total_mins = int(
                    (arrival_dt - home_depart_dt).total_seconds() / 60
                )

                train_route = {
                    "mode":                "Hybrid (Road + Train)",
                    "leave_at":            home_depart_dt.strftime("%H:%M"),
                    "total_duration_mins": total_mins,
                    "delay_buffer_mins":   delay_buffer_mins,
                    "details": {
                        "leg1_road": (
                            f"Home → {origin_station} Station "
                            f"({int(leg1_mins)} mins, OSRM time)"
                        ),
                        "leg2_train": (
                            f"{best_train['type']} "
                            f"{origin_station} → {self.DEST_STATION} "
                            f"({best_train['departure']} – {best_train['arrival_vidyavihar']})"
                            + (
                                f" + {delay_buffer_mins} min delay buffer"
                                if delay_buffer_mins
                                else ""
                            )
                        ),
                        "leg3_walk": (
                            f"Vidyavihar Station → KJSCE gate "
                            f"({int(leg3_mins)} mins, OSRM time)"
                        ),
                    },
                }

        # ── Pick recommendation ───────────────────────────────────────────────
        if train_route:
            recommend = (
                "Train"
                if train_route["total_duration_mins"] < road_route["total_duration_mins"]
                else "Road"
            )
        else:
            recommend = "Road"

        return {
            "road_route":     road_route,
            "train_route":    train_route,   # may be None if no train qualifies
            "recommendation": recommend,
        }

    # ------------------------------------------------------------------
    def _nearest_station(self, location: str) -> str:
        """
        Returns the Central Line station name closest to the given location
        by keyword matching against STATION_MAP.

        Returns None if no keyword matches (caller should skip train route).
        """
        loc_lower = location.lower()
        for keyword, station in self.STATION_MAP.items():
            if keyword in loc_lower:
                return station
        # No match — cannot infer station; return None so caller skips train route.
        logger.info(
            "No station keyword matched for location '%s'. "
            "Train route will not be offered.",
            location,
        )
        return None
