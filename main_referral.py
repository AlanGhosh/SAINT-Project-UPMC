import os
import json
import pandas as pd

from src.referral_ecosystem import census_data, maps
import utils
from src.referral_ecosystem import locations, analysis, ecosystem_map, three_ecosystems

base_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
cache_dir = os.path.join(base_dir, "cache")
maps_dir = os.path.join(base_dir, "maps")
office_out = os.path.join(out_dir, "Office Data with Coordinates.csv")
volume_out = os.path.join(out_dir, "Office Volume Data.csv")
specialty_volume_out = os.path.join(out_dir, "Office Volume by Specialty.csv")


if __name__ == "__main__":
    os.makedirs(maps_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    print("Please select patient visits Excel file.")
    patients_df = utils.load_excel()

    patients_df = utils.run_data_clean(patients_df)

    patients_df.to_csv(office_out, index=False)
    print(f"UPMC office visit data saved to {office_out}")


    upmc_df, competitor_df = locations.run()


    # Aggregate volume and specialty data for maps
    Volume = patients_df.groupby('Normalized Address').agg(
        lat=('lat', 'first'),
        lng=('lng', 'first'),
        Total_Visits=('Total Visits', 'sum'),
        New_Patient_Volume=('New Patient Volume', 'sum')
    ).reset_index()

    Specialty_Volume = patients_df.groupby(['Normalized Address', 'Specialty Grouping']).agg(
        lat=('lat', 'first'),
        lng=('lng', 'first'),
        Total_Visits=('Total Visits', 'sum')
    ).reset_index()


    Volume.to_csv(volume_out, index=False)
    print(f"Office volume data saved to {volume_out}")


    Specialty_Volume.to_csv(specialty_volume_out, index=False)
    print(f"Office volume by specialty data saved to {specialty_volume_out}")



    # Census data
    tract_df, tract_geojson, target_zips, zip_population, zip_growth_df, zip_geojson, zip_centroids, tract_growth_df = census_data.run(patients_df)


    # Generate maps
    maps.run(Volume, Specialty_Volume, tract_df, tract_geojson, zip_growth_df, maps_dir, upmc_df, competitor_df, zip_geojson, tract_growth_df)


    # Analysis
    uc_routing, pc_routing, urgent_cares_filtered = analysis.run(upmc_df, patients_df, target_zips, zip_population, zip_centroids)


    # Final ecosystem map
    map_center = [uc_routing['UC lat'].dropna().mean(), uc_routing['UC lng'].dropna().mean()]
    ecosystem_map.make_ecosystem_routing_map(uc_routing, pc_routing, map_center)


    # Final 3 Ecosystems
    three_ecosystems.make_three_maps(uc_routing, pc_routing, patients_df, urgent_cares_filtered, zip_geojson)