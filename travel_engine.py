import pandas as pd
import googlemaps
import numpy as np
from sklearn.cluster import KMeans
import joblib, math, datetime, requests, os
from functools import lru_cache

CITIES_WITH_AIRPORTS = {
    "delhi","mumbai","bangalore","bengaluru","chennai","kolkata","hyderabad",
    "pune","ahmedabad","jaipur","lucknow","chandigarh","goa","kochi",
    "trivandrum","bhubaneswar","guwahati","indore","bhopal","patna",
    "nagpur","srinagar","varanasi","amritsar","surat","mangalore","coimbatore"
}

_BASE = os.path.dirname(os.path.abspath(__file__))
_PLACES_CSV    = os.path.join(_BASE, 'fallback_places.csv')
_FOOD_CSV      = os.path.join(_BASE, 'fallback_food.csv')
_TRANSPORT_CSV = os.path.join(_BASE, 'fallback_transport.csv')
_MODEL_PKL     = os.path.join(_BASE, 'transport_model.pkl')


# ── Coordinates ──────────────────────────────────────────────────────────────
def get_coordinates(city, gmaps):
    if gmaps:
        try:
            r = gmaps.geocode(city)
            if r:
                loc = r[0]['geometry']['location']
                return loc['lat'], loc['lng']
        except Exception:
            pass
    try:
        df = pd.read_csv(_PLACES_CSV)
        row = df[df['city'].str.lower() == city.lower()]
        if not row.empty:
            return float(row.iloc[0]['lat']), float(row.iloc[0]['lng'])
    except Exception:
        pass
    return None


# ── Distance / Time ───────────────────────────────────────────────────────────
def get_distance_time(origin, destination, gmaps, mode='driving'):
    if not gmaps:
        return "N/A", "N/A", 500
    try:
        # mode can be 'driving', 'transit', 'walking', 'bicycling'
        el = gmaps.distance_matrix(origin, destination, mode=mode)['rows'][0]['elements'][0]
        if el.get('status') == 'OK':
            return (
                el['distance']['text'],
                el['duration']['text'],
                math.ceil(el['distance']['value'] / 1000.0)
            )
        return "N/A", "N/A", 500
    except Exception:
        return "N/A", "N/A", 500


# ── Weather ───────────────────────────────────────────────────────────────────
@lru_cache(maxsize=32)
def get_weather_intelligence(lat, lng):
    base = ["✓ Comfortable Walking Shoes", "✓ Reliable Power Bank", "✓ Reusable Water Bottle"]
    try:
        url  = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
                "&daily=temperature_2m_max,precipitation_probability_max&timezone=auto")
        data = requests.get(url, timeout=5).json().get('daily', {})
        temps = data.get('temperature_2m_max', [])
        rains = data.get('precipitation_probability_max', [])
        avg_t = sum(temps) / len(temps) if temps else 25
        max_r = max(rains) if rains else 0
        packing = base[:]
        if max_r > 35: packing += ["☔ Umbrella / Raincoat", "🎒 Waterproof Cover"]
        if avg_t > 30: packing += ["🕶️ UV Sunglasses", "🧴 Sunscreen SPF 50+"]
        if avg_t < 15: packing += ["🧥 Winter Jacket", "🧤 Thermal Wear"]
        return {"temp_max": f"{round(avg_t)}°C", "rain_chance": f"{max_r}%", "packing_list": packing}
    except Exception:
        return {"temp_max": "EST 25°C", "rain_chance": "10%", "packing_list": base}


