import os
import pandas as pd

from src.physician_deployment import (
    windshield_baseline,
    distance_matrix_generator,
    home_assignment,
    new_baseline
)

import utils

base_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
cache_dir = os.path.join(base_dir, "cache")
durations_file = os.path.join(out_dir, "Physician Durations Matrix.csv")
distances_file = os.path.join(out_dir, "Physicians Distance Matrix.csv")
normalized_distances_file = os.path.join(out_dir, "Physicians Normalized Distances Matrix.csv")


if __name__ == "__main__":
    print("For physician deployment optimization, you need 3 Excel files.\nPlease select the surgical data Excel file first.")
    surgeries_df = utils.load_excel()
    surgeries_df = surgeries_df[pd.to_numeric(surgeries_df['Primary Surgeon NPI'], errors='coerce').notna()]
    surgeries_df = surgeries_df[surgeries_df.groupby('Primary Surgeon NPI')['Case Volume'].transform('sum') >= 30]

    print("Next, select the crosswalk Excel file. This links surgeon NPIs to their Epic ID.")
    crosswalk_df = utils.load_excel()

    print("Lastly, patient volume by location Excel file.")
    patients_df = utils.load_excel()
    patients_df = utils.run_data_clean(patients_df)

    # Google Maps API distance and time matrix generation
    df_dur, df_dist, normalized = distance_matrix_generator.run(surgeries_df)

    if not os.path.exists(durations_file):
        print(f"\nOutputs written:")
        print(f"  {durations_file}")
        df_dur.to_csv(durations_file, index=False)
        print(f"  {distances_file}")
        df_dist.to_csv(distances_file, index=False)
        print(f"  {normalized_distances_file}")
        normalized.to_csv(normalized_distances_file, index=False)
    else:
        print("Distance and duration matrices already exist. Skipping save..")

    # Establish intraday windshield time baseline
    windshield_df = windshield_baseline.run(surgeries_df, df_dur, df_dist)

    # Establish home offices, ASCs, and hospitals for each physician
    # Establish weightings for each location
    assignment_df = home_assignment.run(surgeries_df, patients_df, crosswalk_df)

    # Establish new baseline
    new_baseline.run(windshield_df, assignment_df, df_dur, df_dist)