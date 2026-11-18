import pandas as pd
import os
import numpy as np
import json
import googlemaps
from config import GOOGLE_MAPS_KEY

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
cache_dir = os.path.join(base_dir, "cache")
office_to_asc_cache = os.path.join(cache_dir, "office_to_asc_times.json")
specialty_weights_file = os.path.join(out_dir, "Facility Specialty Weights.csv")
assignment_file = os.path.join(out_dir, "Physician Home Assignment.csv")



def surgeries_data_prep(surgeries_df: pd.DataFrame):
    """
        Prepare surgical case data for home assignment.

        Separates facilities into ASC and Hospital lists, builds a
        surgeon x facility case volume matrix, and computes per-surgeon
        facility counts.

        Parameters
        ----------
        surgeries_df : pd.DataFrame
            Must contain columns: Facility, Facility Type,
            Primary Surgeon NPI, Case Volume.

        Returns
        -------
        doc_location_counts_matrix : pd.DataFrame
            Surgeon x facility case volume pivot table.
        Hospital_names : list of str
            Sorted list of hospital facility names.
        ASC_names : list of str
            Sorted list of ASC facility names.
        """

    type = surgeries_df[['Facility', 'Facility Type']].drop_duplicates().reset_index()

    ASC = type[type['Facility Type'] == 'ASC']
    ASC_names = ASC['Facility'].to_list()
    ASC_names.sort()

    Hospitals = type[type['Facility Type'] == 'Hospital']
    Hospital_names = Hospitals['Facility'].to_list()
    Hospital_names.sort()

    locations = surgeries_df['Facility'].unique()
    locations.sort()

    Current_Facility_Count = surgeries_df.groupby('Primary Surgeon NPI')['Facility'].nunique()
    Current_Facility_Count.sort_index()

    doc_location_counts = surgeries_df.groupby(['Primary Surgeon NPI', 'Facility'])[
        'Case Volume'].sum().reset_index()
    doc_location_counts['Facility'] = pd.Categorical(doc_location_counts['Facility'], categories=locations,
                                                     ordered=True)
    doc_location_counts_matrix = doc_location_counts.pivot(index='Primary Surgeon NPI', columns='Facility',
                                                           values='Case Volume').fillna(0)

    return doc_location_counts_matrix, Hospital_names, ASC_names



def cross_walk_data_prep(surgeries_df: pd.DataFrame, patients_df: pd.DataFrame, crosswalk_df: pd.DataFrame):
    """
        Link surgical NPIs to Epic provider IDs via crosswalk and join to
        patient visit data.

        Surgeons with fewer than 50 total office visits after joining are
        excluded, as insufficient visit data makes office assignment unreliable.

        Parameters
        ----------
        surgeries_df : pd.DataFrame
            Must contain column: Primary Surgeon NPI.
        patients_df : pd.DataFrame
            Cleaned patient visit data; must contain Epic Provider ID,
            Normalized Address, Total Visits.
        crosswalk_df : pd.DataFrame
            Must contain columns: NPI, PROVIDER_CODE.

        Returns
        -------
        pd.DataFrame
            Merged DataFrame linking NPI to office visit locations.
        """

    surgeries_df['Primary Surgeon NPI'] = surgeries_df['Primary Surgeon NPI'].astype(float)
    crosswalk_df['NPI'] = crosswalk_df['NPI'].astype(float)

    merged_df = pd.merge(surgeries_df, crosswalk_df, left_on='Primary Surgeon NPI', right_on='NPI', how='inner')
    providers = merged_df[['Primary Surgeon NPI', 'PROVIDER_CODE']].drop_duplicates()
    df = pd.merge(providers, patients_df, left_on='PROVIDER_CODE', right_on='Epic Provider ID', how='inner')

    physician_totals = df.groupby('Primary Surgeon NPI')['Total Visits'].transform('sum')
    df = df[physician_totals >= 50] # confirm threshold for assignment
    df['Primary Surgeon NPI'] = df['Primary Surgeon NPI'].astype('Int64').astype(str)

    return df



