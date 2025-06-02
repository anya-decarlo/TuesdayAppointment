import geopandas as gpd
from shapely.geometry import box
import pdal
import json
import os
import glob

def get_laz_bounds_and_crs(laz_file_path):
    """
    Reads a .laz file to extract its bounding box and CRS information using PDAL.

    Args:
        laz_file_path (str): Path to the .laz file.

    Returns:
        tuple: (bounds, crs_epsg_code)
               bounds (dict): {'minx': minx, 'miny': miny, 'maxx': maxx, 'maxy': maxy}
               crs_epsg_code (str or None): EPSG code as string (e.g., "EPSG:4326") or None if not found/parsable.
    """
    try:
        # Create a PDAL pipeline to read metadata
        pipeline_dict = {
            "pipeline": [
                {
                    "type": "readers.las",
                    "filename": laz_file_path
                },
                {
                    "type": "filters.info" # Not strictly necessary for bounds/crs but good for general metadata
                }
            ]
        }
        pipeline_json = json.dumps(pipeline_dict)
        
        pipeline = pdal.Pipeline(pipeline_json)
        # pipeline.validate() # Check if the pipeline is valid - REMOVED as it causes AttributeError
        count = pipeline.execute() # Execute the pipeline to populate metadata
        
        metadata = pipeline.metadata # Directly use the metadata object, likely already a dict
        
        # Extract bounds
        # PDAL metadata structure can vary slightly; common paths are checked.
        if 'metadata' in metadata and 'readers.las' in metadata['metadata']: # PDAL 2.3+
            reader_info_obj = metadata['metadata']['readers.las']

            if isinstance(reader_info_obj, list):
                if reader_info_obj: # Check if list is not empty
                    las_metadata = reader_info_obj[0]
                else:
                    print(f"Warning: 'readers.las' metadata for {laz_file_path} is an empty list.")
                    return None, None
            elif isinstance(reader_info_obj, dict):
                las_metadata = reader_info_obj # Use the dict directly
            else:
                print(f"Warning: 'readers.las' metadata for {laz_file_path} is neither a list nor a dict. Type: {type(reader_info_obj)}")
                return None, None
        elif 'stages' in metadata and 'readers.las' in metadata['stages']: # Older PDAL
             # Find the readers.las stage metadata
            las_info_list = [s for s in metadata['stages'] if s.get('type') == 'readers.las' or s.get('tag') == 'readers.las']
            if not las_info_list:
                 print(f"Warning: Could not find 'readers.las' metadata stage for {laz_file_path}")
                 return None, None
            las_metadata = las_info_list[0] # Take the first one
        else: # Try root level for some PDAL versions or if only one reader
            las_metadata = metadata

        bounds_dict = {}
        # Check for different ways bounds might be stored
        if 'bbox' in las_metadata: # Common in recent PDAL versions
            bbox_data = las_metadata['bbox']
            if 'minx' in bbox_data and 'maxx' in bbox_data and 'miny' in bbox_data and 'maxy' in bbox_data:
                 bounds_dict = {
                    'minx': bbox_data['minx'], 'miny': bbox_data['miny'],
                    'maxx': bbox_data['maxx'], 'maxy': bbox_data['maxy']
                }
        # Fallback to older/different metadata structures if 'bbox' isn't there or incomplete
        if not bounds_dict and all(k in las_metadata for k in ['minx', 'miny', 'maxx', 'maxy']):
            bounds_dict = {
                'minx': las_metadata['minx'], 'miny': las_metadata['miny'],
                'maxx': las_metadata['maxx'], 'maxy': las_metadata['maxy']
            }
        elif not bounds_dict and 'summary' in las_metadata and 'bounds' in las_metadata['summary']: # Another common place
             b = las_metadata['summary']['bounds']
             bounds_dict = {
                'minx': b['minx'], 'miny': b['miny'],
                'maxx': b['maxx'], 'maxy': b['maxy']
            }

        if not bounds_dict:
            print(f"Warning: Could not extract bounds for {laz_file_path} from metadata: {las_metadata}")
            return None, None

        # Extract CRS
        srs_data = las_metadata.get('srs', {})
        wkt = srs_data.get('wkt', None)
        proj4 = srs_data.get('proj4', None)
        crs_epsg_code = None

        if wkt and wkt.strip():
            # Try to parse EPSG from WKT (this is a simplified approach)
            # A more robust way would use pyproj or rasterio.crs.CRS.from_wkt(wkt).to_epsg()
            # but that adds more dependencies if not already used.
            # For now, let's see if PDAL gives an EPSG directly or if WKT contains it.
            if "AUTHORITY[\"EPSG\"" in wkt:
                try:
                    epsg_val = wkt.split("AUTHORITY[\"EPSG\",\"")[1].split("\"]")[0]
                    crs_epsg_code = f"EPSG:{epsg_val}"
                except IndexError:
                    print(f"Could not parse EPSG from WKT for {laz_file_path}: {wkt[:100]}...") # Print start of WKT
            if not crs_epsg_code and srs_data.get('authority') == 'EPSG' and srs_data.get('horizontal'):
                crs_epsg_code = f"EPSG:{srs_data['horizontal']}"

        if not crs_epsg_code and proj4 and "epsg" in proj4.lower():
             # Attempt to extract from proj4 if it contains an EPSG code
            try:
                # Example: +init=epsg:4326
                epsg_part = [p for p in proj4.split() if "epsg" in p.lower()][0]
                crs_epsg_code = epsg_part.split(':')[1].upper()
                if not crs_epsg_code.startswith("EPSG:"):
                    crs_epsg_code = f"EPSG:{crs_epsg_code}"
            except Exception as e:
                print(f"Could not parse EPSG from proj4 string '{proj4}' for {laz_file_path}: {e}")


        if crs_epsg_code:
            print(f"Found CRS {crs_epsg_code} for {laz_file_path}")
        else:
            print(f"Warning: No parsable EPSG code found for {laz_file_path}. WKT: {wkt[:100] if wkt else 'N/A'}, Proj4: {proj4 if proj4 else 'N/A'}")
            
        return bounds_dict, crs_epsg_code

    except Exception as e:
        print(f"Error processing {laz_file_path} with PDAL. Exception Type: {type(e)}, Exception Repr: {repr(e)}, Exception Str: {str(e)}")
        # Optionally, re-raise if you want to halt on first error or debug interactively
        # raise
        return None, None

