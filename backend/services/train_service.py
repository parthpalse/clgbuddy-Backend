from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded Mumbai Central-Line SLOW LOCAL timetable: Thane → Vidyavihar
#
# Rules applied:
#   • ONLY Slow Local trains — Fast Locals skip Vidyavihar entirely.
#   • Vidyavihar has NO Fast Local stop — never recommend Fast Local.
#   • Trains depart Thane every ~15 minutes, 06:00 – 10:00.
#   • Travel time Thane → Vidyavihar on a Slow Local: ~22 minutes.
#   • Source: Mumbai suburban railway approximate timetable (Central Line).
# ---------------------------------------------------------------------------

# Each entry: (departure_thane_HH_MM, arrival_vidyavihar_HH_MM)
# All are SLOW LOCAL only.
_SLOW_LOCAL_THANE_TO_VV: list[tuple[str, str]] = [
    ("06:00", "06:22"),
    ("06:15", "06:37"),
    ("06:30", "06:52"),
    ("06:45", "07:07"),
    ("07:00", "07:22"),
    ("07:15", "07:37"),
    ("07:30", "07:52"),
    ("07:45", "08:07"),
    ("08:00", "08:22"),
    ("08:15", "08:37"),
    ("08:30", "08:52"),
    ("08:45", "09:07"),
    ("09:00", "09:22"),
    ("09:15", "09:37"),
    ("09:30", "09:52"),
    ("09:45", "10:07"),
    ("10:00", "10:22"),
]

# Offset table: minutes relative to Thane departure.
# Positive  = station is BEFORE Thane (train hasn't reached Thane yet).
# Negative  = station is AFTER  Thane (train has already passed Thane).
# All values are for Slow Local only.
_OFFSET_FROM_THANE: dict[str, int] = {
    "Kalyan":       35,
    "Thakurli":     28,
    "Dombivli":     22,
    "Kopar":        18,
    "Diva":         14,
    "Mumbra":       10,
    "Kalwa":         5,
    "Thane":         0,
    "Mulund":       -5,
    "Nahur":        -8,
    "Bhandup":     -11,
    "Kanjurmarg":  -14,
    "Vikhroli":    -17,
    "Ghatkopar":   -18,
    "Vidyavihar":  -22,
    "Kurla":       -25,
    "Sion":        -28,
    "Dadar":       -34,
    "CSMT":        -45,
}

# Stations that are on the Trans-Harbour Line and need an interchange at Thane
_TRANS_HARBOUR: frozenset[str] = frozenset({
    "Ghansoli", "Airoli", "Rabale", "Koparkhairane",
    "Turbhe", "Vashi", "Sanpada", "Nerul", "Belapur", "Panvel",
})

DEST_STATION = "Vidyavihar"
DEST_OFFSET  = _OFFSET_FROM_THANE[DEST_STATION]   # -22
# Minimum safety margin: train must arrive at Vidyavihar this many minutes
# BEFORE the user's desired arrival time to allow for walking to college gate.
# (The actual walk leg is calculated separately by commute_service via OSRM.)
ARRIVAL_BUFFER_MINS = 5


