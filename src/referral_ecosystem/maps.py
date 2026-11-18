import os
import json
import numpy as np
import folium
import branca.colormap as cm
from utils import SPECIALTY_COLORS, MAP_TILES, add_select_all_button


COMPETITOR_COLORS = {
    'AHN': 'darkgreen',
    'WVU': 'lightgray'
}


MAP_ZOOM = 9

# Helper function for adding hospital locations
def add_facility_layers(m, upmc_df, competitor_df):
    """
    Add toggleable facility marker layers to a Folium map.

    Adds four layers: UPMC Hospitals (pin markers), UPMC ASCs (medkit
    markers), UPMC Urgent Cares (circle markers), and Competitors
    (pin markers color-coded by company).

    Parameters
    ----------
    m : folium.Map
        Map instance to add layers to.
    upmc_df : pd.DataFrame
        Must contain columns: Facility, Address, lat, lng.
    competitor_df : pd.DataFrame
        Must contain columns: Company, Address, lat, lng.
    """

    # UPMC hospitals
    fg_hospital = folium.FeatureGroup(name='UPMC Hospitals', show=True)
    for _, row in upmc_df[upmc_df['Facility'] == 'Hospital'].iterrows():
        folium.Marker(
            location=[row['lat'], row['lng']],
            icon=folium.Icon(color='darkpurple', icon='hospital', prefix='fa'),
            tooltip=f"{row['Address']}<br>UPMC Hospital"
        ).add_to(fg_hospital)
    fg_hospital.add_to(m)

    # UPMC ASCs
    fg_asc = folium.FeatureGroup(name='UPMC ASCs', show=True)
    for _, row in upmc_df[upmc_df['Facility'] == 'ASC'].iterrows():
        folium.Marker(
            location=[row['lat'], row['lng']],
            icon=folium.Icon(color='darkpurple', icon='medkit', prefix='fa'),
            tooltip=f"{row['Address']}<br>UPMC ASC"
        ).add_to(fg_asc)
    fg_asc.add_to(m)

    # UPMC urgent cares
    fg_uc = folium.FeatureGroup(name='UPMC Urgent Cares', show=True)
    for _, row in upmc_df[upmc_df['Facility'] == 'Urgent Care'].iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=6,
            color='#800080',
            fill=True,
            fill_color='#e4cae4',
            fill_opacity=0.3,
            weight=4,
            tooltip=f"{row['Address']}<br>UPMC Urgent Care"
        ).add_to(fg_uc)
    fg_uc.add_to(m)

    # competitors
    fg_competitors = folium.FeatureGroup(name='Competitors', show=True)
    for _, row in competitor_df.iterrows():
        color = COMPETITOR_COLORS.get(row['Company'], 'gray')
        folium.Marker(
            location=[row['lat'], row['lng']],
            icon=folium.Icon(color=color, icon='plus-sign'),
            tooltip=f"{row['Address']}<br>{row['Company']}"
        ).add_to(fg_competitors)
    fg_competitors.add_to(m)


def add_specialty_legend(m, specialties_present):
    """
    Add a color-coded specialty legend to the bottom-left of a Folium map.
    Note: there is a function in utils that does this but for the bottom right
    Parameters
    ----------
    m : folium.Map
        Map instance to add the legend to.
    specialties_present : array-like of str
        Specialty names to include; colors sourced from SPECIALTY_COLORS.
    """

    legend_html = '<div style="position:fixed;bottom:30px;left:10px;z-index:9999;background:white;padding:10px;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,0.4);font-size:12px;max-height:400px;overflow-y:auto;">'
    legend_html += '<b>Specialty Colors</b><br>'
    for specialty in sorted(specialties_present):
        color = SPECIALTY_COLORS.get(specialty, 'gray')
        legend_html += f'<i style="background:{color};width:12px;height:12px;display:inline-block;margin-right:5px;"></i>{specialty}<br>'
    legend_html += '</div>'
    m.get_root().html.add_child(folium.Element(legend_html))


