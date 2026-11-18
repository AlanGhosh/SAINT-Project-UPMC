import os
import io
import msoffcrypto
import pandas as pd
import regex as re
import json
import folium

base_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(base_dir, "data")
cache_dir = os.path.join(base_dir, "cache")
maps_dir = os.path.join(base_dir, "maps")
geocode_cache_file = os.path.join(cache_dir, "office_geocodes.json")

MAP_TILES = 'CartoDB positron'

SPECIALTY_COLORS = {
    'Neurosciences': '#e6194b',
    'Pediatrics': '#f58231',
    'Behavioral Health': '#ffe119',
    'Primary Care': '#3cb44b',
    'Rehab & Therapy': '#42d4f4',
    'Oncology': '#4363d8',
    'Gastroenterology': '#911eb4',
    'ENT & Audiology': '#f032e6',
    'Pulmonology': '#a9a9a9',
    'Surgery (General)': '#800000',
    'Urology': '#9a6324',
    'Vision': '#808000',
    'Orthopedics': '#469990',
    'Rheumatology': '#000075',
    'Dermatology': '#e6beff',
    'Cardiology': '#ff4500',
    'OB/GYN': '#ff69b4',
    'Medicine Subspecialties': '#aaffc3',
    'Other': '#dcbeff',
    'Endocrinology': '#ffd8b1',
    'Other/Multi-Specialty': '#c0c0c0'
}

def load_excel() -> pd.DataFrame:
    """
    Interactively prompt the user to select and decrypt a password-protected
    Excel file from the data directory.

    Lists available .xlsx files, prompts for filename and password, decrypts
    using msoffcrypto, and returns the contents as a DataFrame. Loops until
    a valid file and password are provided.

    Returns
    -------
    pd.DataFrame
        Raw contents of the selected Excel file.
    """

    while True:
        xlsx_files = [f for f in os.listdir(data_dir) if f.endswith(".xlsx")]
        if xlsx_files:
            print("\nAvailable .xlsx files in data directory:")
            for f in xlsx_files:
                print(f"  - {f[:-5]}")
        else:
            print("No .xlsx files found in data directory.")

        filename = input("\nEnter Excel file name (without .xlsx extension): ").strip()
        filepath = os.path.join(data_dir, f"{filename}.xlsx")

        if not os.path.exists(filepath):
            print(f"File '{filename}.xlsx' not found. Try again.")
            continue

        password = input("Enter file password: ").strip()

        try:
            decrypted = io.BytesIO()
            with open(filepath, "rb") as f:
                office_file = msoffcrypto.OfficeFile(f)
                office_file.load_key(password=password)
                office_file.decrypt(decrypted)
            decrypted.seek(0)
            df = pd.read_excel(decrypted)
            print(f"Successfully loaded '{filename}.xlsx'.")
            return df
        except Exception as e:
            print(f"Failed: {e}. Try again.")



def geocode_addresses(df: pd.DataFrame) -> pd.DataFrame:
    """
    Geocode unique office addresses in the DataFrame using the Google Maps API.

    Builds a full address string from address component columns, geocodes each
    unique address, and appends lat, lng, and formatted address columns to the
    DataFrame. Results are cached to disk to avoid redundant API calls on
    subsequent runs.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: Dept Address, Dept City, Dept State, Dept Zip.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with added columns: lat, lng, Formatted Address.
    """

    from config import GOOGLE_MAPS_KEY
    import googlemaps
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)

    df = df.copy()
    df['Full Address'] = (
        df['Dept Address'].astype(str) + ', ' +
        df['Dept City'].astype(str) + ', ' +
        df['Dept State'].astype(str) + ' ' +
        df['Dept Zip'].astype(str)
    )

    addresses = df['Full Address'].unique().tolist()

    if os.path.exists(geocode_cache_file):
        print("Geocode cache found. Skipping Google Maps calls.")
        with open(geocode_cache_file, 'r') as f:
            results = json.load(f)
    else:
        print(f"Geocoding {len(addresses)} unique addresses...")
        results = {}
        for addr in addresses:
            try:
                result = gmaps.geocode(addr)
                if result:
                    loc = result[0]['geometry']['location']
                    fmt = result[0]['formatted_address']
                    results[addr] = (loc['lat'], loc['lng'], fmt)
                else:
                    results[addr] = (None, None, None)
                    print(f"  [NOT FOUND] {addr}")
            except Exception as e:
                print(f"  [ERROR] {addr}: {e}")
                results[addr] = (None, None, None)

        with open(geocode_cache_file, 'w') as f:
            json.dump(results, f, indent=4)
        print(f"  Geocoded {len(results)} addresses.")

    df['lat'] = df['Full Address'].map(lambda x: results.get(x, (None, None, None))[0])
    df['lng'] = df['Full Address'].map(lambda x: results.get(x, (None, None, None))[1])
    df['Formatted Address'] = df['Full Address'].map(lambda x: results.get(x, (None, None, None))[2])
    return df