class TrainService:
    """
    Provides Mumbai Central Line SLOW LOCAL train times only.

    Key guarantees:
      • No Fast Local is ever recommended (Vidyavihar is not a Fast Local stop).
      • Only Slow Local trains are used.
      • Times are hardcoded for reliability (no live API dependency).
    """

    def __init__(self):
        self.schedule = self._build_schedule()

    # ------------------------------------------------------------------
    def _build_schedule(self) -> list[dict]:
        """
        Expand the raw Thane-anchored timetable into a list of dicts.
        Each entry has departure/arrival times as datetime.time objects
        plus pre-computed duration.
        """
        schedule = []
        for thane_dep_str, vv_arr_str in _SLOW_LOCAL_THANE_TO_VV:
            thane_dep = datetime.strptime(thane_dep_str, "%H:%M").time()
            vv_arr    = datetime.strptime(vv_arr_str,  "%H:%M").time()
            duration  = int(
                (datetime.combine(datetime.min.date(), vv_arr) -
                 datetime.combine(datetime.min.date(), thane_dep)).total_seconds() / 60
            )
            schedule.append({
                "thane_dep":  thane_dep,
                "thane_dep_str": thane_dep_str,
                "vv_arr":     vv_arr,
                "vv_arr_str": vv_arr_str,
                "duration_thane_to_vv": duration,   # minutes
            })
        return schedule

    # ------------------------------------------------------------------
    def get_best_train_for_arrival(
        self,
        origin_station: str,
        desired_arrival_time_str: str,
    ) -> dict | None:
        """
        Find the LATEST Slow Local that arrives at Vidyavihar at least
        ARRIVAL_BUFFER_MINS before desired_arrival_time_str.

        Returns a dict describing the train, or None if no train qualifies.

        The returned dict contains:
          train_id          – unique ID (e.g. "SL0715")
          type              – always "Slow Local"
          departure         – departure from origin_station "HH:MM"
          departure_thane   – departure from Thane "HH:MM"
          arrival_vidyavihar– arrival at Vidyavihar "HH:MM"
          duration_mins     – origin_station → Vidyavihar travel time (mins)
          interchange_buffer_mins – extra buffer for Trans-Harbour interchange (if any)
        """
        arrival_dt = datetime.combine(
            datetime.today().date(),
            datetime.strptime(desired_arrival_time_str, "%H:%M").time(),
        )
        # Latest acceptable Vidyavihar arrival (5 min safety buffer)
        latest_vv_arr_dt = arrival_dt - timedelta(minutes=ARRIVAL_BUFFER_MINS)

        # Offset from Thane for origin station
        origin_offset = _OFFSET_FROM_THANE.get(origin_station)
        if origin_offset is None:
            logger.warning(
                "Station '%s' not in offset table — defaulting to Thane (offset 0).",
                origin_station,
            )
            origin_offset = 0
            origin_station_used = "Thane"
        else:
            origin_station_used = origin_station

        # Does this origin require a Trans-Harbour interchange at Thane?
        interchange_buffer = 7 if origin_station in _TRANS_HARBOUR else None

        best = None

        for entry in self.schedule:
            # Compute Vidyavihar arrival as a full datetime for comparison
            vv_arr_dt = datetime.combine(datetime.today().date(), entry["vv_arr"])

            if vv_arr_dt > latest_vv_arr_dt:
                # This train arrives too late (or exactly ON the boundary with
                # no buffer left) — skip it and all subsequent trains.
                break

            # Compute departure from origin station
            # origin_offset > 0  → station is BEFORE Thane, so depart earlier
            # origin_offset < 0  → station is AFTER  Thane, so depart later
            thane_dep_dt = datetime.combine(
                datetime.today().date(), entry["thane_dep"]
            )
            origin_dep_dt = thane_dep_dt - timedelta(minutes=origin_offset)

            duration_origin_to_vv = int(
                (vv_arr_dt - origin_dep_dt).total_seconds() / 60
            )

            best = {
                "train_id":             f"SL{entry['thane_dep_str'].replace(':', '')}",
                "type":                 "Slow Local",
                "departure":            origin_dep_dt.strftime("%H:%M"),
                "departure_thane":      entry["thane_dep_str"],
                "arrival_vidyavihar":   entry["vv_arr_str"],
                "duration_mins":        duration_origin_to_vv,
            }
            if interchange_buffer is not None:
                best["interchange_buffer_mins"] = interchange_buffer

        return best  # None if no train qualifies

    # ------------------------------------------------------------------
    def get_next_trains(
        self,
        source: str,
        destination: str,
        after_time_str: str = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Return upcoming Slow Local trains from source → destination after
        after_time_str, up to `limit` results.

        Only southbound (toward Vidyavihar / CSMT) journeys are supported
        in this timetable because Vidyavihar is the fixed destination.
        """
        query_time = (
            datetime.strptime(after_time_str, "%H:%M").time()
            if after_time_str
            else datetime.now().time()
        )

        src_offset  = _OFFSET_FROM_THANE.get(source, 0)
        dest_offset = _OFFSET_FROM_THANE.get(destination, DEST_OFFSET)
        interchange_buffer = 7 if source in _TRANS_HARBOUR else None

        results = []

        # Southbound: source is NORTH of destination (larger offset value)
        if src_offset > dest_offset:
            for entry in self.schedule:
                thane_dep_dt = datetime.combine(
                    datetime.today().date(), entry["thane_dep"]
                )
                origin_dep_dt = thane_dep_dt - timedelta(minutes=src_offset)
                vv_arr_dt     = datetime.combine(
                    datetime.today().date(), entry["vv_arr"]
                )

                if origin_dep_dt.time() >= query_time:
                    duration = int(
                        (vv_arr_dt - origin_dep_dt).total_seconds() / 60
                    )
                    item = {
                        "train_id":   f"SL{entry['thane_dep_str'].replace(':', '')}",
                        "type":       "Slow Local",
                        "departure":  origin_dep_dt.strftime("%H:%M"),
                        "arrival":    entry["vv_arr_str"],
                        "duration_mins": duration,
                    }
                    if interchange_buffer is not None:
                        item["interchange_buffer_mins"] = interchange_buffer
                    results.append(item)
                    if len(results) >= limit:
                        break

        # Northbound: source is SOUTH of destination (smaller offset value)
        elif src_offset < dest_offset:
            for entry in self.schedule:
                vv_arr_dt = datetime.combine(
                    datetime.today().date(), entry["vv_arr"]
                )
                travel_time   = src_offset - dest_offset   # negative → positive
                origin_dep_dt = vv_arr_dt - timedelta(minutes=travel_time)

                if origin_dep_dt.time() >= query_time:
                    duration = int(
                        (vv_arr_dt - origin_dep_dt).total_seconds() / 60
                    )
                    item = {
                        "train_id":   f"SLN{entry['vv_arr_str'].replace(':', '')}",
                        "type":       "Slow Local",
                        "departure":  origin_dep_dt.strftime("%H:%M"),
                        "arrival":    entry["vv_arr_str"],
                        "duration_mins": duration,
                    }
                    if interchange_buffer is not None:
                        item["interchange_buffer_mins"] = interchange_buffer
                    results.append(item)
                    if len(results) >= limit:
                        break

        return results
