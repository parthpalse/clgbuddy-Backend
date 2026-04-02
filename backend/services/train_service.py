from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class TrainService:
    def __init__(self):
        # Offsets in minutes relative to Thane (Positive = before Thane, Negative = after Thane)
        self.offsets_to_thane = {
            'Kalyan': 35, 'Thakurli': 28, 'Dombivli': 22, 'Kopar': 18, 'Diva': 14, 'Mumbra': 10,
            'Kalwa': 5, 'Thane': 0, 'Mulund': -5, 'Nahur': -8, 'Bhandup': -11, 'Kanjurmarg': -14,
            'Vikhroli': -17, 'Ghatkopar': -18, 'Vidyavihar': -22, 'Kurla': -25, 'Sion': -28,
            'Dadar': -34, 'CSMT': -45
        }
        
        self.trans_harbour = {
            'Ghansoli', 'Airoli', 'Rabale', 'Koparkhairane', 'Turbhe', 'Vashi', 
            'Sanpada', 'Nerul', 'Belapur', 'Panvel'
        }
        
        self.thane_schedule = self._generate_thane_schedule()

    def _generate_thane_schedule(self):
        # Anchor: Thane departure, 07:15 to 11:00
        schedule = []
        base_date = datetime(2000, 1, 1)
        current = base_date.replace(hour=7, minute=15)
        end = base_date.replace(hour=11, minute=0)
        
        while current <= end:
            v_arr = current + timedelta(minutes=22)
            schedule.append({
                'departure_thane': current.strftime('%H:%M'),
                'arrival_vidyavihar': v_arr.strftime('%H:%M'),
                'type': 'Slow'
            })
            if current.time() < datetime(2000, 1, 1, 9, 30).time():
                current += timedelta(minutes=10)
            else:
                current += timedelta(minutes=15)
        return schedule

    def get_next_trains(self, source: str, destination: str, after_time_str: str = None, limit: int = 50):
        if after_time_str:
            query_time = datetime.strptime(after_time_str, '%H:%M').time()
        else:
            query_time = datetime.now().time()
            
        s_offset = self.offsets_to_thane.get(source, 0)
        d_offset = self.offsets_to_thane.get(destination, -22)
        
        interchange = 7 if source in self.trans_harbour else None
        
        results = []
        
        # User is NORTH of Vidyavihar (e.g. Thane=0 > Vidyavihar=-22), needs CSMT-bound train
        if s_offset > d_offset:
            for t in self.thane_schedule:
                thane_dept_t = datetime.strptime(t['departure_thane'], '%H:%M')
                thane_dept_dt = datetime.combine(datetime.today(), thane_dept_t.time())
                
                source_dept_dt = thane_dept_dt - timedelta(minutes=s_offset)
                arr_dt = datetime.combine(datetime.today(), datetime.strptime(t['arrival_vidyavihar'], '%H:%M').time())

                if source_dept_dt.time() >= query_time:
                    duration = int((arr_dt - source_dept_dt).total_seconds() / 60)
                    item = {
                        'train_id': "S" + t['departure_thane'].replace(':', ''),
                        'type': t['type'],
                        'departure': source_dept_dt.strftime('%H:%M'),
                        'arrival': arr_dt.strftime('%H:%M'),
                        'duration_mins': duration
                    }
                    if interchange is not None:
                        item['interchange_buffer_mins'] = interchange
                    results.append(item)
                    
        # User is SOUTH of Vidyavihar (e.g. Kurla=-25 < Vidyavihar=-22), needs KALYAN-BOUND (northbound)
        elif s_offset < d_offset:
            for t in self.thane_schedule:
                arr_vid = datetime.combine(datetime.today(), datetime.strptime(t['arrival_vidyavihar'], '%H:%M').time())
                
                # source_departure = vidyavihar_arrival_time - (source_offset - (-22)) minutes
                travel_time = s_offset - d_offset
                source_dept_dt = arr_vid - timedelta(minutes=travel_time)
                
                if source_dept_dt.time() >= query_time:
                    duration_mins = int((arr_vid - source_dept_dt).total_seconds() / 60)
                    item = {
                        'train_id': "N" + t['arrival_vidyavihar'].replace(':', ''),
                        'type': t['type'],
                        'departure': source_dept_dt.strftime('%H:%M'),
                        'arrival': t['arrival_vidyavihar'],
                        'duration_mins': duration_mins
                    }
                    if interchange is not None:
                        item['interchange_buffer_mins'] = interchange
                    results.append(item)
                
        return results