# ── Transport Prediction ──────────────────────────────────────────────────────
def predict_transport(distance_km, budget, destination, travelers=1):
    transport_budget = budget * 0.30
    mode = None
    
    # 1. Try ML Model
    try:
        model = joblib.load(_MODEL_PKL)
        feat  = pd.DataFrame([[distance_km, transport_budget]], columns=['distance_km', 'budget'])
        raw   = model.predict(feat)[0]
        mode  = str(raw)
        
        # Mapping integer indices to labels if needed
        if mode.lstrip('-').isdigit():
            classes = ["Bus / Car", "Flight", "Train"] # default
            if hasattr(model, 'classes_'):
                cls_list = list(model.classes_)
                if all(isinstance(x, (int, np.integer)) for x in cls_list):
                    import json
                    try:
                        with open(os.path.join(_BASE, 'model_metadata.json'), 'r') as f:
                            classes = json.load(f).get('target_classes', classes)
                    except: pass
                else:
                    classes = [str(x) for x in cls_list]
            
            idx = int(mode)
            mode = classes[idx] if 0 <= idx < len(classes) else "Train"
            
    except Exception:
        # 2. Try Fallback CSV (Offline Cache)
        try:
            if os.path.exists(_TRANSPORT_CSV):
                df_f = pd.read_csv(_TRANSPORT_CSV)
                match = df_f[(df_f['distance_km'] == distance_km) & (df_f['budget'] == budget)]
                if not match.empty:
                    mode = match.iloc[-1]['predicted_mode']
        except: pass

    # 3. Final Hard Fallback
    per_person_transport = transport_budget / travelers
    if not mode:
        if   distance_km < 300: mode = "Bus / Car"
        elif distance_km < 900: mode = "Train"
        else: mode = "Flight" if per_person_transport > 5000 else "Train (Sleeper/3AC)"

    # AI Preference Override: 
    # 1. Don't suggest Flight as PRIMARY if distance < 900km
    # 2. LOW BUDGET: If per-person transport budget < 4500, prefer Train only
    if "Flight" in mode:
        if distance_km < 900 or per_person_transport < 4500:
            mode = "Train" # Downgrade to Train, Flight stays as option

    # Airport / Cost Logic
    has_airport  = any(c in destination.lower() for c in CITIES_WITH_AIRPORTS)
    flight_cost  = max(4000, math.floor(distance_km * 5)) if has_airport else 0
    train_cost   = max(500,  math.floor(distance_km * 2.5))
    bus_cost     = math.floor(distance_km * 2)

    if "Flight" in mode and not has_airport:
        mode, selected = "Train (AC Sleeper)", train_cost
    elif "Flight" in mode:
        mode, selected = "Flight / Train (2AC)", flight_cost
    elif "Train" in mode:
        # For distances > 600km, suggest AC classes primarily if budget allows
        label = "Train (2AC/2A)" if (distance_km > 600 and per_person_transport > 2200) else "Train (Sleeper/3AC)"
        mode, selected = label, train_cost
    else:
        mode, selected = "Bus/Car / Train (Seater)", bus_cost

    # Cache the final processed mode for offline use
    try:
        df_new = pd.DataFrame([{
            "distance_km": distance_km, "budget": budget, 
            "destination": destination, "predicted_mode": mode
        }])
        if os.path.exists(_TRANSPORT_CSV):
            df_curr = pd.read_csv(_TRANSPORT_CSV)
            # Avoid exact duplicates
            if not ((df_curr['distance_km'] == distance_km) & (df_curr['budget'] == budget) & (df_curr['destination'] == destination)).any():
                df_new.to_csv(_TRANSPORT_CSV, mode='a', header=False, index=False)
        else:
            df_new.to_csv(_TRANSPORT_CSV, index=False)
    except: pass

    return mode, {"selected": selected, "flight": flight_cost, "train": train_cost, "bus": bus_cost}


# ── Places ────────────────────────────────────────────────────────────────────
def _photo_urls(photos, key, n=4):
    return [
        f"https://places.googleapis.com/v1/{p['name']}/media?maxHeightPx=400&maxWidthPx=400&key={key}"
        for p in photos[:n] if p.get('name')
    ]

@lru_cache(maxsize=32)
def fetch_top_places(city, key):
    if not key:
        return pd.DataFrame()
    url     = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': key,
        'X-Goog-FieldMask': 'places.displayName,places.location,places.rating,places.photos'
    }
    places, ok = [], False
    try:
        res = requests.post(url, headers=headers, json={'textQuery': f"tourist attractions in {city}"})
        if res.status_code == 200:
            for p in res.json().get('places', [])[:15]:
                try:
                    places.append({
                        "name":   p['displayName']['text'],
                        "lat":    p['location']['latitude'],
                        "lng":    p['location']['longitude'],
                        "rating": p.get('rating', 4.0),
                        "photos": _photo_urls(p.get('photos', []), key),
                    })
                except KeyError:
                    continue
            ok = True
    except Exception:
        pass

    if ok and places:
        try:
            df_ex = pd.read_csv(_PLACES_CSV) if os.path.exists(_PLACES_CSV) else pd.DataFrame(columns=['city','name','lat','lng','rating','fee'])
            df_ex = df_ex[df_ex['city'].str.lower() != city.lower()]
            new   = [{"city": city, "name": p["name"], "lat": p["lat"], "lng": p["lng"], "rating": p["rating"], "fee": 0} for p in places]
            pd.concat([df_ex, pd.DataFrame(new)], ignore_index=True).to_csv(_PLACES_CSV, index=False)
        except Exception:
            pass

    if not places:
        try:
            df = pd.read_csv(_PLACES_CSV)
            rows = df[df['city'].str.lower() == city.lower()]
            places = rows.to_dict('records') if not rows.empty else [
                {"name": f"Top Destination Area {i+1}", "lat": 20.0, "lng": 76.0, "rating": 4.5, "photos": []}
                for i in range(5)
            ]
        except Exception:
            places = [{"name": f"Top Destination Area {i+1}", "lat": 20.0, "lng": 76.0, "rating": 4.5, "photos": []} for i in range(5)]

    return pd.DataFrame(places)