def make_specialty_map(Specialty_Volume, map_center, output_path, upmc_df, competitor_df):
    """
    Build a specialty visit volume map with one toggleable layer per specialty.

    Circle marker radius scales with visit volume relative to the maximum
    across all specialties. Saves to HTML.

    Parameters
    ----------
    Specialty_Volume : pd.DataFrame
        Must contain columns: Specialty Grouping, Normalized Address,
        lat, lng, Total_Visits.
    map_center : list of float
        [lat, lng] center for the map.
    output_path : str
        File path to save the HTML map.
    upmc_df : pd.DataFrame
        UPMC facility locations for facility layers.
    competitor_df : pd.DataFrame
        Competitor facility locations for facility layers.
    """

    m = folium.Map(location=map_center, zoom_start=MAP_ZOOM, tiles=MAP_TILES)
    max_visits = Specialty_Volume['Total_Visits'].max()

    for specialty, group_df in Specialty_Volume.groupby('Specialty Grouping'):
        fg = folium.FeatureGroup(name=specialty, show=False)
        color = SPECIALTY_COLORS.get(specialty, 'gray')
        for _, row in group_df.iterrows():
            folium.CircleMarker(
                location=[row['lat'], row['lng']],
                radius=max(5, row['Total_Visits'] / max_visits * 40),
                color=color,
                fill=True,
                fill_opacity=0.7,
                tooltip=f"{row['Normalized Address']}<br>{specialty}: {row['Total_Visits']:,} visits"
            ).add_to(fg)
        fg.add_to(m)

    add_facility_layers(m, upmc_df, competitor_df)
    folium.LayerControl(collapsed=False).add_to(m)
    specialties_present = Specialty_Volume['Specialty Grouping'].unique()
    add_specialty_legend(m, specialties_present)
    add_select_all_button(m)
    m.save(output_path)
    print(f"  Saved: {output_path}")



def make_volume_map(Volume, map_center, output_path, upmc_df, competitor_df):
    """
    Build a total visit and new patient volume map with two toggleable layers.

    Circle marker radius scales with visit volume. Saves to HTML.

    Parameters
    ----------
    Volume : pd.DataFrame
        Must contain columns: Normalized Address, lat, lng,
        Total_Visits, New_Patient_Volume.
    map_center : list of float
        [lat, lng] center for the map.
    output_path : str
        File path to save the HTML map.
    upmc_df : pd.DataFrame
        UPMC facility locations.
    competitor_df : pd.DataFrame
        Competitor facility locations.
    """

    m = folium.Map(location=map_center, zoom_start=MAP_ZOOM, tiles=MAP_TILES)
    max_total = Volume['Total_Visits'].max()

    fg_total = folium.FeatureGroup(name='Total Visits')
    for _, row in Volume.iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=max(3, row['Total_Visits'] / max_total * 20),
            color='steelblue',
            fill=True,
            fill_opacity=0.7,
            tooltip=f"{row['Normalized Address']}<br>Total Visits: {row['Total_Visits']:,}"
        ).add_to(fg_total)
    fg_total.add_to(m)

    fg_new = folium.FeatureGroup(name='New Patient Volume')
    for _, row in Volume.iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=max(3, row['New_Patient_Volume'] / max_total * 20),
            color='darkorange',
            fill=True,
            fill_opacity=0.7,
            tooltip=f"{row['Normalized Address']}<br>New Patients: {row['New_Patient_Volume']:,}"
        ).add_to(fg_new)
    fg_new.add_to(m)

    add_facility_layers(m, upmc_df, competitor_df)
    folium.LayerControl(collapsed=False).add_to(m)
    add_select_all_button(m)
    m.save(output_path)
    print(f"  Saved: {output_path}")