def get_office_to_asc_times(home_office_df: pd.DataFrame, asc_names: list) -> pd.DataFrame:
    """
        Compute drive times in minutes from each physician's home office to
        each ASC using the Google Maps Distance Matrix API.

        Loads ASC coordinates from the existing geocode cache. Results are
        cached to disk.

        Parameters
        ----------
        home_office_df : pd.DataFrame
            Must contain column: Home Office Address.
        asc_names : list of str
            ASC facility names present in the geocode cache.

        Returns
        -------
        pd.DataFrame
            Matrix with office addresses as index, ASC names as columns,
            values in minutes.
        """

    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)

    if os.path.exists(office_to_asc_cache):
        print("Office to ASC cache found. Skipping API call.")
        with open(office_to_asc_cache, 'r') as f:
            return pd.DataFrame(json.load(f)).T

    # Load ASC coordinates from existing cache
    geocode_cache = os.path.join(cache_dir, "physician_deployment_addresses_geocode.json")
    with open(geocode_cache, 'r') as f:
        geocodes = json.load(f)

    asc_coords = {name: geocodes[name] for name in asc_names if name in geocodes}
    asc_coord_list = [asc_coords[name] for name in asc_names if name in asc_coords]
    valid_asc_names = [name for name in asc_names if name in asc_coords]

    # Get unique office addresses that have coordinates
    office_addresses = home_office_df['Home Office Address'].dropna().unique().tolist()

    print(f"Fetching office to ASC travel times for {len(office_addresses)} offices x {len(valid_asc_names)} ASCs...")

    results = {}
    for office in office_addresses:
        try:
            response = gmaps.distance_matrix(
                origins=[office],
                destinations=asc_coord_list,
                mode="driving",
                departure_time="now",
                traffic_model="best_guess"
            )
            if response['status'] == 'OK':
                row = response['rows'][0]['elements']
                results[office] = {
                    asc: el.get('duration_in_traffic', el['duration'])['value'] / 60
                    if el['status'] == 'OK' else None
                    for asc, el in zip(valid_asc_names, row)
                }
            else:
                results[office] = {asc: None for asc in valid_asc_names}
        except Exception as e:
            print(f"  [ERROR] {office}: {e}")
            results[office] = {asc: None for asc in valid_asc_names}

    with open(office_to_asc_cache, 'w') as f:
        json.dump(results, f, indent=4)

    # Return as DataFrame: rows = office addresses, columns = ASC names, values = minutes
    return pd.DataFrame(results).T



def facility_weights(surgeries_df: pd.DataFrame, ASC_names):
    """
        Compute specialty concentration weights for each ASC.

        For each ASC and surgeon specialty, calculates what share of that
        specialty's total system-wide case volume is performed at that ASC.
        Used to determine which ASCs are viable for a given physician's specialty.

        Parameters
        ----------
        surgeries_df : pd.DataFrame
            Must contain columns: Facility, Primary Surgeon Specialty,
            Case Volume.
        ASC_names : list of str
            ASC facility names to include.

        Returns
        -------
        pd.DataFrame
            ASC x specialty concentration matrix, written to CSV.
        """

    all_combinations = pd.MultiIndex.from_product(
        [sorted(surgeries_df['Facility'].unique()), sorted(surgeries_df['Primary Surgeon Specialty'].unique())],
        names=['Facility', 'Primary Surgeon Specialty']
    )

    specialty_total_volume = surgeries_df.groupby('Primary Surgeon Specialty')['Case Volume'].sum()
    specialty_facility_volume = surgeries_df.groupby(['Facility', 'Primary Surgeon Specialty'])['Case Volume'].sum()
    specialty_facility_volume = specialty_facility_volume.reindex(all_combinations, fill_value=0)
    specialty_concentration = specialty_facility_volume.div(specialty_total_volume, level='Primary Surgeon Specialty')

    specialty_matrix = specialty_concentration.reset_index().pivot(
        index='Facility',
        columns='Primary Surgeon Specialty',
        values='Case Volume'
    )
    specialty_matrix = specialty_matrix.loc[ASC_names]
    specialty_matrix.to_csv(specialty_weights_file)

    return specialty_matrix



