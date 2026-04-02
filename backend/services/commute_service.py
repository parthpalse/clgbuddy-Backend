from datetime import datetime, timedelta
import logging

from services.traffic_service import TrafficService, VIDYAVIHAR_TO_KJSCE_WALK_MINS
from services.train_service import TrainService
from config import Config

logger = logging.getLogger(__name__)


class CommuteService:
    """
    Calculates road-only vs hybrid (road + train) commute options.

    Destination is always KJSCE Vidyavihar (hardcoded via Config).
    Leg structure:
        Leg 1 — Home  → Origin station       (road, live ORS)
        Leg 2 — Origin station → Vidyavihar   (train + delay buffer)
        Leg 3 — Vidyavihar → KJSCE gate       (road, live ORS)
        Road  — Home  → KJSCE                 (direct drive, live ORS)
    """

    DESTINATION = Config.KJSCE_ADDRESS        # "KJSCE, Vidyavihar West, Mumbai..."
    DEST_STATION = Config.KJSCE_STATION       # "Vidyavihar"

    # Keyword → nearest Central Line station
    STATION_MAP = {
        # Central Line
        'thane':      'Thane',
        'mulund':     'Thane',
        'dombivli':   'Dombivli',
        'kalyan':     'Kalyan',
        'ghatkopar':  'Ghatkopar',
        'kurla':      'Kurla',
        'dadar':      'Dadar',
        'csmt':       'CSMT',
        'fort':       'CSMT',
        'vidyavihar': 'Vidyavihar',

        # Trans-Harbour Line
        'airoli':        'Thane',
        'rabale':        'Thane',
        'ghansoli':      'Thane',
        'koparkhairane': 'Thane',
        'turbhe':        'Thane',
        'vashi':         'Kurla', # Faster via Harbour -> Kurla than Thane

        # Harbour Line (Maps mostly to Kurla)
        'panvel':     'Kurla',
        'nerul':      'Kurla',
        'sanpada':    'Kurla',
        'mankhurd':   'Kurla',
        'govandi':    'Kurla',
        'chembur':    'Kurla',
        'chunabhatti':'Kurla',
        'wadala':     'Kurla',

        # Western Line (Maps to Dadar)
        'churchgate': 'Dadar',
        'marine lines': 'Dadar',
        'charni road': 'Dadar',
        'grant road': 'Dadar',
        'mumbai central': 'Dadar',
        'mahalaxmi':  'Dadar',
        'lower parel': 'Dadar',
        'prabhadevi': 'Dadar',
        'matunga road':'Dadar',
        'mahim':      'Dadar',
        'bandra':     'Dadar',
        'khar':       'Dadar',
        'santacruz':  'Dadar',
        'vile parle': 'Dadar',
        'andheri':    'Dadar',
        'jogeshwari': 'Dadar',
        'goregaon':   'Dadar',
        'malad':      'Dadar',
        'kandivali':  'Dadar',
        'borivali':   'Dadar',
        'dahisar':    'Dadar',
        'mira road':  'Dadar',
        'bhayandar':  'Dadar',
        'vasai':      'Dadar',
        'virar':      'Dadar',
    }

    def __init__(self):
        self.traffic = TrafficService()
        self.trains  = TrainService()

    # ------------------------------------------------------------------
    def calculate_best_route(self, origin: str, arrival_time_str: str,
                             delay_buffer_mins: int = 0):
        """
        Returns a dict with road_route, train_route, and recommendation.

        :param origin:            Free-text home address
        :param arrival_time_str:  "HH:MM" — desired arrival at KJSCE
        :param delay_buffer_mins: Extra buffer added to train leg for expected delays
        """
        arrival_dt = datetime.combine(
            datetime.now().date(),
            datetime.strptime(arrival_time_str, '%H:%M').time()
        )

        # FIX: Clamp delay_buffer_mins to [0, 60].
        # WHY: A corrupt or malicious value (e.g. 9999 or -30) would push
        #      the departure time into the previous day or skip all trains.
        #      60 minutes is a generous upper bound for Mumbai local delays.
        delay_buffer_mins = max(0, min(60, delay_buffer_mins))

        # ── Road-only route ──────────────────────────────────────────
        road_trip = self.traffic.get_travel_time(origin, self.DESTINATION)
        if 'error' in road_trip:
            raise Exception(f"Road routing failed: {road_trip['error']}")
            
        road_mins       = road_trip['duration_seconds'] / 60
        road_depart_dt  = arrival_dt - timedelta(minutes=road_mins)

        road_route = {
            'mode':               'Road Only',
            'leave_at':           road_depart_dt.strftime('%H:%M'),
            'total_duration_mins': int(road_mins),
            'details': {
                'summary':  f"Drive directly ({road_trip['distance_text']})",
                'duration': road_trip['duration_text'],
            },
        }

        # ── Hybrid route (road + train) ──────────────────────────────
        origin_station = self._nearest_station(origin)
        train_route    = None

        if origin_station and origin_station != self.DEST_STATION:
            leg1 = self.traffic.get_travel_time(
                origin, f"{origin_station} Railway Station, Mumbai"
            )
            if 'error' in leg1:
                raise Exception(f"Leg1 road routing failed: {leg1['error']}")
            
            leg1_mins = leg1['duration_seconds'] / 60

            leg3_mins = VIDYAVIHAR_TO_KJSCE_WALK_MINS  # fixed walk: Vidyavihar stn → KJSCE gate

            # Latest the train can arrive at Vidyavihar
            # (subtract walking leg + delay buffer already baked into buffer)
            train_must_arrive_by = arrival_dt - timedelta(minutes=leg3_mins)

            # Find the latest suitable train (arrives before deadline)
            # We search trains from early morning and pick the last valid one
            trains = self.trains.get_next_trains(
                origin_station, self.DEST_STATION,
                after_time_str='04:00',
                limit=200,
            )

            best_train = None
            for train in trains:
                arr_t  = datetime.strptime(train['arrival'], '%H:%M').time()
                arr_dt = datetime.combine(datetime.now().date(), arr_t)
                # Add predicted delay buffer to train arrival
                effective_arr_dt = arr_dt + timedelta(minutes=delay_buffer_mins)
                if effective_arr_dt <= train_must_arrive_by:
                    best_train = train   # keep updating — last valid wins
                # trains are sorted ascending; once they're past deadline, done
                elif arr_dt > train_must_arrive_by:
                    break

            if best_train:
                dept_t  = datetime.strptime(best_train['departure'], '%H:%M').time()
                dept_dt = datetime.combine(datetime.now().date(), dept_t)

                # Leave home early enough to catch the train
                home_depart_dt = dept_dt - timedelta(minutes=leg1_mins)

                # Total journey from home to KJSCE gate
                total_mins = int(
                    (arrival_dt - home_depart_dt).total_seconds() / 60
                )

                train_route = {
                    'mode':               'Hybrid (Road + Train)',
                    'leave_at':           home_depart_dt.strftime('%H:%M'),
                    'total_duration_mins': total_mins,
                    'delay_buffer_mins':  delay_buffer_mins,
                    'details': {
                        'leg1_road':  (
                            f"Home → {origin_station} Station "
                            f"({int(leg1_mins)} mins)"
                        ),
                        'leg2_train': (
                            f"{best_train['type']} train "
                            f"{origin_station} → {self.DEST_STATION} "
                            f"({best_train['departure']} – {best_train['arrival']})"
                            + (f" + {delay_buffer_mins} min delay buffer"
                               if delay_buffer_mins else '')
                        ),
                        'leg3_walk':  (
                            f"Vidyavihar Station → KJSCE gate "
                            f"({int(leg3_mins)} mins)"
                        ),
                    },
                }

        # ── Pick recommendation ───────────────────────────────────────
        if train_route:
            recommend = (
                'Train'
                if train_route['total_duration_mins'] < road_route['total_duration_mins']
                else 'Road'
            )
        else:
            recommend = 'Road'

        return {
            'road_route':     road_route,
            'train_route':    train_route,   # may be None
            'recommendation': recommend,
        }

    # ------------------------------------------------------------------
    def _nearest_station(self, location: str) -> str:
        loc_lower = location.lower()
        for keyword, station in self.STATION_MAP.items():
            if keyword in loc_lower:
                return station
        return 'Thane'   # sensible Mumbai default