def make_tract_population_map(tract_df, tract_geojson, Volume, map_center, output_path, upmc_df, competitor_df):
    """
    Build a census tract raw population choropleth map with office volume
    markers overlaid.

    Colormap spans from the 25th percentile to the maximum tract population.
    Saves to HTML.

    Parameters
    ----------
    tract_df : pd.DataFrame
        Must contain columns: GEOID, Population.
    tract_geojson : dict
        GeoJSON FeatureCollection for census tracts.
    Volume : pd.DataFrame
        Office visit volumes for overlay markers.
    map_center : list of float
        [lat, lng] center for the map.
    output_path : str
        File path to save the HTML map.
    upmc_df : pd.DataFrame
        UPMC facility locations.
    competitor_df : pd.DataFrame
        Competitor facility locations.
    """

    geojson = json.loads(json.dumps(tract_geojson))

    tract_df = tract_df.copy()
    pop_lookup = dict(zip(tract_df['GEOID'], tract_df['Population']))
    valid_tracts = set(tract_df['GEOID'])
    geojson['features'] = [
        f for f in geojson['features']
        if f['properties']['GEOID'] in valid_tracts
    ]
    for feature in geojson['features']:
        geoid = feature['properties']['GEOID']
        feature['properties']['Population'] = pop_lookup.get(geoid, 0)

    colormap = cm.LinearColormap(
        colors=['yellow', 'orange', 'red'],
        vmin=tract_df['Population'].quantile(0.25),
        vmax=tract_df['Population'].max(),
        caption='Population (Census Tract, 2023)'
    )

    m = folium.Map(location=map_center, zoom_start=MAP_ZOOM, tiles=MAP_TILES)
    colormap.add_to(m)

    fg_heatmap = folium.FeatureGroup(name='Population Heat Map', show=True)
    folium.GeoJson(
        geojson,
        style_function=lambda f, colormap=colormap: {
            'fillColor': colormap(f['properties']['Population']),
            'color': 'black',
            'weight': 0.2,
            'fillOpacity': 0.5
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['Population'],
            aliases=['Population:'],
            localize=True  # adds comma formatting to numbers
        )
    ).add_to(fg_heatmap)
    fg_heatmap.add_to(m)

    fg_offices = folium.FeatureGroup(name='UPMC Offices', show=True)
    for _, row in Volume.iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=6,
            color='darkblue',
            fill=True,
            fill_opacity=0.8,
            tooltip=f"{row['Normalized Address']}<br>Total Visits: {row['Total_Visits']:,}"
        ).add_to(fg_offices)
    fg_offices.add_to(m)

    add_facility_layers(m, upmc_df, competitor_df)


    folium.LayerControl(collapsed=False).add_to(m)
    add_select_all_button(m)
    m.save(output_path)
    print(f"  Saved: {output_path}")


