import os
import pandas as pd
import googlemaps
import json
import numpy as np
from datetime import datetime
from config import GOOGLE_MAPS_KEY
import requests

client = googlemaps.Client(key=GOOGLE_MAPS_KEY)

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
cache_dir = os.path.join(base_dir, "cache")

addresses_cache = os.path.join(cache_dir, "physician_deployment_addresses.json")
geocode_cache = os.path.join(cache_dir, "physician_deployment_addresses_geocode.json")
matrix_cache = os.path.join(cache_dir, "physician_distance_matrix.json")


def get_addresses(facilities: list) -> dict:
    """
    Look up formatted street addresses for UPMC facility names using the
    Google Places Text Search API.

    Results are cached to disk. On subsequent runs the cache is loaded
    directly. Facilities not resolved will have a None value in the cache
    and should be filled in manually before proceeding.

    Parameters
    ----------
    facilities : list of str
        Facility name strings as they appear in the surgical data.

    Returns
    -------
    dict
        Mapping of facility name to formatted address string (or None).
    """

    if os.path.exists(addresses_cache):
        print("Address cache found. Skipping Places API calls.")
        with open(addresses_cache, 'r') as f:
            return json.load(f)

    print(f"\nLooking up addresses for {len(facilities)} facilities...")
    results = {}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress"
    }

    for facility in facilities:
        try:
            query = facility if "UPMC" in facility else f"UPMC {facility}"
            response = requests.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json={"textQuery": query}
            )
            print(response.status_code, response.json())

            data = response.json()
            if "places" in data and data["places"]:
                results[facility] = data["places"][0]["formattedAddress"]
                print(f"  [OK] {facility} -> {results[facility]}")
            else:
                results[facility] = None
                print(f"  [NOT FOUND] {facility}")
        except Exception as e:
            print(f"  [ERROR] {facility}: {e}")
            results[facility] = None

    not_found = sum(1 for v in results.values() if v is None)
    if not_found:
        print(f"\nWarning: {not_found} facilities could not be resolved. Fill in manually: {addresses_cache}")

    with open(addresses_cache, 'w') as f:
        json.dump(results, f, indent=4)
    return results


def get_geocodes(address_map: dict) -> dict:
    """
    Geocode formatted facility addresses to lat/lng using the Google Maps
    Geocoding API.

    Results are cached to disk.

    Parameters
    ----------
    address_map : dict
        Output of get_addresses(); maps facility name to address string.

    Returns
    -------
    dict
        Mapping of facility name to {'lat': float, 'lng': float} (or None).
    """

    if os.path.exists(geocode_cache):
        print("Geocode cache found. Skipping Geocoding API calls.")
        with open(geocode_cache, 'r') as f:
            return json.load(f)

    print("\nGeocoding addresses...")
    results = {}
    for facility, address in address_map.items():
        if address is None:
            results[facility] = None
            continue
        try:
            res = client.geocode(address)
            results[facility] = res[0]['geometry']['location'] if res else None
        except Exception as e:
            print(f"  Error geocoding '{facility}': {e}")
            results[facility] = None

    with open(geocode_cache, 'w') as f:
        json.dump(results, f, indent=4)
    return results


def get_distance_matrix(facilities: list, geocode_map: dict):
    """
    Build a full pairwise driving distance and duration matrix for all
    facilities using the Google Maps Distance Matrix API.

    Requests are chunked to stay within the 25-origin x 25-destination
    per-call limit. Results are written to the matrix cache file. If the
    cache already exists the function returns immediately.

    Parameters
    ----------
    facilities : list of str
        Facility names; must be keys in geocode_map.
    geocode_map : dict
        Output of get_geocodes(); maps facility name to lat/lng.
    """

    if os.path.exists(matrix_cache):
        print("Matrix cache found. Skipping Distance Matrix API calls.")
        return

    valid = [(f, geocode_map[f]) for f in facilities if geocode_map.get(f)]
    names = [f for f, _ in valid]
    coords = [c for _, c in valid]
    n = len(coords)
    final_rows = [[] for _ in range(n)]

    DEST_CHUNK_SIZE = 25
    for j in range(0, n, DEST_CHUNK_SIZE):
        dest_chunk = coords[j:j + DEST_CHUNK_SIZE]
        ORIGIN_CHUNK_SIZE = min(25, 100 // len(dest_chunk))
        for i in range(0, n, ORIGIN_CHUNK_SIZE):
            origin_chunk = coords[i:i + ORIGIN_CHUNK_SIZE]
            print(f"Requesting origins {i}-{i + len(origin_chunk)} x destinations {j}-{j + len(dest_chunk)}")
            response = client.distance_matrix(
                origins=origin_chunk,
                destinations=dest_chunk,
                mode="driving",
                departure_time=datetime.now(),
                traffic_model="best_guess"
            )
            if response['status'] == 'OK':
                for idx, row in enumerate(response['rows']):
                    final_rows[i + idx].extend(row['elements'])

    with open(matrix_cache, 'w') as f:
        json.dump({"names": names, "rows": [{"elements": r} for r in final_rows]}, f, indent=4)


def build_csvs():
    """
    Read the matrix cache and produce three output DataFrames.

    - Distance matrix: miles between each facility pair.
    - Duration matrix: driving minutes between each facility pair,
      using duration_in_traffic where available.
    - Normalized distance matrix: per-row min-max normalization of
      distances, excluding the diagonal (self-distance).

    Returns
    -------
    df_dur : pd.DataFrame
        Duration matrix in minutes, facilities as index and columns.
    df_dist : pd.DataFrame
        Distance matrix in miles, facilities as index and columns.
    normalized : pd.DataFrame
        Row-normalized distance matrix.
    """

    with open(matrix_cache, 'r') as f:
        data = json.load(f)

    names = data["names"]

    dist_list = [[el['distance']['value'] if el['status'] == 'OK' else float('nan')
                  for el in row['elements']] for row in data['rows']]
    dur_list = [[el.get('duration_in_traffic', el['duration'])['value'] if el['status'] == 'OK' else float('nan')
                 for el in row['elements']] for row in data['rows']]

    df_dist = pd.DataFrame(dist_list, index=names, columns=names) * 0.000621371
    df_dur = pd.DataFrame(dur_list, index=names, columns=names) / 60

    # Normalize distances
    df_masked = df_dist.mask(np.eye(len(df_dist), dtype=bool))
    min_dist = df_masked.min(axis=1)
    max_dist = df_masked.max(axis=1)
    normalized = df_dist.sub(min_dist, axis=0).div(max_dist - min_dist, axis=0)

    return df_dur, df_dist, normalized


def run(surgeries_df: pd.DataFrame):
    """
    Execute the full distance matrix pipeline for physician deployment.

    Looks up facility addresses, geocodes them, computes the pairwise
    driving matrix via Google Maps, and returns distance/duration DataFrames.

    Parameters
    ----------
    surgeries_df : pd.DataFrame
        Surgical case data; must contain column: Facility.

    Returns
    -------
    df_dur : pd.DataFrame
        Duration matrix in minutes.
    df_dist : pd.DataFrame
        Distance matrix in miles.
    normalized : pd.DataFrame
        Row-normalized distance matrix.
    """

    os.makedirs(cache_dir, exist_ok=True)

    facilities = sorted(surgeries_df['Facility'].unique().tolist())
    address_map = get_addresses(facilities)
    geocode_map = get_geocodes(address_map)
    get_distance_matrix(facilities, geocode_map)
    df_dur, df_dist, normalized = build_csvs()
    return df_dur, df_dist, normalized