import csv
import requests
import os
from dotenv import load_dotenv

# Load environment variables
env_file = ".env.sandbox" if os.getenv("ALMA_ENV") == "SANDBOX" else ".env"
load_dotenv(env_file)

ALMA_API_KEY = os.getenv('ALMA_API_KEY')
ALMA_API_BASE_URL = os.getenv('ALMA_API_BASE_URL')

# Helper function to make API calls
def call_alma_api(endpoint, method="GET", params=None, data=None):
    url = f"{ALMA_API_BASE_URL}/almaws/v1{endpoint}"
    headers = {
        "Authorization": f"apikey {ALMA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data)
        elif method == "POST":
            response = requests.post(url, headers=headers, params=params, json=data)
        else:
            raise ValueError("Unsupported HTTP method")
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error during API call to {url}: {e}")
        return None

# Function to check if a user has a UNIV_ID identifier
def user_has_univ_id(primary_id):
    """
    Fetch a user by primary_id and check if they have a UNIV_ID identifier.
    Returns True if UNIV_ID exists, False if not, None if user not found.
    """
    print(f"Checking user {primary_id} for UNIV_ID...")
    
    user_data = call_alma_api(f"/users/{primary_id}")
    
    if not user_data:
        print(f"  Could not fetch user {primary_id}")
        return None
    
    # Check if user has any user_identifier with id_type UNIV_ID
    for identifier in user_data.get("user_identifier", []):
        if identifier.get("id_type", {}).get("value") == "UNIV_ID":
            print(f"  User {primary_id} HAS UNIV_ID: {identifier.get('value')}")
            return True
    
    print(f"  User {primary_id} does NOT have UNIV_ID")
    return False

# Main function to analyze the CSV file
def analyze_missing_univ_ids(csv_file_path):
    users_without_univ_id = []
    users_with_univ_id = []
    users_not_found = []
    total_users = 0
    
    print(f"Analyzing users in {csv_file_path}...")
    print("=" * 50)
    
    with open(csv_file_path, mode="r", encoding="utf-8-sig") as csv_file:
        csv_reader = csv.reader(csv_file)
        
        # Skip header if present
        first_row = next(csv_reader, None)
        if first_row and (first_row[0].lower() in ['primary_id', 'user_id', 'id'] or 'id' in first_row[0].lower()):
            print(f"Skipping header row: {first_row}")
        else:
            # If it's not a header, process it as data
            if first_row:
                primary_id = first_row[0].strip()
                if primary_id:
                    total_users += 1
                    result = user_has_univ_id(primary_id)
                    if result is True:
                        users_with_univ_id.append(primary_id)
                    elif result is False:
                        users_without_univ_id.append(primary_id)
                    else:
                        users_not_found.append(primary_id)
        
        # Process remaining rows
        for row in csv_reader:
            if len(row) < 1:
                print(f"Skipping empty/invalid row: {row}")
                continue
            
            primary_id = row[0].strip()
            
            if not primary_id:
                print(f"Skipping row with missing primary_id: {row}")
                continue
            
            total_users += 1
            result = user_has_univ_id(primary_id)
            
            if result is True:
                users_with_univ_id.append(primary_id)
            elif result is False:
                users_without_univ_id.append(primary_id)
            else:  # result is None - user not found
                users_not_found.append(primary_id)
    
    # Print summary results
    print("\n" + "=" * 50)
    print("ANALYSIS SUMMARY")
    print("=" * 50)
    print(f"Total users analyzed: {total_users}")
    print(f"Users WITH UNIV_ID: {len(users_with_univ_id)}")
    print(f"Users WITHOUT UNIV_ID: {len(users_without_univ_id)}")
    print(f"Users not found: {len(users_not_found)}")
    
    if users_without_univ_id:
        print(f"\nUsers WITHOUT UNIV_ID ({len(users_without_univ_id)}):")
        for user_id in users_without_univ_id:
            print(f"  - {user_id}")
    
    if users_not_found:
        print(f"\nUsers NOT FOUND ({len(users_not_found)}):")
        for user_id in users_not_found:
            print(f"  - {user_id}")
    
    # Write results to output files
    if users_without_univ_id:
        output_file = "users_without_univ_id.csv"
        with open(output_file, mode="w", encoding="utf-8", newline='') as output_csv:
            writer = csv.writer(output_csv)
            writer.writerow(["primary_id"])
            for user_id in users_without_univ_id:
                writer.writerow([user_id])
        print(f"\nUsers without UNIV_ID saved to: {output_file}")
    
    return {
        'total': total_users,
        'with_univ_id': len(users_with_univ_id),
        'without_univ_id': len(users_without_univ_id),
        'not_found': len(users_not_found),
        'users_without_univ_id': users_without_univ_id,
        'users_not_found': users_not_found
    }

if __name__ == "__main__":
    # Ensure API credentials are set
    if not ALMA_API_KEY or not ALMA_API_BASE_URL:
        print("ERROR: Please set ALMA_API_KEY and ALMA_API_BASE_URL in your .env file.")
        exit(1)
    
    # Path to the pid-unchanged.csv file
    csv_file_path = "pid-unchanged.csv"
    
    if not os.path.exists(csv_file_path):
        print(f"ERROR: File {csv_file_path} not found.")
        print("Available files in current directory:")
        for file in os.listdir("."):
            if file.endswith(".csv"):
                print(f"  - {file}")
        exit(1)
    
    # Analyze the CSV file
    results = analyze_missing_univ_ids(csv_file_path)
    
    print(f"\n🎯 FINAL ANSWER: {results['without_univ_id']} users out of {results['total']} DO NOT have a UNIV_ID identifier.")