def hospital_assignment(doc_location_counts_matrix, ASC_names):
    """
        Assign each surgeon a home hospital based on highest case volume share.

        Parameters
        ----------
        doc_location_counts_matrix : pd.DataFrame
            Surgeon x facility case volume matrix from surgeries_data_prep().
        ASC_names : list of str
            ASC names to exclude from hospital volume calculation.

        Returns
        -------
        Home_Hospital : pd.Series
            Home hospital name per surgeon NPI.
        Max_Hospital_Percent : pd.Series
            Volume share (%) at home hospital per surgeon.
        Hospital_Count : pd.Series
            Number of distinct hospitals used per surgeon.
        """

    doc_hospital_matrix = doc_location_counts_matrix.drop(columns=ASC_names)
    doc_hospital_matrix_percent = doc_hospital_matrix.div(doc_hospital_matrix.sum(axis=1), axis=0).fillna(0) * 100
    doc_hospital_matrix_percent.sort_index()
    Home_Hospital = doc_hospital_matrix_percent.idxmax(axis=1).where(doc_hospital_matrix_percent.max(axis=1) > 0, None)
    Max_Hospital_Percent = doc_hospital_matrix_percent.max(axis=1).round(1)
    Hospital_Count = (doc_hospital_matrix > 0).sum(axis=1)

    return Home_Hospital, Max_Hospital_Percent, Hospital_Count



def office_assignment(combined_df: pd.DataFrame):
    """
        Assign each surgeon a home office address based on highest total
        visit volume across linked office locations.

        Parameters
        ----------
        combined_df : pd.DataFrame
            Output of cross_walk_data_prep(); must contain Primary Surgeon NPI,
            Normalized Address, Total Visits.

        Returns
        -------
        max_address_per_surgeon : pd.DataFrame
            Home Office Address and Max Office Percent per surgeon NPI.
        Office_Count : pd.Series
            Number of distinct office locations per surgeon.
        """

    office_visits = combined_df.groupby(['Primary Surgeon NPI', 'Normalized Address'])['Total Visits'].sum().reset_index()
    max_address_per_surgeon = office_visits.loc[office_visits.groupby('Primary Surgeon NPI')['Total Visits'].idxmax()]
    total_visits_per_surgeon = office_visits.groupby('Primary Surgeon NPI')['Total Visits'].sum()

    max_address_per_surgeon = max_address_per_surgeon.copy()
    max_address_per_surgeon['Max Office Percent'] = (
            max_address_per_surgeon['Total Visits'] /
            max_address_per_surgeon['Primary Surgeon NPI'].map(total_visits_per_surgeon) * 100
    ).round(1)

    max_address_per_surgeon = max_address_per_surgeon.drop(columns='Total Visits')
    max_address_per_surgeon.rename(columns={'Normalized Address': 'Home Office Address'}, inplace=True)
    max_address_per_surgeon = max_address_per_surgeon.set_index('Primary Surgeon NPI').sort_index()

    Office_Count = office_visits.groupby('Primary Surgeon NPI')['Normalized Address'].nunique()

    return max_address_per_surgeon, Office_Count


