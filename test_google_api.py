#!/usr/bin/env python3
"""
Test script to verify Google API key configuration
"""
import os
from dotenv import load_dotenv
import requests

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

print("=" * 60)
print("Google API Key Configuration Test")
print("=" * 60)
print(f"\n✓ API Key found: {GOOGLE_API_KEY[:20]}..." if GOOGLE_API_KEY else "✗ No API key found!")
print()

if not GOOGLE_API_KEY:
    print("ERROR: GOOGLE_API_KEY not found in .env file")
    exit(1)

# Test 1: Geocoding API
print("Test 1: Geocoding API")
print("-" * 60)
geocode_url = f"https://maps.googleapis.com/maps/api/geocode/json?address=Delhi&key={GOOGLE_API_KEY}"
try:
    response = requests.get(geocode_url, timeout=10)
    data = response.json()
    if data.get("status") == "OK":
        print("✓ Geocoding API: WORKING")
    elif data.get("status") == "REQUEST_DENIED":
        print(f"✗ Geocoding API: REQUEST DENIED")
        print(f"  Error: {data.get('error_message', 'No error message')}")
    else:
        print(f"✗ Geocoding API: {data.get('status')}")
        print(f"  Error: {data.get('error_message', 'Unknown error')}")
except Exception as e:
    print(f"✗ Geocoding API: FAILED - {e}")

print()

# Test 2: Places API
print("Test 2: Places API (Text Search)")
print("-" * 60)
places_url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query=restaurants+in+Goa&key={GOOGLE_API_KEY}"
try:
    response = requests.get(places_url, timeout=10)
    data = response.json()
    if data.get("status") == "OK":
        print("✓ Places API: WORKING")
        print(f"  Found {len(data.get('results', []))} results")
    elif data.get("status") == "REQUEST_DENIED":
        print(f"✗ Places API: REQUEST DENIED")
        print(f"  Error: {data.get('error_message', 'No error message')}")
    else:
        print(f"✗ Places API: {data.get('status')}")
        print(f"  Error: {data.get('error_message', 'Unknown error')}")
except Exception as e:
    print(f"✗ Places API: FAILED - {e}")

print()

# Test 3: Distance Matrix API
print("Test 3: Distance Matrix API")
print("-" * 60)
distance_url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins=Delhi&destinations=Goa&key={GOOGLE_API_KEY}"
try:
    response = requests.get(distance_url, timeout=10)
    data = response.json()
    if data.get("status") == "OK":
        print("✓ Distance Matrix API: WORKING")
    elif data.get("status") == "REQUEST_DENIED":
        print(f"✗ Distance Matrix API: REQUEST DENIED")
        print(f"  Error: {data.get('error_message', 'No error message')}")
    else:
        print(f"✗ Distance Matrix API: {data.get('status')}")
        print(f"  Error: {data.get('error_message', 'Unknown error')}")
except Exception as e:
    print(f"✗ Distance Matrix API: FAILED - {e}")

print()
print("=" * 60)
print("Summary & Recommendations")
print("=" * 60)
print("""
If you see REQUEST_DENIED errors, you need to:

1. Go to Google Cloud Console: https://console.cloud.google.com/
2. Enable the following APIs:
   - Geocoding API
   - Places API
   - Distance Matrix API
3. Make sure billing is enabled on your project
4. Check API key restrictions (HTTP referrers, IP addresses, API restrictions)
5. If using localhost, add http://localhost:* to allowed referrers

The map display uses Leaflet/CartoDB (no Google API needed).
Google APIs are only used for places, distances, and geocoding.
""")