def make_tract_growth_map(growth_df, tract_geojson, Volume, map_center, output_path, upmc_df, competitor_df):
    """
    Build a census tract population percent change choropleth map (2019-2023).

    Colormap is diverging red-white-blue, scaled to the 95th percentile of
    absolute percent change to reduce outlier distortion. Saves to HTML.

    Parameters
    ----------
    growth_df : pd.DataFrame
        Must contain columns: GEOID, Population Change Pct.
    tract_geojson : dict
        GeoJSON FeatureCollection for census tracts.
    Volume : pd.DataFrame
        Office visit volumes for overlay markers.
    map_center : list of float
        [lat, lng] center for the map.
    output_path : str
        File path to save the HTML map.
    upmc_df : pd.DataFrame
        UPMC facility locations.
    competitor_df : pd.DataFrame
        Competitor facility locations.
    """

    geojson = json.loads(json.dumps(tract_geojson))

    growth_df = growth_df.copy()
    growth_df['Population Change Pct'] = growth_df['Population Change Pct'].fillna(0)

    growth_lookup = dict(zip(growth_df['GEOID'], growth_df['Population Change Pct']))
    valid_tracts = set(growth_df['GEOID'])
    geojson['features'] = [
        f for f in geojson['features']
        if f['properties']['GEOID'] in valid_tracts
    ]
    for feature in geojson['features']:
        geoid = feature['properties']['GEOID']
        feature['properties']['Population Change Pct'] = growth_lookup.get(geoid, 0)

    abs_max = growth_df['Population Change Pct'].abs().quantile(0.95)
    if abs_max == 0:
        abs_max = growth_df['Population Change Pct'].abs().max()
    if abs_max == 0:
        abs_max = 1

    colormap = cm.LinearColormap(
        colors=['red', 'white', 'blue'],
        vmin=-abs_max,
        vmax=abs_max,
        caption='Population Change 2019–2023 (%)'
    )

    m = folium.Map(location=map_center, zoom_start=MAP_ZOOM, tiles=MAP_TILES)
    colormap.add_to(m)

    fg_heatmap = folium.FeatureGroup(name='Population Change 2019–2023', show=True)
    folium.GeoJson(
        geojson,
        style_function=lambda f, colormap=colormap: {
            'fillColor': colormap(f['properties'].get('Population Change Pct') or 0),
            'color': 'black',
            'weight': 0.2,
            'fillOpacity': 0.6
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['Population Change Pct'],
            aliases=['Population Change 2019–2023 (%):']
        )
    ).add_to(fg_heatmap)
    fg_heatmap.add_to(m)

    fg_offices = folium.FeatureGroup(name='UPMC Offices', show=True)
    for _, row in Volume.iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=6,
            color='darkblue',
            fill=True,
            fill_opacity=0.8,
            tooltip=f"{row['Normalized Address']}<br>Total Visits: {row['Total_Visits']:,}"
        ).add_to(fg_offices)
    fg_offices.add_to(m)

    add_facility_layers(m, upmc_df, competitor_df)
    folium.LayerControl(collapsed=False).add_to(m)
    add_select_all_button(m)
    m.save(output_path)
    print(f"  Saved: {output_path}")


def make_zip_growth_map(zip_growth_df, zip_geojson, Volume, map_center, output_path, upmc_df, competitor_df):
    """
    Build a zip code population percent change choropleth map (2020-2023).

    Colormap is diverging red-white-blue, scaled to the 70th percentile of
    absolute percent change. Saves to HTML.

    Parameters
    ----------
    zip_growth_df : pd.DataFrame
        Must contain columns: Zip Code, Population Change Pct.
    zip_geojson : dict
        GeoJSON FeatureCollection for zip codes.
    Volume : pd.DataFrame
        Office visit volumes for overlay markers.
    map_center : list of float
        [lat, lng] center for the map.
    output_path : str
        File path to save the HTML map.
    upmc_df : pd.DataFrame
        UPMC facility locations.
    competitor_df : pd.DataFrame
        Competitor facility locations.
    """

    geojson = json.loads(json.dumps(zip_geojson))

    zip_growth_df = zip_growth_df.copy()
    zip_growth_df['Population Change Pct'] = zip_growth_df['Population Change Pct'].fillna(0)

    growth_lookup = dict(zip(zip_growth_df['Zip Code'], zip_growth_df['Population Change Pct']))
    valid_zips = set(zip_growth_df['Zip Code'])

    geojson['features'] = [
        f for f in geojson['features']
        if f['properties']['ZCTA5CE20'] in valid_zips
    ]
    for feature in geojson['features']:
        zcta = feature['properties']['ZCTA5CE20']
        feature['properties']['Population Change Pct'] = growth_lookup.get(zcta, 0)

    abs_max = zip_growth_df['Population Change Pct'].abs().quantile(0.70)
    if abs_max == 0:
        abs_max = zip_growth_df['Population Change Pct'].abs().max()
    if abs_max == 0:
        abs_max = 1

    colormap = cm.LinearColormap(
        colors=['red', 'white', 'blue'],
        vmin=-abs_max,
        vmax=abs_max,
        caption='Population Change 2020–2023 (%)'
    )

    m = folium.Map(location=map_center, zoom_start=MAP_ZOOM, tiles=MAP_TILES)
    colormap.add_to(m)

    fg_heatmap = folium.FeatureGroup(name='Population Change 2020–2023', show=True)
    folium.GeoJson(
        geojson,
        style_function=lambda f, colormap=colormap: {
            'fillColor': colormap(f['properties'].get('Population Change Pct') or 0),
            'color': 'black',
            'weight': 0.2,
            'fillOpacity': 0.6
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['ZCTA5CE20', 'Population Change Pct'],
            aliases=['Zip Code:', 'Population Change 2020–2023 (%):']
        )
    ).add_to(fg_heatmap)
    fg_heatmap.add_to(m)

    fg_offices = folium.FeatureGroup(name='UPMC Offices', show=True)
    for _, row in Volume.iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=6,
            color='darkblue',
            fill=True,
            fill_opacity=0.8,
            tooltip=f"{row['Normalized Address']}<br>Total Visits: {row['Total_Visits']:,}"
        ).add_to(fg_offices)
    fg_offices.add_to(m)

    add_facility_layers(m, upmc_df, competitor_df)
    folium.LayerControl(collapsed=False).add_to(m)
    add_select_all_button(m)
    m.save(output_path)
    print(f"  Saved: {output_path}")