# ── Itinerary Clustering ──────────────────────────────────────────────────────
def cluster_itinerary(df_places, days):
    df = df_places.copy()
    if df.empty:
        return df
    n = min(days, len(df))
    if n > 0 and len(df) >= n:
        df['Day'] = KMeans(n_clusters=n, random_state=42, n_init=10).fit_predict(df[['lat','lng']].values) + 1
        df = df.sort_values(['Day','rating'], ascending=[True, False])
    else:
        df['Day'] = 1

    starts, ends = [], []
    for day in df['Day'].unique():
        base = datetime.datetime.today().replace(hour=9, minute=0, second=0, microsecond=0)
        for _ in df[df['Day'] == day].itertuples():
            ends.append(base + datetime.timedelta(hours=2))
            starts.append(base)
            base = ends[-1] + datetime.timedelta(minutes=45)
    df['Start_Time'] = starts
    df['End_Time']   = ends
    return df


# ── Hotel ─────────────────────────────────────────────────────────────────────
def recommend_hotel(city, checkin, checkout, budget, days, travelers=1):
    num_rooms = math.ceil(travelers / 2)
    # Distribute 40% of budget across all rooms and days
    rate = max(1000, min((budget * 0.4) / (days * num_rooms), 8000))
    return {
        "name":           f"Top Rated Hotel in {city} ({num_rooms} Room{'s' if num_rooms > 1 else ''})",
        "price_per_night": math.floor(rate),
        "total_cost":      math.floor(rate * days * num_rooms),
        "link":            f"https://www.booking.com/searchresults.html?ss={city}&checkin={checkin}&checkout={checkout}&group_adults={travelers}&no_rooms={num_rooms}",
    }


# ── Food ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=32)
def recommend_food(city, key, days, budget, travelers=1):
    if not key:
        return [], 0
    # Use per-person daily food budget to pick restaurant type
    daily_per_person = (budget * 0.3) / (days * travelers)
    if   daily_per_person >= 2500: query, mul = f"luxury 5 star fine dining in {city}", 400
    elif daily_per_person <= 800:  query, mul = f"affordable street food in {city}", 40
    else:                          query, mul = f"popular medium budget restaurants in {city}", 100

    url     = "https://places.googleapis.com/v1/places:searchText"
    headers = {'Content-Type': 'application/json', 'X-Goog-Api-Key': key,
               'X-Goog-FieldMask': 'places.displayName,places.rating,places.photos'}
    items, ok = [], False
    try:
        res = requests.post(url, headers=headers, json={'textQuery': query})
        if res.status_code == 200:
            for p in res.json().get('places', [])[:10]:
                try:
                    r = p.get('rating', 4.0)
                    items.append({"name": p['displayName']['text'], "rating": r,
                                  "price": math.ceil(r * mul),
                                  "photos": _photo_urls(p.get('photos', []), key)})
                except KeyError:
                    continue
            ok = True
    except Exception:
        pass

    if ok and items:
        try:
            df_ex = pd.read_csv(_FOOD_CSV) if os.path.exists(_FOOD_CSV) else pd.DataFrame(columns=['city','name','rating','price'])
            df_ex = df_ex[df_ex['city'].str.lower() != city.lower()]
            new   = [{"city": city, "name": i["name"], "rating": i["rating"], "price": i["price"]} for i in items]
            pd.concat([df_ex, pd.DataFrame(new)], ignore_index=True).to_csv(_FOOD_CSV, index=False)
        except Exception:
            pass

    if not items:
        try:
            df = pd.read_csv(_FOOD_CSV)
            rows = df[df['city'].str.lower() == city.lower()]
            if not rows.empty:
                items = [{"name": r['name'], "rating": r['rating'], "price": math.ceil(r['rating'] * mul), "photos": []} for _, r in rows.iterrows()]
            else:
                items = [{"name": f"Popular Local Diner {i+1}", "rating": 4.3, "price": math.ceil(4.3*mul), "photos": []} for i in range(3)]
        except Exception:
            items = [{"name": f"Popular Local Diner {i+1}", "rating": 4.3, "price": math.ceil(4.3*mul), "photos": []} for i in range(3)]

    df_food = pd.DataFrame(items)
    avg     = df_food['price'].mean() if not df_food.empty else 300
    return items, math.ceil(avg * 2 * days * travelers)


# ── Groq AI Chat ──────────────────────────────────────────────────────────────
def get_groq_chat_response(messages, api_key):
    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "llama-3.1-8b-instant", "messages": messages, "temperature": 0.7, "max_tokens": 1024},
            timeout=10
        )
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
        return f"⚠️ Groq API Error: {res.status_code}"
    except Exception as e:
        return f"⚠️ Connection error: {e}"
