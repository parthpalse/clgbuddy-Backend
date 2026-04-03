import React, { useState, useEffect, useCallback } from 'react';
import {
  StyleSheet, Text, View, TextInput, TouchableOpacity,
  ScrollView, ActivityIndicator, Alert, SafeAreaView, KeyboardAvoidingView, Platform,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Location from 'expo-location';
import { API_URL } from './config';

// ─── Storage keys ────────────────────────────────────────────────────────────
const KEY_PROFILE = 'niklo_profile';       // { home, station, walk_mins, arrival_time }
const KEY_DELAY_LOG = 'niklo_delay_log';     // { 0:[10,8,…], 1:[…], … }  (Mon=0 … Sun=6)
const MAX_DELAY_ENTRIES = 4;                  // keep last 4 per day

// ─── Helpers ─────────────────────────────────────────────────────────────────
// FIX: Extended timeout from 60s → 90s for Render free tier cold starts.
// WHY: Render free tier sleeps after 15 min inactivity. Cold start takes ~30s
//      to spin up Python + install deps. 60s was too tight — users saw
//      "Timed Out" on first tap after waking the server.
const TIMEOUT_MS = 90_000;

async function postJSON(url, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

function avgDelay(log, day) {
  const entries = (log[day] || []);
  if (!entries.length) return 0;
  const sum = entries.reduce((a, b) => a + b, 0);
  return Math.round(sum / entries.length);
}

function dayOfWeekMon0() {
  // JS Sunday=0 → convert to Mon=0 … Sun=6
  const d = new Date().getDay();
  return d === 0 ? 6 : d - 1;
}

// ─── Screens ─────────────────────────────────────────────────────────────────

// Nominatim reverse-geocode URL (free, no API key)
const NOMINATIM_REVERSE = 'https://nominatim.openstreetmap.org/reverse';

/** First-launch setup — collects home address, nearest station, walk time, arrival time. */
function SetupScreen({ onSave }) {
  const [home, setHome] = useState('');
  const [station, setStation] = useState('Thane');
  const [walkMins, setWalkMins] = useState('5');
  const [arrival, setArrival] = useState('09:00');
  const [saving, setSaving] = useState(false);
  const [locLoading, setLocLoading] = useState(false);

  const ARRIVAL_OPTS = [
    { label: '9:00 AM', val: '09:00' },
    { label: '9:30 AM', val: '09:30' },
    { label: '10:00 AM', val: '10:00' },
    { label: '10:30 AM', val: '10:30' },
    { label: '11:00 AM', val: '11:00' },
  ];

  /**
   * "📍 Use My Location" handler.
   * 1. Requests expo-location foreground permission.
   * 2. Gets current GPS coords.
   * 3. Reverse-geocodes via Nominatim (free, no API key) to get a human address.
   * 4. Auto-fills the Home Address field.
   * Shows a spinner while in progress.
   * Shows a helpful Alert if permission is denied.
   */
  const useMyLocation = async () => {
    setLocLoading(true);
    try {
      // Step 1: Request permission
      const { status } = await Location.requestForegroundPermissionsAsync();

      if (status !== 'granted') {
        Alert.alert(
          '📍 Location Permission Denied',
          'ClgBuddy needs your location to auto-fill your home address.\n\n'
          + 'To enable it:\n'
          + '1. Open your phone Settings\n'
          + '2. Find ClgBuddy (or Expo Go)\n'
          + '3. Tap Permissions → Location → Allow\n\n'
          + 'Or just type your address manually below.',
          [{ text: 'OK' }]
        );
        return;
      }

      // Step 2: Get GPS coordinates
      const loc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      const { latitude, longitude } = loc.coords;

      // Step 3: Reverse-geocode via Nominatim (free, no API key needed)
      const nomUrl =
        `${NOMINATIM_REVERSE}?lat=${latitude}&lon=${longitude}`
        + `&format=json&addressdetails=1`;
      const resp = await fetch(nomUrl, {
        headers: { 'User-Agent': 'ClgBuddyApp/1.0 (student project)' },
      });

      if (!resp.ok) {
        throw new Error(`Nominatim returned HTTP ${resp.status}`);
      }

      const data = await resp.json();

      // Build a concise address from structured address components
      const addr = data.address || {};
      const parts = [
        addr.road || addr.pedestrian || addr.footway,
        addr.suburb || addr.neighbourhood || addr.quarter,
        addr.city || addr.town || addr.village || addr.county,
        addr.state,
      ].filter(Boolean);

      const displayAddr =
        parts.length > 0 ? parts.join(', ') : (data.display_name || '');

      if (!displayAddr) {
        throw new Error('No address returned from Nominatim');
      }

      // Step 4: Auto-fill the home address field
      setHome(displayAddr);
    } catch (err) {
      Alert.alert(
        'Location Error',
        `Could not determine your location: ${err.message}\n\nPlease type your address manually.`,
        [{ text: 'OK' }]
      );
    } finally {
      setLocLoading(false);
    }
  };

  const save = async () => {
    if (!home.trim() || !station.trim() || !arrival.trim()) {
      Alert.alert('Missing', 'Please fill in all fields.');
      return;
    }
    if (!/^\d{2}:\d{2}$/.test(arrival)) {
      Alert.alert('Format', 'Arrival time must be HH:MM (e.g. 09:00).');
      return;
    }
    setSaving(true);
    const profile = {
      home: home.trim(),
      station: station.trim(),
      walk_mins: parseInt(walkMins) || 5,
      arrival_time: arrival.trim(),
    };
    await AsyncStorage.setItem(KEY_PROFILE, JSON.stringify(profile));
    onSave(profile);
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.setupScroll}>
        <Text style={styles.header}>ClgBuddy 🚆</Text>
        <Text style={styles.subHeader}>Set up once — we remember forever</Text>

        <View style={styles.card}>
          <Text style={styles.label}>🏠 Home Address</Text>

          {/* 📍 Use My Location button */}
          <TouchableOpacity
            style={[styles.locButton, locLoading && styles.locButtonDisabled]}
            onPress={useMyLocation}
            disabled={locLoading}
          >
            {locLoading ? (
              <View style={styles.locButtonInner}>
                <ActivityIndicator color="#007AFF" size="small" />
                <Text style={styles.locButtonText}>  Fetching location…</Text>
              </View>
            ) : (
              <Text style={styles.locButtonText}>📍 Use My Location</Text>
            )}
          </TouchableOpacity>

          <TextInput
            style={styles.input}
            value={home}
            onChangeText={setHome}
            placeholder="e.g. Thane West, near Upvan Lake"
          />

          <Text style={styles.label}>🚉 Nearest Railway Station</Text>
          <TextInput
            style={styles.input}
            value={station}
            onChangeText={setStation}
            placeholder="e.g. Thane"
          />

          <Text style={styles.label}>🚶 Walk time: Station → KJSCE gate (mins)</Text>
          <TextInput
            style={styles.input}
            value={walkMins}
            onChangeText={setWalkMins}
            placeholder="5"
            keyboardType="number-pad"
          />

          <Text style={styles.label}>🎯 Desired arrival time at KJSCE</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.pillContainer}>
            {ARRIVAL_OPTS.map((opt) => (
              <TouchableOpacity
                key={opt.val}
                style={[styles.pill, arrival === opt.val && styles.pillActive]}
                onPress={() => setArrival(opt.val)}
              >
                <Text style={[styles.pillText, arrival === opt.val && styles.pillTextActive]}>
                  {opt.label}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          <TouchableOpacity style={styles.button} onPress={save} disabled={saving}>
            {saving
              ? <ActivityIndicator color="#fff" />
              : <Text style={styles.buttonText}>Save & Continue →</Text>}
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

/** Main commute screen — calculates and shows the best route. */
function MainScreen({ profile, onReset }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [delayLog, setDelayLog] = useState({});
  const [logDelay, setLogDelay] = useState('');   // text input for logging actual delay
  const [logging, setLogging] = useState(false);

  const day = dayOfWeekMon0();

  // Load delay log on mount
  useEffect(() => {
    AsyncStorage.getItem(KEY_DELAY_LOG).then(raw => {
      if (raw) setDelayLog(JSON.parse(raw));
    });

    // FIX: Warm-up ping to /health on screen mount.
    // WHY: Render free tier sleeps after 15 min inactivity. This fires a
    //      lightweight GET to /health as soon as the user opens the app,
    //      so the server is already awake by the time they tap "Calculate".
    //      We don't await it or show errors — it's a silent background ping.
    fetch(`${API_URL}/health`, { method: 'GET' }).catch(() => { });
  }, []);

  const predictedDelay = avgDelay(delayLog, day);

  const calculate = useCallback(async () => {
    setLoading(true);
    setResult(null);
    try {
      // Fire both requests in parallel using Promise.all
      const [plan, predictionReq] = await Promise.all([
        postJSON(`${API_URL}/api/commute`, {
          origin: profile.home,
          arrival_time: profile.arrival_time,
          delay_buffer_mins: predictedDelay,
        }),
        postJSON(`${API_URL}/api/predict`, {
          time: profile.arrival_time,
          day_of_week: day,
        }).catch(err => null)
      ]);

      const prediction = predictionReq ? predictionReq.predicted_duration_mins : null;
      setResult({ ...plan, prediction });
    } catch (err) {
      if (err.name === 'AbortError') {
        // FIX: More helpful timeout message for cold starts.
        // WHY: Users don't know what "cold start" means. This message tells
        //      them to wait and retry, instead of thinking the app is broken.
        Alert.alert(
          'Server Waking Up ☕',
          'The server was sleeping (free tier). It\'s booting now — please wait 10 seconds and tap Calculate again.'
        );
      } else {
        Alert.alert('Error', 'Could not fetch commute plan. Is the backend running?');
      }
    } finally {
      setLoading(false);
    }
  }, [profile, predictedDelay, day]);

  const saveDelay = async () => {
    const mins = parseInt(logDelay);
    if (isNaN(mins) || mins < 0 || mins > 120) {
      Alert.alert('Invalid', 'Enter a delay in minutes (0–120).');
      return;
    }
    setLogging(true);
    const updated = { ...delayLog };
    const existing = updated[day] || [];
    updated[day] = [...existing, mins].slice(-MAX_DELAY_ENTRIES); // keep last 4
    await AsyncStorage.setItem(KEY_DELAY_LOG, JSON.stringify(updated));
    setDelayLog(updated);
    setLogDelay('');
    setLogging(false);
    Alert.alert('Saved!', `Logged ${mins} min delay for today. New average: ${avgDelay(updated, day)} mins.`);
  };

  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  return (
    <ScrollView contentContainerStyle={styles.mainScroll}>
      {/* Header */}
      <Text style={styles.header}>NikLo 🚆</Text>
      <Text style={styles.subHeader}>Home → KJSCE Vidyavihar</Text>

      {/* Profile summary */}
      <View style={styles.profileBar}>
        <Text style={styles.profileText}>🏠 {profile.home}</Text>
        <Text style={styles.profileText}>🚉 {profile.station} · ⏰ Arrive {profile.arrival_time}</Text>
        <TouchableOpacity onPress={onReset}>
          <Text style={styles.editLink}>Edit profile</Text>
        </TouchableOpacity>
      </View>

      {/* Delay badge */}
      <View style={[styles.delayBadge, predictedDelay > 0 ? styles.delayBadgeActive : {}]}>
        <Text style={styles.delayText}>
          {predictedDelay > 0
            ? `⚠️ ${DAY_NAMES[day]} usually runs ${predictedDelay} min late — buffer added`
            : `✅ No usual delay recorded for ${DAY_NAMES[day]}s`}
        </Text>
      </View>

      {/* Calculate button */}
      <TouchableOpacity style={styles.button} onPress={calculate} disabled={loading}>
        {loading
          ? <ActivityIndicator color="#fff" />
          : <Text style={styles.buttonText}>Calculate My Commute</Text>}
      </TouchableOpacity>

      {/* Results */}
      {result && (
        <View style={{ marginTop: 24 }}>
          {result.prediction != null && (
            <View style={styles.mlBadge}>
              <Text style={styles.mlText}>🔮 ML estimate: ~{Math.round(result.prediction)} mins total</Text>
            </View>
          )}

          <Text style={styles.recommendText}>
            Recommended: {result.recommendation === 'Train' ? '🚆 Train' : '🚗 Road'}
          </Text>

          {/* Train route card — only render if train_route !== null */}
          {result.train_route !== null ? (
            <View style={[styles.routeCard, result.recommendation === 'Train' && styles.winnerCard]}>
              <Text style={styles.cardTitle}>🚆 Train Route</Text>
              <Text style={styles.leaveAt}>Leave by {result.train_route.leave_at}</Text>
              <Text style={styles.info}>{result.train_route.details.leg1_road}</Text>
              <Text style={styles.info}>{result.train_route.details.leg2_train}</Text>
              <Text style={styles.info}>{result.train_route.details.leg3_walk}</Text>
              <Text style={styles.duration}>Total: {result.train_route.total_duration_mins} mins</Text>
            </View>
          ) : (
            <View style={styles.routeCard}>
              <Text style={styles.cardTitle}>🚆 Train Route</Text>
              <Text style={styles.info}>No feasible train found for this timing.</Text>
            </View>
          )}

          {/* Road route card */}
          <View style={[styles.routeCard, result.recommendation === 'Road' && styles.winnerCard]}>
            <Text style={styles.cardTitle}>🚗 Road Route</Text>
            <Text style={styles.leaveAt}>Leave by {result.road_route.leave_at}</Text>
            <Text style={styles.info}>{result.road_route.details.summary}</Text>
            <Text style={styles.duration}>Total: {result.road_route.total_duration_mins} mins</Text>
          </View>
        </View>
      )}

      {/* Log actual delay */}
      <View style={styles.logBox}>
        <Text style={styles.label}>📝 Log today's train delay (mins)</Text>
        <View style={styles.logRow}>
          <TextInput
            style={[styles.input, { flex: 1, marginBottom: 0 }]}
            value={logDelay}
            onChangeText={setLogDelay}
            placeholder="e.g. 8"
            keyboardType="number-pad"
          />
          <TouchableOpacity style={styles.logButton} onPress={saveDelay} disabled={logging}>
            {logging
              ? <ActivityIndicator color="#fff" size="small" />
              : <Text style={styles.logButtonText}>Save</Text>}
          </TouchableOpacity>
        </View>
        {(delayLog[day] || []).length > 0 && (
          <Text style={styles.delayHistory}>
            Last {(delayLog[day] || []).length} {DAY_NAMES[day]} delays: {(delayLog[day] || []).join(', ')} mins
          </Text>
        )}
      </View>
    </ScrollView>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [profile, setProfile] = useState(null);   // null = not loaded yet
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(KEY_PROFILE).then(raw => {
      if (raw) setProfile(JSON.parse(raw));
      setReady(true);
    });
  }, []);

  const resetProfile = async () => {
    await AsyncStorage.removeItem(KEY_PROFILE);
    setProfile(null);
  };

  if (!ready) {
    return (
      <SafeAreaView style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <ActivityIndicator size="large" color="#007AFF" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      {profile
        ? <MainScreen profile={profile} onReset={resetProfile} />
        : <SetupScreen onSave={setProfile} />}
    </SafeAreaView>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F0F4F8' },
  setupScroll: { padding: 24, paddingBottom: 48 },
  mainScroll: { padding: 20, paddingBottom: 48 },

  header: { fontSize: 34, fontWeight: '800', color: '#1A1A2E', textAlign: 'center', marginTop: 16 },
  subHeader: { fontSize: 15, color: '#666', textAlign: 'center', marginBottom: 24 },

  card: {
    backgroundColor: '#fff', borderRadius: 16, padding: 20,
    shadowColor: '#000', shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.08, shadowRadius: 8, elevation: 4,
  },

  profileBar: {
    backgroundColor: '#fff', borderRadius: 12, padding: 14, marginBottom: 12,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06, shadowRadius: 4, elevation: 2,
  },
  profileText: { fontSize: 13, color: '#444', marginBottom: 3 },
  editLink: { fontSize: 13, color: '#007AFF', marginTop: 6 },

  delayBadge: { borderRadius: 10, padding: 10, backgroundColor: '#E8F5E9', marginBottom: 14 },
  delayBadgeActive: { backgroundColor: '#FFF3E0' },
  delayText: { fontSize: 13, color: '#333', textAlign: 'center' },

  label: { fontSize: 14, fontWeight: '600', color: '#444', marginBottom: 6, marginTop: 14 },
  input: {
    borderWidth: 1, borderColor: '#DDE3EA', borderRadius: 10,
    padding: 12, fontSize: 15, backgroundColor: '#FAFAFA', marginBottom: 4,
  },

  button: {
    backgroundColor: '#007AFF', padding: 16, borderRadius: 12,
    marginTop: 20, alignItems: 'center',
    shadowColor: '#007AFF', shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3, shadowRadius: 8, elevation: 5,
  },
  buttonText: { color: '#fff', fontSize: 17, fontWeight: '700' },

  recommendText: {
    fontSize: 20, fontWeight: '700', color: '#1A1A2E',
    textAlign: 'center', marginBottom: 14,
  },

  routeCard: {
    backgroundColor: '#fff', borderRadius: 14, padding: 16,
    marginBottom: 14, borderWidth: 1.5, borderColor: '#E8ECF0',
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06, shadowRadius: 5, elevation: 2,
  },
  winnerCard: { borderColor: '#34C759', backgroundColor: '#F1FFF4' },
  cardTitle: { fontSize: 17, fontWeight: '700', color: '#1A1A2E', marginBottom: 10 },
  leaveAt: { fontSize: 22, fontWeight: '800', color: '#007AFF', marginBottom: 8 },
  info: { fontSize: 14, color: '#555', marginVertical: 3 },
  duration: { fontSize: 14, fontWeight: '600', color: '#333', marginTop: 8 },

  mlBadge: {
    backgroundColor: '#EEF2FF', borderRadius: 10, padding: 10,
    marginBottom: 14, borderWidth: 1, borderColor: '#C7D2FE', alignItems: 'center',
  },
  mlText: { color: '#4338CA', fontWeight: '600', fontSize: 13 },

  logBox: {
    marginTop: 28, backgroundColor: '#fff', borderRadius: 14, padding: 16,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06, shadowRadius: 5, elevation: 2,
  },
  logRow: { flexDirection: 'row', gap: 10, alignItems: 'center' },
  logButton: { backgroundColor: '#34C759', borderRadius: 10, paddingHorizontal: 18, paddingVertical: 13 },
  logButtonText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  delayHistory: { fontSize: 12, color: '#888', marginTop: 8, textAlign: 'center' },

  // 📍 Use My Location button
  locButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    borderColor: '#007AFF',
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 10,
    backgroundColor: '#F0F8FF',
  },
  locButtonDisabled: {
    borderColor: '#A0BFDF',
    backgroundColor: '#F5F9FF',
  },
  locButtonInner: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  locButtonText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#007AFF',
  },

  pillContainer: { flexDirection: 'row', marginBottom: 6 },
  pill: { backgroundColor: '#F0F4F8', paddingHorizontal: 16, paddingVertical: 10, borderRadius: 20, marginRight: 8, borderWidth: 1, borderColor: '#DDE3EA' },
  pillActive: { backgroundColor: '#007AFF', borderColor: '#007AFF' },
  pillText: { fontSize: 14, fontWeight: '600', color: '#555' },
  pillTextActive: { color: '#fff' }
});