def make_zip_growth_map2(zip_growth_df, zip_geojson, Volume, map_center, output_path, upmc_df, competitor_df):
    from src.referral_ecosystem.three_ecosystems import NORTH_ZIPS, SOUTHWEST_ZIPS, EAST_ZIPS

    geojson = json.loads(json.dumps(zip_geojson))

    zip_growth_df = zip_growth_df.copy()
    zip_growth_df['Population Change Pct'] = zip_growth_df['Population Change Pct'].fillna(0)

    growth_lookup = dict(zip(zip_growth_df['Zip Code'], zip_growth_df['Population Change Pct']))
    valid_zips = set(zip_growth_df['Zip Code'])

    geojson['features'] = [
        f for f in geojson['features']
        if f['properties']['ZCTA5CE20'] in valid_zips
    ]
    for feature in geojson['features']:
        zcta = feature['properties']['ZCTA5CE20']
        feature['properties']['Population Change Pct'] = growth_lookup.get(zcta, 0)

    abs_max = zip_growth_df['Population Change Pct'].abs().quantile(0.70)
    if abs_max == 0:
        abs_max = zip_growth_df['Population Change Pct'].abs().max()
    if abs_max == 0:
        abs_max = 1

    colormap = cm.LinearColormap(
        colors=['red', 'white', 'blue'],
        vmin=-abs_max,
        vmax=abs_max,
        caption='Population Change 2020–2023 (%)'
    )

    m = folium.Map(location=map_center, zoom_start=MAP_ZOOM, tiles=MAP_TILES)
    colormap.add_to(m)

    # Population change choropleth
    fg_heatmap = folium.FeatureGroup(name='Population Change 2020–2023', show=True)
    folium.GeoJson(
        geojson,
        style_function=lambda f, colormap=colormap: {
            'fillColor': colormap(f['properties'].get('Population Change Pct') or 0),
            'color': 'black',
            'weight': 0.2,
            'fillOpacity': 0.6
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['ZCTA5CE20', 'Population Change Pct'],
            aliases=['Zip Code:', 'Population Change 2020–2023 (%):']
        )
    ).add_to(fg_heatmap)
    fg_heatmap.add_to(m)

    # Region boundaries
    ALL_REGION_ZIPS = NORTH_ZIPS | SOUTHWEST_ZIPS | EAST_ZIPS
    region_geojson = json.loads(json.dumps(zip_geojson))
    region_geojson['features'] = [
        f for f in region_geojson['features']
        if f['properties']['ZCTA5CE20'] in ALL_REGION_ZIPS
    ]
    for feature in region_geojson['features']:
        zcta = feature['properties']['ZCTA5CE20']
        if zcta in NORTH_ZIPS:
            feature['properties']['Region'] = 'North (Cranberry-Butler)'
        elif zcta in SOUTHWEST_ZIPS:
            feature['properties']['Region'] = 'Southwest'
        elif zcta in EAST_ZIPS:
            feature['properties']['Region'] = 'East (Irwin-Latrobe)'
        else:
            feature['properties']['Region'] = ''

    fg_regions = folium.FeatureGroup(name='Region Boundaries', show=True)
    folium.GeoJson(
        region_geojson,
        style_function=lambda f: {
            'fillColor': 'transparent',
            'color': '#222222',
            'weight': 3.5,
            'fillOpacity': 0,
            'dashArray': None
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['ZCTA5CE20', 'Region'],
            aliases=['Zip Code:', 'Region:']
        )
    ).add_to(fg_regions)
    fg_regions.add_to(m)

    # UPMC offices
    fg_offices = folium.FeatureGroup(name='UPMC Offices', show=True)
    for _, row in Volume.iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=6,
            color='darkblue',
            fill=True,
            fill_opacity=0.8,
            tooltip=f"{row['Normalized Address']}<br>Total Visits: {row['Total_Visits']:,}"
        ).add_to(fg_offices)
    fg_offices.add_to(m)

    add_facility_layers(m, upmc_df, competitor_df)
    folium.LayerControl(collapsed=False).add_to(m)
    add_select_all_button(m)
    m.save(output_path)
    print(f"  Saved: {output_path}")


