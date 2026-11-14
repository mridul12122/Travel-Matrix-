from flask import Flask, jsonify, request, render_template, send_file
from flask_cors import CORS
from fpdf import FPDF
import io
import googlemaps
import requests
import math
import ast
from datetime import date as dateobj
from indian_cities import INDIAN_CITIES
import os
from dotenv import load_dotenv
from travel_engine import (
    get_coordinates, get_distance_time, predict_transport,
    fetch_top_places, cluster_itinerary, recommend_hotel, recommend_food,
    get_weather_intelligence, get_groq_chat_response
)

load_dotenv()

app = Flask(__name__)
CORS(app)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def is_online():
    try:
        requests.get("https://www.google.com", timeout=2)
        return True
    except Exception:
        return False


def safe_photos(raw):
    """Ensure photos value is always a Python list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return ast.literal_eval(raw)
        except Exception:
            return []
    return []


def clean_pdf_text(s):
    """Ensure string is compatible with FPDF standard fonts (latin-1)."""
    if not s: return ""
    return str(s).encode('latin-1', 'replace').decode('latin-1')


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/cities')
def get_cities():
    return jsonify(INDIAN_CITIES)


@app.route('/api/detect-city')
def detect_city():
    try:
        res = requests.get('http://ip-api.com/json/', timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data.get('status') == 'success':
                detected = data.get('city', 'Delhi')
                for city in INDIAN_CITIES:
                    if city.lower() == detected.lower():
                        return jsonify({"city": city})
                for city in INDIAN_CITIES:
                    if detected.lower() in city.lower() or city.lower() in detected.lower():
                        return jsonify({"city": city})
    except Exception:
        pass
    return jsonify({"city": "Delhi"})


@app.route('/api/plan', methods=['POST'])
def generate_plan():
    req = request.json or {}
    origin      = req.get('origin', 'Delhi')
    destination = req.get('destination', 'Goa')
    budget      = int(req.get('budget', 15000))
    checkin     = req.get('checkin',  str(dateobj.today()))
    checkout    = req.get('checkout', str(dateobj.today()))
    travelers   = int(req.get('travelers', 1))

    try:
        days = max(1, (dateobj.fromisoformat(checkout) - dateobj.fromisoformat(checkin)).days)
    except Exception:
        days = 3

    online = is_online()

    try:
        gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
    except Exception:
        gmaps = None

    # ── Core data ──────────────────────────────────────────────
    distance_text, duration, dist_val = get_distance_time(origin, destination, gmaps)
    transport_mode, transport_cost    = predict_transport(dist_val, budget, destination, travelers)

    # ── Refine Duration based on Mode ────────────────────────
    if dist_val != 500 and gmaps:
        if any(x in transport_mode.lower() for x in ["train", "bus"]):
            # Try to get real transit time from Google
            _, trans_dur, _ = get_distance_time(origin, destination, gmaps, mode='transit')
            if trans_dur != "N/A":
                duration = trans_dur
        elif "flight" in transport_mode.lower():
            # Google doesn't do flight durations in distance_matrix
            # Estimation: 1.5h flight + 3h airport + 1h shuttle = ~5.5h
            duration = "5.5 hrs (incl. airport)"

    # Scale transport costs by number of travelers
    for key in ['selected', 'flight', 'train', 'bus']:
        if key in transport_cost:
            transport_cost[key] *= travelers

    df_places = fetch_top_places(destination, GOOGLE_API_KEY)

    # ── Itinerary (serialise to JSON-safe dicts) ───────────────
    itinerary = []
    if not df_places.empty:
        df_itin = cluster_itinerary(df_places, days)
        for _, row in df_itin.iterrows():
            st_raw = row.get('Start_Time')
            et_raw = row.get('End_Time')
            itinerary.append({
                "day":        int(row.get('Day', 1)),
                "name":       str(row.get('name', '')),
                "lat":        float(row.get('lat', 0)),
                "lng":        float(row.get('lng', 0)),
                "rating":     float(row.get('rating', 4.0)),
                "photos":     safe_photos(row.get('photos', [])),
                "start_time": str(st_raw)[11:16] if st_raw is not None else '09:00',
                "end_time":   str(et_raw)[11:16] if et_raw is not None else '11:00',
            })

    # ── Hotel & Food ───────────────────────────────────────────
    hotel_info        = recommend_hotel(destination, checkin, checkout, budget, days, travelers)
    food_items, food_cost = recommend_food(destination, GOOGLE_API_KEY, days, budget, travelers)
    for item in food_items:
        item['photos'] = safe_photos(item.get('photos', []))

    total_cost = transport_cost['selected'] + hotel_info['total_cost'] + food_cost

    # ── Weather ────────────────────────────────────────────────
    dest_coords = get_coordinates(destination, gmaps)
    weather = {"temp_max": "N/A", "rain_chance": "N/A", "packing_list": []}
    if dest_coords:
        weather = get_weather_intelligence(float(dest_coords[0]), float(dest_coords[1]))

    return jsonify({
        "distance_text":  distance_text,
        "duration":       duration,
        "transport_mode": transport_mode,
        "transport_cost": transport_cost,
        "itinerary":      itinerary,
        "days":           days,
        "hotel":          hotel_info,
        "food_items":     food_items,
        "food_cost":      food_cost,
        "total_cost":     total_cost,
        "weather":        weather,
        "dest_coords":    list(dest_coords) if dest_coords else None,
        "online":         online,
        "destination":    destination,
        "origin":         origin,
        "budget":         budget,
        "travelers":      travelers,
    })


@app.route('/api/export-pdf', methods=['POST'])
def export_pdf():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    try:
        # ── Header / Branding ──
        pdf.set_font("Helvetica", "B", 24)
        pdf.set_text_color(79, 142, 247) # Blue accent
        pdf.cell(0, 20, "AI Travel Matrix", align="C", new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_font("Helvetica", "I", 12)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 10, "Your Personalized Smart Itinerary", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(10)
        
        # ── Trip Overview ──
        pdf.set_fill_color(240, 245, 255)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(0, 0, 0)
        overview_title = clean_pdf_text(f"Trip Overview: {data.get('origin')} to {data.get('destination')}")
        pdf.cell(0, 12, overview_title, fill=True, new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_font("Helvetica", "", 11)
        pdf.ln(5)
        pdf.cell(95, 8, f"Duration: {data.get('days')} Days")
        pdf.cell(95, 8, f"Total Travelers: {data.get('travelers')}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(95, 8, clean_pdf_text(f"Distance: {data.get('distance_text')}"))
        pdf.cell(95, 8, clean_pdf_text(f"Selected Transport: {data.get('transport_mode')}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(10)
        
        # ── Daily Itinerary ──
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_fill_color(240, 245, 255)
        pdf.cell(0, 12, "Detailed Daily Itinerary", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        
        # Group itinerary by day
        itinerary = data.get('itinerary', [])
        by_day = {}
        for p in itinerary:
            d = p['day']
            if d not in by_day: by_day[d] = []
            by_day[d].append(p)
            
        for day_num in range(1, data.get('days', 1) + 1):
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(79, 142, 247)
            pdf.cell(0, 10, f"Day {day_num}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            
            day_places = by_day.get(day_num, [])
            if not day_places:
                pdf.set_font("Helvetica", "I", 10)
                pdf.cell(0, 8, "  No activities planned for today.", new_x="LMARGIN", new_y="NEXT")
            else:
                for place in day_places:
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.cell(30, 8, f"  {place.get('start_time')} - ")
                    pdf.set_font("Helvetica", "", 10)
                    name = clean_pdf_text(place.get('name', ''))
                    # Fixed: Explicitly calculate width to avoid FPDFException
                    rem_w = pdf.w - pdf.l_margin - pdf.r_margin - 30
                    pdf.multi_cell(rem_w, 8, f"{name} (Rating: {place.get('rating')})", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            
        pdf.ln(5)
        
        # ── Packing & Weather Advice ──
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_fill_color(240, 245, 255)
        pdf.cell(0, 12, "Weather & Preparation", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        
        w = data.get('weather', {})
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, clean_pdf_text(f"Estimated Max Temp: {w.get('temp_max', 'N/A')}"), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, clean_pdf_text(f"Rain Probability: {w.get('rain_chance', 'N/A')}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "AI Recommended Packing List:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for item in w.get('packing_list', []):
            pdf.cell(0, 7, clean_pdf_text(f"- {item}"), new_x="LMARGIN", new_y="NEXT")
    
        # ── Hotel & Food ──
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_fill_color(240, 245, 255)
        pdf.cell(0, 12, "Accommodation & Dining", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        
        h = data.get('hotel', {})
        pdf.set_font("Helvetica", "B", 11)
        hname = clean_pdf_text(h.get('name', 'N/A'))
        pdf.cell(0, 8, f"Selected Hotel: {hname}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 8, f"Price per Night: INR {h.get('price_per_night', 0):,}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, f"Total Stay Cost: INR {h.get('total_cost', 0):,}", new_x="LMARGIN", new_y="NEXT")
        
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "Recommended Local Dining:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for food in data.get('food_items', [])[:5]:
            fname = clean_pdf_text(food.get('name', ''))
            pdf.cell(0, 7, f"- {fname} (Est. Price: INR {food.get('price', 0)})", new_x="LMARGIN", new_y="NEXT")
            
        # ── Budget Summary ──
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_fill_color(240, 245, 255)
        pdf.cell(0, 12, "Budget Analysis", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(100, 8, "Transport Cost:")
        pdf.cell(0, 8, f"INR {data.get('transport_cost', {}).get('selected', 0):,}", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(100, 8, "Accommodation Cost:")
        pdf.cell(0, 8, f"INR {data.get('hotel', {}).get('total_cost', 0):,}", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(100, 8, "Estimated Food Cost:")
        pdf.cell(0, 8, f"INR {data.get('food_cost', 0):,}", align="R", new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_font("Helvetica", "B", 12)
        pdf.ln(2)
        pdf.cell(100, 10, "Total Estimated Budget:")
        pdf.cell(0, 10, f"INR {data.get('total_cost', 0):,}", align="R", new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_font("Helvetica", "B", 11)
        status = "WITHIN BUDGET" if data.get('total_cost', 0) <= data.get('budget', 0) else "EXCEEDS BUDGET"
        pdf.set_text_color(0, 150, 0) if status == "WITHIN BUDGET" else pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 10, f"Status: {status}", align="R", new_x="LMARGIN", new_y="NEXT")

        # Output bytes directly for fpdf2
        pdf_bytes = pdf.output()
        return send_file(
            io.BytesIO(pdf_bytes),
            as_attachment=True,
            download_name=f"AI_Travel_Plan_{data.get('destination', 'Trip')}.pdf",
            mimetype='application/pdf'
        )
    except Exception as e:
        print(f"PDF Error: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, port=5000)