def asc_assignment(doc_location_counts_matrix, Hospital_names, ASC_names, assignment_df, specialty_matrix,
                   physician_specialty, home_office_df):
    """
        Assign each surgeon a home ASC using one of two methods depending
        on their facility tier.

        Tier classification is based on which combination of Hospital, Office,
        and ASC usage a surgeon has. Assignment logic:
        - Office Proximity: used when the surgeon has a home office; picks the
          viable ASC closest in drive time to that office.
        - Historical Volume: used when no home office exists; picks the viable
          ASC with the highest historical case volume share.

        Viable ASCs are those with non-zero specialty concentration for the
        surgeon's specialty per facility_weights().

        Parameters
        ----------
        doc_location_counts_matrix : pd.DataFrame
            Surgeon x facility case volume matrix.
        Hospital_names : list of str
            Hospital facility names.
        ASC_names : list of str
            ASC facility names.
        assignment_df : pd.DataFrame
            Partial assignment DataFrame with Home Hospital and Home Office Address.
        specialty_matrix : pd.DataFrame
            ASC x specialty concentration from facility_weights().
        physician_specialty : pd.Series
            Primary specialty per surgeon NPI.
        home_office_df : pd.DataFrame
            Home office assignments from office_assignment().

        Returns
        -------
        Home_ASC : pd.Series
            Home ASC name per surgeon NPI.
        Max_ASC_Percent : pd.Series
            Volume share (%) at home ASC per surgeon.
        ASC_Count : pd.Series
            Number of distinct ASCs used per surgeon.
        Tier : pd.Series
            Facility tier label per surgeon.
        """


    # Normalize all indices to string
    doc_location_counts_matrix = doc_location_counts_matrix.copy()
    doc_location_counts_matrix.index = doc_location_counts_matrix.index.astype(str)

    has_hospital = assignment_df['Home Hospital'].notna()
    has_office = assignment_df['Home Office Address'].notna()
    has_asc = (doc_location_counts_matrix[ASC_names] > 0).any(axis=1)
    has_asc = has_asc.reindex(assignment_df.index, fill_value=False)

    conditions = [
        has_hospital & has_office & has_asc,
        has_hospital & has_office & ~has_asc,
        has_hospital & ~has_office & has_asc,
        has_hospital & ~has_office & ~has_asc,
        ~has_hospital & has_office & has_asc,
        ~has_hospital & has_office & ~has_asc,
        ~has_hospital & ~has_office & has_asc,
    ]
    labels = [
        'Hospital + Office + ASC',
        'Hospital + Office',
        'Hospital + ASC',
        'Hospital Only',
        'ASC + Office',
        'Office Only',
        'ASC Only',
    ]
    assignment_df = assignment_df.copy()
    assignment_df['Tier'] = np.select(conditions, labels, default='Unknown')

    # ASC volume matrix (drop hospital columns)
    doc_asc_matrix = doc_location_counts_matrix.drop(columns=Hospital_names)
    doc_asc_matrix.index = doc_asc_matrix.index.astype(str).str.replace('.0', '', regex=False)
    doc_asc_matrix_percent = doc_asc_matrix.div(doc_asc_matrix.sum(axis=1), axis=0).fillna(0) * 100
    ASC_Count = (doc_asc_matrix > 0).sum(axis=1)

    # Get office-to-ASC travel times
    office_to_asc_times = get_office_to_asc_times(home_office_df, ASC_names)

    Home_ASC = pd.Series(index=assignment_df.index, dtype=object)
    Max_ASC_Percent = pd.Series(index=assignment_df.index, dtype=float)

    for npi in assignment_df.index:
        tier = assignment_df.loc[npi, 'Tier']

        # Look up specialty per NPI
        specialty_for_npi = physician_specialty.get(npi)
        if isinstance(specialty_for_npi, pd.Series):
            specialty_for_npi = specialty_for_npi.iloc[0]

        # Get ASCs that offer this physician's specialty (non-zero concentration)
        if specialty_for_npi and specialty_for_npi in specialty_matrix.columns:
            viable_ascs = specialty_matrix[specialty_matrix[specialty_for_npi] > 0].index.tolist()
        else:
            viable_ascs = ASC_names

        if not viable_ascs:
            viable_ascs = ASC_names  # fallback if no ASC offers specialty

        if tier in ('Hospital + Office + ASC', 'ASC + Office'):
            # Office-driven: pick closest viable ASC to home office
            home_office = assignment_df.loc[npi, 'Home Office Address']
            valid_viable = [a for a in viable_ascs if a in office_to_asc_times.columns]
            if not valid_viable:
                valid_viable = office_to_asc_times.columns.tolist()
            if home_office and home_office in office_to_asc_times.index:
                times = office_to_asc_times.loc[home_office, valid_viable].dropna()
                if not times.empty:
                    Home_ASC[npi] = times.idxmin()
                    Max_ASC_Percent[npi] = doc_asc_matrix_percent.loc[
                        npi, Home_ASC[npi]] if npi in doc_asc_matrix_percent.index else 0
                else:
                    Home_ASC[npi] = None
                    Max_ASC_Percent[npi] = 0
            else:
                Home_ASC[npi] = None
                Max_ASC_Percent[npi] = 0

        elif tier in ('Hospital + ASC', 'ASC Only'):
            # Volume-driven: pick highest volume viable ASC
            valid_viable = [a for a in viable_ascs if a in doc_asc_matrix_percent.columns]
            if not valid_viable:
                valid_viable = doc_asc_matrix_percent.columns.tolist()
            if npi in doc_asc_matrix_percent.index:
                viable_pcts = doc_asc_matrix_percent.loc[npi, valid_viable]
                if viable_pcts.max() > 0:
                    Home_ASC[npi] = viable_pcts.idxmax()
                    Max_ASC_Percent[npi] = viable_pcts.max()
                else:
                    Home_ASC[npi] = None
                    Max_ASC_Percent[npi] = 0
            else:
                Home_ASC[npi] = None
                Max_ASC_Percent[npi] = 0

        else:
            # Hospital Only, Hospital + Office, Office Only, Unknown — no ASC
            Home_ASC[npi] = None
            Max_ASC_Percent[npi] = 0

    Max_ASC_Percent = Max_ASC_Percent.round(1)

    return Home_ASC, Max_ASC_Percent, ASC_Count, assignment_df['Tier']


