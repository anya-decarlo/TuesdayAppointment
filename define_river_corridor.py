import geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import split
import numpy as np
import os

def segment_line(line, segment_length_m=1000):
    """
    Segments a Shapely LineString into smaller segments of approximately
    equal length.

    Args:
        line (shapely.geometry.LineString): The line to segment.
        segment_length_m (float): The desired approximate length of each segment in meters.

    Returns:
        list: A list of Shapely LineString objects representing the segments.
    """
    distances = np.arange(0, line.length, segment_length_m)
    if line.length not in distances:
        distances = np.append(distances, line.length)
    
    points = [line.interpolate(d) for d in distances]
    
    if len(points) < 2:
        return [line]

    segments = [LineString([points[i], points[i+1]]) for i in range(len(points)-1)]
    return segments

def define_river_corridor_and_segments():
    """
    Defines a river corridor by buffering a centerline and segments the centerline
    for HMM analysis.

    Returns:
        tuple: (segments_gdf, corridor_gdf)
    """
    print("Step 1: Create the River Centerline (Manual Definition)")
    river_centerline_coords = [
        (-53.446, -11.133), # Shifted eastward
        (-53.416, -11.096)  # Shifted eastward
    ]
    # river_centerline_coords = [
    #     (-53.451, -11.133), 
    #     (-53.421, -11.096)
    # ] # Previous attempt for core area
    # river_centerline_coords = [
    #     (-53.5, -11.5), 
    #     (-52.9, -10.9)
    # ] # Original longer river segment

    river_line = LineString(river_centerline_coords)
    river_gdf = gpd.GeoDataFrame({'id': [1], 'geometry': [river_line]}, crs="EPSG:4326")
    print(f"Initial river line length: {river_gdf.geometry.iloc[0].length:.4f} degrees")

    print("\nStep 2: Reproject to Meters (UTM Zone 22S for this area of Brazil)")
    # Corrected line: Use integer EPSG code
    river_gdf_proj = river_gdf.to_crs(epsg=32722) 
    projected_line = river_gdf_proj.geometry.iloc[0]
    print(f"Projected river line length: {projected_line.length/1000:.2f} km")

    print("\nStep 3: Buffer the River Line to Create 5km-Wide Corridor")
    buffer_distance_m = 2500
    corridor_polygon = projected_line.buffer(buffer_distance_m)
    corridor_gdf = gpd.GeoDataFrame({'id': [1], 'geometry': [corridor_polygon]}, crs=river_gdf_proj.crs)
    print(f"Corridor polygon created with area: {corridor_gdf.geometry.area.iloc[0]/1e6:.2f} sq km")

    print("\nStep 4: Divide River Line Into ~1km Segments")
    segment_length_m = 1000
    segments = segment_line(projected_line, segment_length_m=segment_length_m)
    segments_gdf = gpd.GeoDataFrame({'geometry': segments}, crs=river_gdf_proj.crs)
    segments_gdf.insert(0, 'segment_id', range(len(segments_gdf)))
    print(f"River line divided into {len(segments_gdf)} segments of ~{segment_length_m/1000}km.")

    print("\nStep 5: Tag Each Segment With Its Center Coordinates (Lat/Lon)")
    segments_gdf['centroid_proj'] = segments_gdf.geometry.centroid
    segments_gdf['centroid_latlon'] = segments_gdf['centroid_proj'].to_crs(epsg=4326)
    segments_gdf['lat'] = segments_gdf['centroid_latlon'].y
    segments_gdf['lon'] = segments_gdf['centroid_latlon'].x
    
    segments_gdf = segments_gdf[['segment_id', 'geometry', 'lat', 'lon']]
    print("Centroid coordinates (lat/lon) added to each segment.")

    # Ensure the output directory exists
    # Path is now relative to the script's current location in the main project directory
    output_dir = "gis_outputs"
    os.makedirs(output_dir, exist_ok=True)

    # Save the corridor and segments to GeoJSON files
    corridor_output_path = os.path.join(output_dir, "river_corridor_5km.geojson")
    segments_output_path = os.path.join(output_dir, "river_segments.geojson")

    try:
        corridor_gdf.to_file(corridor_output_path, driver="GeoJSON")
        segments_gdf.to_file(segments_output_path, driver="GeoJSON")
    except Exception as e:
        print(f"Error saving GeoJSON files: {e}")

    print(f"Corridor saved to {os.path.abspath(corridor_output_path)}")
    print(f"Segments saved to {os.path.abspath(segments_output_path)}")

    return segments_gdf, corridor_gdf


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__)) 
    project_root_dir = os.path.dirname(script_dir)
    output_dir = os.path.join(project_root_dir, "gis_outputs")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

    segments_data, corridor_data = define_river_corridor_and_segments()

    print("\n--- Final Segmented River Data (First 5 Rows) ---")
    print(segments_data.head())

    segments_output_path = os.path.join(output_dir, "river_segments.geojson")
    corridor_output_path = os.path.join(output_dir, "river_corridor_5km.geojson")
    
    segments_data_4326 = segments_data.copy()
    if segments_data_4326.crs.to_epsg() != 4326:
        segments_data_4326['geometry'] = segments_data_4326['geometry'].to_crs(epsg=4326)
    segments_data_4326.to_file(segments_output_path, driver="GeoJSON")
    
    corridor_data_4326 = corridor_data.copy()
    if corridor_data_4326.crs.to_epsg() != 4326:
        corridor_data_4326['geometry'] = corridor_data_4326['geometry'].to_crs(epsg=4326)
    corridor_data_4326.to_file(corridor_output_path, driver="GeoJSON")
    
    print(f"\nSegments GeoDataFrame saved to: {segments_output_path}")
    print(f"Corridor GeoDataFrame saved to: {corridor_output_path}")

    print("\n--- Corridor Data ---")
    print(corridor_data.info())
    print(corridor_data.head())

    print("\nScript finished.")