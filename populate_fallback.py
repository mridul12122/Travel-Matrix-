import googlemaps
from indian_cities import INDIAN_CITIES
from travel_engine import (
    get_distance_time, predict_transport, fetch_top_places, recommend_food
)
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
BUDGETS = [10000, 25000, 50000]
ORIGIN = INDIAN_CITIES[0]

def main():
    print(f"Starting fallback data population.")
    print(f"Origin City: {ORIGIN}")
    print(f"Total Destinations: {len(INDIAN_CITIES)}")
    
    try:
        gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
    except Exception as e:
        print(f"Error initializing Google Maps client: {e}")
        return

    for i, dest in enumerate(INDIAN_CITIES):
        print(f"[{i+1}/{len(INDIAN_CITIES)}] Processing {dest}...")
        
        # 1. Distance and Transport
        _, _, dist_val = get_distance_time(ORIGIN, dest, gmaps)
        for budget in BUDGETS:
            predict_transport(dist_val, budget, dest)
        
        # 2. Top Places
        fetch_top_places(dest, GOOGLE_API_KEY)
        
        # 3. Food Recommendations
        for budget in BUDGETS:
            recommend_food(dest, GOOGLE_API_KEY, days=3, budget=budget)

    print("Population complete!")

if __name__ == "__main__":
    main()
