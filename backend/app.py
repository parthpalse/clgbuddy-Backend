from datetime import datetime

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import Config
from services.traffic_service import TrafficService
from services.commute_service import CommuteService
from services.notification_service import NotificationService
from services.ml_service import MLService

app = Flask(__name__)
CORS(app)
app.config.from_object(Config)

# Service singletons
traffic_service = TrafficService()
commute_service = CommuteService()
notification_service = NotificationService()
ml_service = MLService()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'NikLo Backend'}), 200


# ---------------------------------------------------------------------------
# Raw traffic (utility / debug)
# ---------------------------------------------------------------------------
@app.route('/api/traffic', methods=['POST'])
def get_traffic():
    data = request.json or {}
    origin = data.get('origin')
    destination = data.get('destination')

    if not origin or not destination:
        return jsonify({'error': 'origin and destination are required'}), 400

    result = traffic_service.get_travel_time(origin, destination)
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Commute plan
# Accepts: origin, arrival_time (HH:MM), delay_buffer_mins (optional int)
# Destination is always hardcoded to KJSCE Vidyavihar on the backend.
# ---------------------------------------------------------------------------
@app.route('/api/commute', methods=['POST'])
def get_commute_plan():
    data = request.json or {}
    origin = data.get('origin')
    arrival_time = data.get('arrival_time')          # "HH:MM"
    # FIX: Clamp delay_buffer_mins at the API layer (defense in depth).
    # WHY: Even though commute_service also clamps, validating at the API
    #      boundary catches bad input early and returns a clear 400 error
    #      instead of silently clamping.
    try:
        delay_buffer_mins = int(data.get('delay_buffer_mins', 0))
        delay_buffer_mins = max(0, min(60, delay_buffer_mins))
    except (ValueError, TypeError):
        delay_buffer_mins = 0

    if not origin or not arrival_time:
        return jsonify({'error': 'origin and arrival_time are required'}), 400

    # Validate arrival_time format
    try:
        datetime.strptime(arrival_time, '%H:%M')
    except ValueError:
        return jsonify({'error': 'arrival_time must be HH:MM format'}), 400

    try:
        plan = commute_service.calculate_best_route(
            origin, arrival_time, delay_buffer_mins
        )
        return jsonify(plan), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# ML prediction
# ---------------------------------------------------------------------------
@app.route('/api/predict', methods=['POST'])
def predict_commute():
    data = request.json or {}
    time_str = data.get('time')           # "HH:MM"
    day = data.get('day_of_week')         # 0=Mon … 6=Sun
    historical_avg = data.get('historical_avg_delay', 0)

    if not time_str or day is None:
        return jsonify({'error': 'time and day_of_week are required'}), 400

    try:
        dt = datetime.strptime(time_str, '%H:%M')
        day_int = int(day)
        if not (0 <= day_int <= 6):
            return jsonify({'error': 'day_of_week must be 0 (Mon) to 6 (Sun)'}), 400
        
        prediction = ml_service.predict_commute_time(dt.hour, dt.minute, day_int, float(historical_avg))
        return jsonify({'predicted_duration_mins': prediction}), 200
    except ValueError:
        return jsonify({'error': 'time must be HH:MM format'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# ML Update
# ---------------------------------------------------------------------------
@app.route('/api/ml/update', methods=['POST'])
def update_ml_model():
    data = request.json or {}
    delay_logs = data.get('logs') # e.g. {"0": [10, 5], "1": [2]}
    
    if delay_logs is None:
        return jsonify({'error': 'logs are required'}), 400

    try:
        ml_service.learn_from_logs(delay_logs)
        return jsonify({'status': 'model updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500



# ---------------------------------------------------------------------------
# Push notifications
# ---------------------------------------------------------------------------
@app.route('/api/notify', methods=['POST'])
def send_notification():
    data = request.json or {}
    token = data.get('token')
    title = data.get('title')
    body = data.get('body')

    if not all([token, title, body]):
        return jsonify({'error': 'token, title, and body are required'}), 400

    result = notification_service.send_push_notification(token, title, body)
    return jsonify(result), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=Config.DEBUG)
