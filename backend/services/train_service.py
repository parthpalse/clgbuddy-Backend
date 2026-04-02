from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class TrainService:
    def __init__(self):
        # Offsets in minutes relative to Thane (Positive = before Thane, Negative = after Thane)
        self.offsets_to_thane = {
            'Kalyan': 25,
            'Thakurli': 20,
            'Dombivli': 13,
            'Kopar': 10,
            'Diva': 8,
            'Mumbra': 5,
            'Kalwa': 3,
            'Thane': 0,
            'Mulund': -4,
            'Nahur': -7,
            'Bhandup': -10,
            'Kanjurmarg': -12,
            'Vikhroli': -15,
            'Ghatkopar': -18,
            'Vidyavihar': -22,
            'Kurla': -25,
            'Sion': -28,
            'Dadar': -34,
            'CSMT': -45
        }
        
        self.thane_schedule = self._generate_thane_vidyavihar_schedule()

    def _generate_thane_vidyavihar_schedule(self):
        # Hardcode realistic slow local timetable for Thane -> Vidyavihar (every ~15-20 mins)
        schedule = []
        base = datetime(2000, 1, 1, 6, 0)
        end = datetime(2000, 1, 1, 10, 0)
        
        current = base
        while current <= end:
            v_arr = current + timedelta(minutes=22) # Thane to Vidyavihar takes ~22 mins for Slow Local
            schedule.append({
                'departure_thane': current.strftime('%H:%M'),
                'arrival_vidyavihar': v_arr.strftime('%H:%M'),
                'type': 'Slow'
            })
            current += timedelta(minutes=15) # Roughly 15 mins gap
        return schedule

    def get_next_trains(self, source: str, destination: str, after_time_str: str = None, limit: int = 50):
        if after_time_str:
            query_time = datetime.strptime(after_time_str, '%H:%M').time()
        else:
            query_time = datetime.now().time()
            
        source_offset = self.offsets_to_thane.get(source, 0) # Defaults to 0 if not found
        destination_offset = self.offsets_to_thane.get(destination, -22) # Vidyavihar is -22 from Thane
        
        results = []
        for t in self.thane_schedule:
            thane_dept_t = datetime.strptime(t['departure_thane'], '%H:%M')
            thane_dept_dt = datetime.combine(datetime.today(), thane_dept_t.time())
            
            # If user is at a station before Thane, they leave earlier. 
            # E.g. Kalyan (+25 mins to Thane), so they depart 25 mins before the Thane departure time
            source_dept_dt = thane_dept_dt - timedelta(minutes=source_offset)
            
            # Arrival time at destination (which should be Vidyavihar)
            thane_arr_dt = datetime.combine(datetime.today(), datetime.strptime(t['arrival_vidyavihar'], '%H:%M').time())
            # For correctness if destination is NOT Vidyavihar, though the prompt implies it always is
            # Vidyavihar offset is -22, so (destination_offset - (-22)) adjusts it
            arr_dt = thane_arr_dt + timedelta(minutes=-(destination_offset - (-22)))

            if source_dept_dt.time() >= query_time:
                duration = int((arr_dt - source_dept_dt).total_seconds() / 60)
                results.append({
                    'train_id': "S" + t['departure_thane'].replace(':', ''),
                    'type': t['type'],
                    'departure': source_dept_dt.strftime('%H:%M'),
                    'arrival': arr_dt.strftime('%H:%M'),
                    'duration_mins': duration
                })
                
        return results