def run(Volume, Specialty_Volume, tract_df, tract_geojson, zip_growth_df, maps_dir, upmc_df, competitor_df, zip_geojson, tract_growth_df):
    """
    Generate all five referral ecosystem maps and save to the maps directory.

    Maps produced:
    - Specialty Map: visit volume by specialty
    - Volume Map: total and new patient visit volume
    - Tract Heat Map (Population): census tract raw population
    - Census Tract Growth Map: tract population change 2019-2023
    - Zip Code Population Growth Map: zip population change 2020-2023

    Parameters
    ----------
    Volume : pd.DataFrame
        Aggregated office visit volumes.
    Specialty_Volume : pd.DataFrame
        Office visit volumes broken out by specialty.
    tract_df : pd.DataFrame
        Census tract population data.
    tract_geojson : dict
        GeoJSON for census tracts.
    zip_growth_df : pd.DataFrame
        Zip population growth data.
    maps_dir : str
        Directory path to save HTML map files.
    upmc_df : pd.DataFrame
        UPMC facility locations.
    competitor_df : pd.DataFrame
        Competitor facility locations.
    zip_geojson : dict
        GeoJSON for zip codes.
    tract_growth_df : pd.DataFrame
        Census tract population growth data.
    """

    os.makedirs(maps_dir, exist_ok=True)
    print("\nGenerating maps...")

    map_center = [Volume['lat'].mean(), Volume['lng'].mean()]


    make_specialty_map(
        Specialty_Volume, map_center,
        os.path.join(maps_dir, "Specialty Map.html"),
        upmc_df, competitor_df
    )

    make_volume_map(
        Volume, map_center,
        os.path.join(maps_dir, "Volume Map.html"),
        upmc_df, competitor_df
    )


    make_tract_population_map(
        tract_df, tract_geojson, Volume, map_center,
        os.path.join(maps_dir, "Tract Heat Map (Population).html"),
        upmc_df, competitor_df
    )


    make_tract_growth_map(
        tract_growth_df, tract_geojson, Volume, map_center,
        os.path.join(maps_dir, "Census Tract Growth Map.html"),
        upmc_df, competitor_df
    )


    make_zip_growth_map(
        zip_growth_df, zip_geojson, Volume, map_center,
        os.path.join(maps_dir, "Zip Code Population Growth Map.html"),
        upmc_df, competitor_df
    )

    make_zip_growth_map2(
        zip_growth_df, zip_geojson, Volume, map_center,
        os.path.join(maps_dir, "Zip Code Population Growth Map2.html"),
        upmc_df, competitor_df
    )

    print(f"\nAll maps saved to {maps_dir}")