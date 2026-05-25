# ClgBuddy Backend (NikLo)

A smart commute planner for college students in Mumbai, built with a Python/Flask backend and React Native (Expo) frontend. NikLo helps students find the optimal route between locations using real-world transit data.

## Tech Stack

- **Backend:** Python, Flask, OSRM, Nominatim
- **Frontend:** React Native (Expo)
- **Auth:** Firebase
- **Deployment:** Render

## Features

- GPS-based auto location detection
- Real-time optimal route calculation
- Support for local trains and mixed transit
- Station name geocoding via Nominatim

---

## 🧠 DSA in Production — Dijkstra's Algorithm

One of the core features of NikLo is **shortest path routing**, implemented using **Dijkstra's Algorithm** — not as a textbook exercise, but as actual production logic powering real commute recommendations.

### Problem
Given a student's current location and destination, find the lowest-cost path across a graph of Mumbai transit nodes (stations, stops, landmarks).

### Implementation
The backend models the transit network as a **weighted graph** where:
- **Nodes** = stations / locations
- **Edges** = routes between them
- **Weights** = distance or estimated travel time

Dijkstra's algorithm runs on this graph to compute the globally optimal path using a **min-heap (priority queue)** for efficiency.

```python
import heapq

def dijkstra(graph, start):
    distances = {node: float('inf') for node in graph}
    distances[start] = 0
    heap = [(0, start)]

    while heap:
        curr_dist, curr_node = heapq.heappop(heap)
        if curr_dist > distances[curr_node]:
            continue
        for neighbor, weight in graph[curr_node].items():
            distance = curr_dist + weight
            if distance < distances[neighbor]:
                distances[neighbor] = distance
                heapq.heappush(heap, (distance, neighbor))

    return distances
```

### Complexity
| | Value |
|---|---|
| Time | O((V + E) log V) |
| Space | O(V) |

### Why this matters
Most routing apps abstract this away. In NikLo, this algorithm runs directly on the backend, processing live station data to return the fastest commute path — a real-world application of a core DSA concept.

---

## Setup

```bash
git clone https://github.com/parthpalse/clgbuddy-Backend
cd clgbuddy-Backend
pip install -r requirements.txt
python backend/app.py
```

## Mobile (Expo)

```bash
cd mobile
npm install
npx expo start
```
