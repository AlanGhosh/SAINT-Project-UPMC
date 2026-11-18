import os
import json
import pandas as pd
import numpy as np
import googlemaps
from config import GOOGLE_MAPS_KEY

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
cache_dir = os.path.join(base_dir, "cache")

hospital_path = os.path.join(data_dir, "Hospital Locations.xlsx")
ASC_path = os.path.join(data_dir, "ASC Data.xlsx")
competitor_path = os.path.join(data_dir, "Competitor Data.xlsx")
urgent_cares_path = os.path.join(data_dir, "2024.12.05 MedExpress UCC's part of JV.xlsx")

upmc_locs_out = os.path.join(out_dir, "UPMC Hospital, ASC, Urgent Care Locations.csv")
competitor_locs_out = os.path.join(out_dir, "Competitor Locations.csv")

upmc_geocode_cache = os.path.join(cache_dir, "upmc_locations_geocodes.json")
competitor_geocode_cache = os.path.join(cache_dir, "competitor_locations_geocodes.json")


def geocode_addresses(addresses: list, cache_file: str) -> dict:
    """
    Geocode a list of address strings using the Google Maps API.

    Results are cached to disk at cache_file. On subsequent runs the cache
    is loaded directly, skipping API calls.

    Parameters
    ----------
    addresses : list of str
        Address strings to geocode.
    cache_file : str
        Path to the JSON cache file.

    Returns
    -------
    dict
        Mapping of address string to {'lat': float, 'lng': float}.
    """

    if os.path.exists(cache_file):
        print(f"  Cache found: {cache_file}. Skipping API calls.")
        with open(cache_file, 'r') as f:
            return json.load(f)

    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)
    print(f"  Geocoding {len(addresses)} addresses...")
    results = {}
    for addr in addresses:
        try:
            result = gmaps.geocode(addr)
            if result:
                loc = result[0]['geometry']['location']
                results[addr] = {'lat': loc['lat'], 'lng': loc['lng']}
            else:
                results[addr] = {'lat': None, 'lng': None}
                print(f"    [NOT FOUND] {addr}")
        except Exception as e:
            print(f"    [ERROR] {addr}: {e}")
            results[addr] = {'lat': None, 'lng': None}

    with open(cache_file, 'w') as f:
        json.dump(results, f, indent=4)
    return results


def build_csv(df: pd.DataFrame, geocode_map: dict, output_path: str) -> pd.DataFrame:
    """
    Join geocode results onto a locations DataFrame and write to CSV.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain an Address column.
    geocode_map : dict
        Output of geocode_addresses(); maps address to lat/lng.
    output_path : str
        Destination CSV path.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with added columns: lat, lng.
    """

    df = df.copy()
    df['lat'] = df['Address'].map(lambda x: geocode_map.get(x, {}).get('lat'))
    df['lng'] = df['Address'].map(lambda x: geocode_map.get(x, {}).get('lng'))
    not_found = df['lat'].isna().sum()
    if not_found:
        print(f"  Warning: {not_found} addresses could not be geocoded.")
    df.to_csv(output_path, index=False)
    print(f"  Saved: {output_path}")
    return df


def run():
    """
    Load, geocode, and combine all UPMC and competitor facility locations.

    Reads hospital, ASC, and urgent care Excel files from the data directory,
    filters out closing urgent cares, builds a unified UPMC locations DataFrame,
    geocodes all addresses (with caching), and writes CSVs for both UPMC and
    competitor locations.

    Returns
    -------
    upmc_df : pd.DataFrame
        UPMC hospitals, ASCs, and urgent cares with lat/lng.
    competitor_df : pd.DataFrame
        Competitor facility locations with lat/lng.
    """

    os.makedirs(cache_dir, exist_ok=True)

    hospitals = pd.read_excel(hospital_path)
    hospitals['Address'] = hospitals['Address'].str.replace('\n', ', ')
    hospitals = hospitals.drop(columns=['Company'])

    ASCs = pd.read_excel(ASC_path, header=None)
    ASCs = ASCs.rename(columns={ASCs.columns[0]: 'Address'})
    ASCs['Facility'] = 'ASC'

    urgent_cares = pd.read_excel(urgent_cares_path)
    urgent_cares = urgent_cares[urgent_cares['Closing?'] != 'Closing'].copy()
    urgent_cares = urgent_cares.dropna(subset=['Address 1'])
    urgent_cares['Address'] = (
            urgent_cares['Address 1'].str.strip() + ', ' +
            urgent_cares['City'].str.strip() + ', ' +
            urgent_cares['State'].str.strip() + ' ' +
            urgent_cares['Zip'].astype(float).astype('Int64').astype(str)
    )
    urgent_cares = urgent_cares[['Address']].copy()
    urgent_cares['Facility'] = 'Urgent Care'


    UPMC_locations = pd.concat([hospitals, ASCs], ignore_index=True)
    UPMC_locations = pd.concat([UPMC_locations, urgent_cares], ignore_index=True)
    print(UPMC_locations['Facility'].unique())

    competitor_locations = pd.read_excel(competitor_path)

    print("Geocoding UPMC locations...")
    upmc_geocodes = geocode_addresses(UPMC_locations['Address'].tolist(), upmc_geocode_cache)
    upmc_df = build_csv(UPMC_locations, upmc_geocodes, upmc_locs_out)

    print("Geocoding competitor locations...")
    competitor_geocodes = geocode_addresses(competitor_locations['Address'].tolist(), competitor_geocode_cache)
    competitor_df = build_csv(competitor_locations, competitor_geocodes, competitor_locs_out)

    return upmc_df, competitor_df