def run(surgeries_df: pd.DataFrame, patients_df: pd.DataFrame, crosswalk_df: pd.DataFrame):
    """
        Execute the full physician home assignment pipeline.

        Assigns each surgeon a home hospital, home office, and home ASC based
        on historical case and visit volume data. Writes results to CSV.

        Parameters
        ----------
        surgeries_df : pd.DataFrame
            Surgical case data.
        patients_df : pd.DataFrame
            Cleaned patient visit data.
        crosswalk_df : pd.DataFrame
            NPI-to-Epic provider ID crosswalk.

        Returns
        -------
        pd.DataFrame
            One row per surgeon NPI with columns: Specialty, Home Hospital,
            Hospital Volume %, Hospital Count, Home Office Address,
            Office Volume %, Office Count, Home ASC, ASC Volume %,
            ASC Count, Tier, ASC Assignment Method.
        """

    # data prep
    doc_location_counts_matrix, Hospital_names, ASC_names = surgeries_data_prep(surgeries_df)
    combined_df = cross_walk_data_prep(surgeries_df, patients_df, crosswalk_df)
    specialty_matrix = facility_weights(surgeries_df, ASC_names)

    # Normalize physician_specialty index to string
    physician_specialty = surgeries_df.groupby('Primary Surgeon NPI')['Primary Surgeon Specialty'].first()
    physician_specialty.index = physician_specialty.index.astype(str)
    physician_specialty = physician_specialty[~physician_specialty.index.duplicated(keep='first')]

    # home office and hospital assignment
    home_office_df, Office_Count = office_assignment(combined_df)
    Home_Hospital, Max_Hospital_Percent, Hospital_Count = hospital_assignment(doc_location_counts_matrix, ASC_names)

    # Normalize all indices to string
    Home_Hospital.index = Home_Hospital.index.astype(str)
    Max_Hospital_Percent.index = Max_Hospital_Percent.index.astype(str)
    Hospital_Count.index = Hospital_Count.index.astype(str)
    all_NPIs = Home_Hospital.index

    home_office_df = home_office_df.reindex(all_NPIs)

    assignment_df = home_office_df.join(pd.DataFrame({
        'Home Hospital': Home_Hospital,
        'Max Hospital Percent': Max_Hospital_Percent
    }))

    Home_ASC, Max_ASC_Percent, ASC_Count, assignment_df['Tier'] = asc_assignment(
        doc_location_counts_matrix,
        Hospital_names,
        ASC_names,
        assignment_df,
        specialty_matrix,
        physician_specialty,
        home_office_df
    )

    # Normalize remaining indices
    Office_Count.index = Office_Count.index.astype(str)
    ASC_Count.index = ASC_Count.index.astype(str)

    Office_Count = Office_Count.reindex(all_NPIs, fill_value=0)
    ASC_Count = ASC_Count.reindex(all_NPIs, fill_value=0)
    Hospital_Count = Hospital_Count.reindex(all_NPIs, fill_value=0)

    Home_Assignment = pd.DataFrame({
        'Specialty': physician_specialty.reindex(all_NPIs),
        'Home Hospital': Home_Hospital,
        'Hospital Volume %': Max_Hospital_Percent,
        'Hospital Count': Hospital_Count,
        'Home Office Address': assignment_df['Home Office Address'],
        'Office Volume %': assignment_df['Max Office Percent'],
        'Office Count': Office_Count,
        'Home ASC': Home_ASC,
        'ASC Volume %': Max_ASC_Percent,
        'ASC Count': ASC_Count,
        'Tier': assignment_df['Tier']
    }, index=all_NPIs)

    Home_Assignment['ASC Assignment Method'] = Home_Assignment['Tier'].map({
        'Hospital + Office + ASC': 'Office Proximity',
        'ASC + Office': 'Office Proximity',
        'Hospital + ASC': 'Historical Volume',
        'ASC Only': 'Historical Volume'
    }).fillna('N/A')

    Home_Assignment.index.name = 'Primary Surgeon NPI'
    Home_Assignment = Home_Assignment.sort_index()

    Home_Assignment.to_csv(assignment_file)
    print("Physician home assignment completed")

    return Home_Assignment