def normalize_address(addr: str) -> str:
    """
    Strip suite numbers, floor designations, room numbers, and similar
    sub-unit qualifiers from an address string.

    Used to consolidate address variants that refer to the same physical
    location (e.g., "123 Main St Suite 4" and "123 Main St") into a
    single canonical form.

    Parameters
    ----------
    addr : str
        Raw address string.

    Returns
    -------
    str
        Address with sub-unit qualifiers removed.
    """

    addr = re.sub(
        r',?\s*(Suite|Ste|#\s*[\w-]+|Rm|Room|Bldg\s*[A-Z]?|\d+(st|nd|rd|th)?\s*[Ff]loor)\s*[\w]*',
        '', str(addr), flags=re.IGNORECASE
    )
    return addr.strip()


def clean_patients(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter patient visit data to face-to-face office visits and map
    Epic department specialties to consolidated specialty groupings.

    Rows where Visit Type Group is not 'Face-to-Face Office Visit' are
    dropped. Epic specialty strings are mapped to ~20 grouped categories
    (e.g., 'Pediatrics', 'Primary Care', 'Cardiology'). Unmapped
    specialties are assigned 'Other/Multi-Specialty'.

    Parameters
    ----------
    df : pd.DataFrame
        Raw patient visit DataFrame. Must contain columns:
        Visit Type Group, Epic Dept Specialty.

    Returns
    -------
    pd.DataFrame
        Filtered DataFrame with added column: Specialty Grouping.
    """


    mapping_dict = {
        # Pediatrics
        'PEDIATRIC ADOLESCENT MED': 'Pediatrics', 'PEDIATRIC ALLERGY': 'Pediatrics',
        'PEDIATRIC AUDIOLOGY': 'Pediatrics', 'PEDIATRIC BEHAVIORAL MED': 'Pediatrics',
        'PEDIATRIC CARDIO THORACIC SURGERY': 'Pediatrics', 'PEDIATRIC CARDIOLOGY': 'Pediatrics',
        'PEDIATRIC CHILD ADVOCACY': 'Pediatrics', 'PEDIATRIC CHILD DEVELOPMENT': 'Pediatrics',
        'PEDIATRIC COMPLEX CARE': 'Pediatrics', 'PEDIATRIC DENTISTRY': 'Pediatrics',
        'PEDIATRIC ENDOCRINOLOGY': 'Pediatrics', 'PEDIATRIC ENT-OTOLARYNGOLOGY': 'Pediatrics',
        'PEDIATRIC GASTROENTEROLOGY': 'Pediatrics', 'PEDIATRIC GENETICS': 'Pediatrics',
        'PEDIATRIC HEMATOLOGY/ONCOLOGY': 'Pediatrics', 'PEDIATRIC HOSPITAL MEDICINE': 'Pediatrics',
        'PEDIATRIC INFECTIOUS DIS': 'Pediatrics', 'PEDIATRIC NEPHROLOGY': 'Pediatrics',
        'PEDIATRIC NEUROLOGY': 'Pediatrics', 'PEDIATRIC NEUROSURGERY': 'Pediatrics',
        'PEDIATRIC NUTRITION': 'Pediatrics', 'PEDIATRIC OCCUPATIONAL THERAPY': 'Pediatrics',
        'PEDIATRIC OPHTHALMOLOGY': 'Pediatrics', 'PEDIATRIC OPTOMETRY': 'Pediatrics',
        'PEDIATRIC ORTHOPEADICS': 'Pediatrics', 'PEDIATRIC PAIN MGMT': 'Pediatrics',
        'PEDIATRIC PHYSIATRY': 'Pediatrics', 'PEDIATRIC PHYSICAL THERAPY': 'Pediatrics',
        'PEDIATRIC PLASTIC SURGERY': 'Pediatrics', 'PEDIATRIC PULMONOLOGY': 'Pediatrics',
        'PEDIATRIC RHEUMATOLOGY': 'Pediatrics', 'PEDIATRIC SPEECH THERAPY': 'Pediatrics',
        'PEDIATRIC SPINA BIFIDA SERVICES': 'Pediatrics', 'PEDIATRIC SURGERY': 'Pediatrics',
        'PEDIATRIC TRANSPLANT SURGERY': 'Pediatrics', 'PEDIATRIC UROLOGY': 'Pediatrics',
        'PEDIATRICS': 'Pediatrics',
        # Primary Care
        'FAMILY MEDICINE': 'Primary Care', 'FAMILY PRACTICE': 'Primary Care',
        'INTERNAL MEDICINE': 'Primary Care', 'GERIATRICS': 'Primary Care',
        # Orthopedics
        'ORTHOPAEDIC SURGERY': 'Orthopedics', 'ORTHOPAEDICS': 'Orthopedics', 'PODIATRY': 'Orthopedics',
        # OB/GYN
        'OB/GYN': 'OB/GYN', 'GYNECOLOGY': 'OB/GYN', 'GYN URO': 'OB/GYN',
        'MATERNAL FETAL MEDICINE': 'OB/GYN', 'REPRODUCTIVE ENDOCRINOLOGY': 'OB/GYN',
        # Behavioral Health
        'BEHAVIORAL HEALTH': 'Behavioral Health', 'BEHAVIORAL MED': 'Behavioral Health',
        'NEUROPSYCHOLOGY': 'Behavioral Health',
        # Dermatology
        'DERMATOLOGY': 'Dermatology',
        # Cardiology
        'CARDIOLOGY': 'Cardiology', 'CARDIAC SURGERY': 'Cardiology',
        # Vision
        'OPHTHALMOLOGY': 'Vision', 'OPTOMETRY': 'Vision',
        # ENT & Audiology
        'ENT-OTOLARYNGOLOGY': 'ENT & Audiology', 'AUDIOLOGY': 'ENT & Audiology',
        # Urology
        'UROLOGY': 'Urology',
        # Rheumatology
        'RHEUMATOLOGY': 'Rheumatology',
        # Pulmonology
        'PULMONOLOGY': 'Pulmonology',
        # Gastroenterology
        'GASTROENTEROLOGY': 'Gastroenterology', 'CENTER FOR LIVER DISEASES': 'Gastroenterology',
        'HEPATOBILIARY SURGERY': 'Gastroenterology',
        # Neurosciences
        'NEUROLOGY': 'Neurosciences', 'NEUROSURGERY': 'Neurosciences',
        # Rehab & Therapy
        'PAIN MANAGEMENT': 'Rehab & Therapy', 'PHYSICAL MEDICINE AND REHAB': 'Rehab & Therapy',
        'PALLIATIVE CARE': 'Rehab & Therapy',
        # Oncology
        'HEMATOLOGY/ONCOLOGY': 'Oncology', 'GYNECOLOGIC ONCOLOGY': 'Oncology',
        'SURGICAL ONCOLOGY/MIXED TUMOR': 'Oncology',
        # Surgery (General)
        'GENERAL SURGERY': 'Surgery (General)', 'PLASTIC SURGERY': 'Surgery (General)',
        'VASCULAR SURGERY': 'Surgery (General)', 'COLON AND RECTAL SURGERY': 'Surgery (General)',
        'BREAST SURGERY': 'Surgery (General)', 'BARIATRIC SURGERY': 'Surgery (General)',
        'THORACIC SURGERY': 'Surgery (General)', 'TRANSPLANT SURGERY': 'Surgery (General)',
        'ENDOCRINE SURGERY': 'Surgery (General)', 'GASTROINTESTINAL SURGERY': 'Surgery (General)',
        'CT TRANSPLANT': 'Surgery (General)',
        # Endocrinology
        'ENDOCRINOLOGY': 'Endocrinology',
        # Medicine Subspecialties
        'INFECTIOUS DISEASES': 'Medicine Subspecialties', 'NEPHROLOGY': 'Medicine Subspecialties',
        'ALLERGY': 'Medicine Subspecialties', 'GENETICS': 'Medicine Subspecialties',
        # Other
        'WOUND CARE': 'Other', 'ANESTHESIOLOGY': 'Other', 'INTERV RAD': 'Other',
        'RADIOLOGY - MRI': 'Other', 'NUTRITION': 'Other', 'MULTI-SPECIALTY': 'Other',
        'MULTIDISCIPLINARY': 'Other', 'NONE': 'Other',
    }

    df = df[df['Visit Type Group'] == 'Face-to-Face Office Visit'].copy()
    df['Specialty Grouping'] = df['Epic Dept Specialty'].map(mapping_dict).fillna('Other/Multi-Specialty')
    return df

def run_data_clean(patients_df: pd.DataFrame):
    """
    Run the full patient data cleaning pipeline: specialty filtering,
    geocoding, address normalization, and new patient volume calculation.

    Parameters
    ----------
    patients_df : pd.DataFrame
        Raw patient visit DataFrame from load_excel().

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame with added columns: Specialty Grouping, lat, lng,
        Formatted Address, Normalized Address, New Patient Volume.
    """

    patients_df = clean_patients(patients_df)
    patients_df = geocode_addresses(patients_df)
    patients_df['Normalized Address'] = patients_df['Formatted Address'].apply(normalize_address)
    patients_df['New Patient Volume'] = patients_df['% of New Patients'] * patients_df['Total Visits']
    return patients_df


def add_select_all_button(m):
    """
    Inject a Select All / Deselect All button into the map HTML that
    toggles all Leaflet layer control checkboxes simultaneously.

    Parameters
    ----------
    m : folium.Map
        Map instance to inject the button into.
    """

    select_all_js = """
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        setTimeout(function() {
            var btns = document.createElement('div');
            btns.style.cssText = 'position:fixed;top:10px;left:60px;z-index:9999;background:white;padding:5px;border-radius:4px;box-shadow:0 1px 5px rgba(0,0,0,0.4);';
            btns.innerHTML = '<button onclick="toggleAll(true)" style="margin-right:4px;cursor:pointer;">Select All</button><button onclick="toggleAll(false)" style="cursor:pointer;">Deselect All</button>';
            document.body.appendChild(btns);
        }, 500);
    });
    function toggleAll(checked) {
        var checkboxes = document.querySelectorAll('.leaflet-control-layers-overlays input[type=checkbox]');
        checkboxes.forEach(function(cb) {
            if (cb.checked !== checked) cb.click();
        });
    }
    </script>
    """
    m.get_root().html.add_child(folium.Element(select_all_js))


def add_specialty_legend(m, specialties_present):
    """
    Add a color-coded specialty legend to the bottom-right of a Folium map.

    Parameters
    ----------
    m : folium.Map
        Map instance to add the legend to.
    specialties_present : array-like of str
        Specialty names to include; colors sourced from SPECIALTY_COLORS.
    """

    legend_html = '<div style="position:fixed;bottom:30px;right:10px;z-index:9999;background:white;padding:10px;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,0.4);font-size:12px;max-height:400px;overflow-y:auto;">'
    legend_html += '<b>Specialty Colors</b><br>'
    for specialty in sorted(specialties_present):
        color = SPECIALTY_COLORS.get(specialty, 'gray')
        legend_html += f'<i style="background:{color};width:12px;height:12px;display:inline-block;margin-right:5px;"></i>{specialty}<br>'
    legend_html += '</div>'
    m.get_root().html.add_child(folium.Element(legend_html))