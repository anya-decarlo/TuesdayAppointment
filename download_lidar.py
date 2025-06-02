import earthaccess
import os

# --- Configuration ---
# Dataset DOI
DATASET_DOI = "10.3334/ORNLDAAC/1644"

# Bounding Box for Rio Xingu section
# (min_lon, min_lat, max_lon, max_lat)
BOUNDING_BOX = (-53.5, -11.5, -52.9, -10.9)

# Directory to save downloaded files
# IMPORTANT: Create this directory before running the script!
# Example: DOWNLOAD_DIR = "/Users/anyadecarlo/TuesdayAppointment/lidar_data"
DOWNLOAD_DIR = "/Users/anyadecarlo/TuesdayAppointment/LiDAR: northern Mato Grosso near the Upper Xingu region" # <<< CHANGE THIS

# --- Main script ---
def main():
    """Finds and downloads LiDAR data for the specified DOI and bounding box."""

    print("Authenticating with NASA Earthdata Login...")
    try:
        auth = earthaccess.login(strategy="netrc")
        if not auth.authenticated:
            print("Authentication failed. Please ensure your .netrc file is set up correctly.")
            return
        print("Authentication successful.")
    except Exception as e:
        print(f"An error occurred during authentication: {e}")
        print("Please ensure your .netrc file is set up correctly.")
        return

    # Create download directory if it doesn't exist
    if not os.path.exists(DOWNLOAD_DIR):
        print(f"Creating download directory: {DOWNLOAD_DIR}")
        os.makedirs(DOWNLOAD_DIR)
    elif not os.path.isdir(DOWNLOAD_DIR):
        print(f"Error: {DOWNLOAD_DIR} exists but is not a directory.")
        return

    print(f"Searching for granules from DOI: {DATASET_DOI}")
    print(f"Bounding box: {BOUNDING_BOX}")

    try:
        granules = earthaccess.search_data(
            doi=DATASET_DOI,
            bounding_box=BOUNDING_BOX,
            count=-1 # Get all matching granules
        )
    except Exception as e:
        print(f"An error occurred while searching for data: {e}")
        return

    if not granules:
        print("No granules found matching your criteria.")
        return

    print(f"Found {len(granules)} total granules for the dataset in the bounding box.")

    # Filter for .laz files (primary format for this LiDAR dataset)
    # Granule links are typically in 'RelatedUrls' or directly as download links.
    # earthaccess.download() handles finding the correct download links.
    # We can inspect granule metadata if we need to be more specific about file types before download,
    # but earthaccess usually handles this well.

    # For this dataset, the primary data files are .laz. earthaccess.download should pick them up.
    # If we needed to filter by filename extension before download, we might do something like:
    # laz_granules = [g for g in granules if any(url.endswith('.laz') for url in g.data_links())]
    # However, let's rely on earthaccess.download() first.

    print(f"Attempting to download {len(granules)} granules to {DOWNLOAD_DIR}...")

    try:
        # The earthaccess.download function takes the list of granule objects
        # and the local path to download to.
        downloaded_files = earthaccess.download(granules, local_path=DOWNLOAD_DIR)
        
        if downloaded_files:
            print(f"\nSuccessfully downloaded {len(downloaded_files)} files:")
            for f in downloaded_files:
                print(f" - {f}")
        else:
            print("\nNo files were downloaded. This might happen if links were not accessible or files already existed and were not overwritten.")
            print("Check for errors above or if files are already in the target directory.")

    except Exception as e:
        print(f"\nAn error occurred during download: {e}")

    print("\nScript finished.")

if __name__ == "__main__":
    # Quick check for DOWNLOAD_DIR placeholder
    if "/path/to/your/download_directory" in DOWNLOAD_DIR:
        print("---------------------------------------------------------------------")
        print("IMPORTANT: Please update the DOWNLOAD_DIR variable in the script")
        print("           to your desired download location before running!")
        print("---------------------------------------------------------------------")
    else:
        main()