def match_lidar_to_segments(segments_geojson_path, lidar_data_dir, output_geojson_path, target_segment_crs="EPSG:32722"):
    """
    Matches LiDAR data files to river segments based on spatial intersection.

    Args:
        segments_geojson_path (str): Path to the GeoJSON file containing river segments.
        lidar_data_dir (str): Directory containing .laz LiDAR files.
        output_geojson_path (str): Path to save the augmented segments GeoJSON.
        target_segment_crs (str): The CRS of the river segments (and the target CRS for LiDAR bounds).
    """
    print(f"Loading river segments from: {segments_geojson_path}")
    segments_gdf = gpd.read_file(segments_geojson_path)
    if segments_gdf.crs is None:
        print(f"Warning: Segments GeoDataFrame has no CRS. Assuming {target_segment_crs}.")
        segments_gdf.crs = target_segment_crs
    elif segments_gdf.crs.to_string().upper() != target_segment_crs.upper():
        print(f"Reprojecting segments from {segments_gdf.crs} to {target_segment_crs}")
        segments_gdf = segments_gdf.to_crs(target_segment_crs)
    
    print(f"Scanning LiDAR files in {lidar_data_dir}...")

    lidar_bounds_data = []
    processed_files_count = 0
    assumed_native_crs_count = 0 # Count files assumed to be in target_segment_crs

    for laz_file in glob.glob(os.path.join(lidar_data_dir, "*.laz")):
        print(f"Processing LiDAR file: {os.path.basename(laz_file)}")
        bounds, laz_crs_epsg = get_laz_bounds_and_crs(laz_file)

        if bounds:
            bbox_polygon = box(bounds['minx'], bounds['miny'], bounds['maxx'], bounds['maxy'])
            file_data = {'file_path': laz_file, 'geometry': bbox_polygon}

            if laz_crs_epsg:
                # If CRS is found in LAZ, create GeoSeries and reproject
                gs_temp = gpd.GeoSeries([bbox_polygon], crs=laz_crs_epsg)
                gs_reprojected = gs_temp.to_crs(target_segment_crs)
                file_data['geometry'] = gs_reprojected.iloc[0]
                print(f"Found CRS {laz_crs_epsg} for {os.path.basename(laz_file)}. Reprojected to {target_segment_crs}.")
            else:
                # If NO CRS is found, assume coordinates are ALREADY in target_segment_crs
                # No reprojection needed, geometry is already in target_segment_crs
                # The GeoDataFrame for lidar_gdf will be created with target_segment_crs later
                print(f"WARNING: No CRS found for {os.path.basename(laz_file)}. Assuming coordinates are already in {target_segment_crs}.")
                assumed_native_crs_count += 1
            
            lidar_bounds_data.append(file_data)
            processed_files_count += 1
        else:
            print(f"Skipping {os.path.basename(laz_file)} due to missing bounds or read error.")

    if not lidar_bounds_data:
        print("No LiDAR file bounds could be processed. Exiting.")
        return

    print(f"\nSuccessfully processed {processed_files_count} LiDAR file(s).")
    if assumed_native_crs_count > 0:
        print(f"IMPORTANT SUMMARY: Assumed coordinates for {assumed_native_crs_count} LiDAR file(s) were already in {target_segment_crs} due to missing embedded CRS information.")

    # Create GeoDataFrame for LiDAR bounds, explicitly setting CRS to target_segment_crs
    # This is correct because if laz_crs_epsg was found, we reprojected to target_segment_crs.
    # If laz_crs_epsg was NOT found, we are now assuming the coordinates were already in target_segment_crs.
    lidar_gdf = gpd.GeoDataFrame(lidar_bounds_data, crs=target_segment_crs)

    print("\n--- Pre-Join Diagnostics ---")
    print(f"Segments GDF CRS: {segments_gdf.crs}")
    print(f"Segments GDF total bounds: {segments_gdf.total_bounds}")
    print(f"LiDAR GDF CRS: {lidar_gdf.crs}")
    print(f"LiDAR GDF total bounds: {lidar_gdf.total_bounds}")
    print("---------------------------\n")

    # --- Add Plotting for Debugging ---
    try:
        import matplotlib.pyplot as plt
        output_dir_for_plot = os.path.dirname(output_geojson_path)
        plot_filename = os.path.join(output_dir_for_plot, "debug_spatial_join_preview.png")
        
        print(f"Attempting to plot segments and LiDAR bounds to {plot_filename}...")
        fig, ax = plt.subplots(1, 1, figsize=(12, 12))
        
        segments_gdf.plot(ax=ax, color='blue', edgecolor='black', linewidth=0.5, label='River Segments', zorder=2)
        lidar_gdf.plot(ax=ax, color='red', edgecolor='darkred', alpha=0.4, label='LiDAR Tiles', zorder=1)
        
        # Optionally, set plot limits to the union of both total bounds for a better view
        # Or, focus on the area of the LiDAR data if segments are much larger
        # For now, let geopandas/matplotlib decide the extent based on data

        ax.set_title("River Segments and LiDAR Tile Bounding Boxes (EPSG:32722)")
        ax.set_xlabel("Easting (meters)")
        ax.set_ylabel("Northing (meters)")
        ax.legend()
        plt.savefig(plot_filename)
        print(f"Saved debug plot to {plot_filename}")
        # plt.show() # Uncomment for interactive display if running locally and not on a headless server
    except ImportError:
        print("Matplotlib not found. Skipping debug plot. Please install matplotlib to enable plotting.")
    except Exception as e:
        print(f"Error during plotting: {e}. Skipping debug plot.")
    # --- End Plotting ---

    print("Performing spatial join between segments and LiDAR file bounds...")
    # Use 'intersects' to find any overlap. Consider 'within' if segments should be fully within tiles.
    # op='intersects' is generally good for finding relevant tiles.
    joined_gdf = gpd.sjoin(segments_gdf, lidar_gdf, how="left", predicate="intersects") 

    print("Aggregating LiDAR file paths for each segment...")
    # Group by segment attributes (use index if segment_id is unique and index)
    # Ensure all original segment columns are preserved
    segment_cols = segments_gdf.columns.tolist()
    if 'index_right' in joined_gdf.columns: # Column added by sjoin
        segment_cols_for_grouping = [col for col in segment_cols if col in joined_gdf.columns]
    else: # Should not happen if join occurred
        segment_cols_for_grouping = segment_cols

    # Handle cases where a segment might not intersect any LiDAR file (file_path will be NaN)
    def aggregate_files(series):
        # Filter out NaNs which occur if a segment has no intersecting LiDAR files
        valid_files = series.dropna().unique().tolist()
        return valid_files if valid_files else None # Return None or [] as preferred

    # Group by the original segment's index to ensure one row per original segment
    aggregated_lidar_info = joined_gdf.groupby(joined_gdf.index)['file_path'].apply(aggregate_files).rename('lidar_file_paths')
    
    # Merge the aggregated file paths back to the original segments_gdf
    # This ensures segments without matches are still present
    final_segments_gdf = segments_gdf.merge(aggregated_lidar_info, left_index=True, right_index=True, how='left')
    
    # Fill NaN in 'lidar_file_paths' with None or empty list if preferred after merge
    final_segments_gdf['lidar_file_paths'] = final_segments_gdf['lidar_file_paths'].apply(lambda x: x if isinstance(x, list) else None)


    print(f"\nSaving augmented segments to: {output_geojson_path}")
    final_segments_gdf.to_file(output_geojson_path, driver="GeoJSON")
    print("Matching process complete.")
    
    # Print a summary of matches
    matches_found = final_segments_gdf['lidar_file_paths'].notna().sum()
    print(f"Found LiDAR file matches for {matches_found} out of {len(final_segments_gdf)} segments.")
    no_matches = len(final_segments_gdf) - matches_found
    if no_matches > 0:
        print(f"Warning: {no_matches} segments had no intersecting LiDAR files.")


if __name__ == "__main__":
    # Configuration
    base_dir = "/Users/anyadecarlo/TuesdayAppointment"
    segments_input_file = os.path.join(base_dir, "gis_outputs", "river_segments.geojson")
    # This is the directory specified in your download_lidar.py
    lidar_dir = os.path.join(base_dir, "LiDAR: northern Mato Grosso near the Upper Xingu region") 
    output_segments_file = os.path.join(base_dir, "gis_outputs", "river_segments_with_lidar.geojson")
    
    # Ensure input files/dirs exist
    if not os.path.exists(segments_input_file):
        print(f"ERROR: Segments input file not found: {segments_input_file}")
        print("Please run define_river_corridor.py first.")
    elif not os.path.isdir(lidar_dir):
        print(f"ERROR: LiDAR data directory not found: {lidar_dir}")
        print("Please ensure LiDAR data is downloaded and the path is correct.")
    else:
        match_lidar_to_segments(segments_input_file, lidar_dir, output_segments_file)
