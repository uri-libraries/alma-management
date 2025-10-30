import csv
import requests
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from collections import defaultdict
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

# Thread-safe counters and results
results_lock = Lock()
progress_counter = 0

def user_has_univ_id(primary_id, show_progress=True):
    """
    Fetch a user by primary_id and check if they have a UNIV_ID identifier.
    Returns dict with user info and analysis results.
    """
    global progress_counter
    
    result = {
        'primary_id': primary_id,
        'has_univ_id': False,
        'univ_id_value': None,
        'found': False,
        'issues': []
    }
    
    user_data = call_alma_api(f"/users/{primary_id}")
    
    if not user_data:
        result['issues'].append(f"Could not fetch user {primary_id}")
        with results_lock:
            progress_counter += 1
            if show_progress and progress_counter % 10 == 0:
                print(f"  Progress: {progress_counter} users processed...")
        return result
    
    result['found'] = True
    
    # Data integrity checks
    if not primary_id.startswith("21222"):
        result['issues'].append(f"Unusual primary_id format: {primary_id}")
    
    if len(primary_id) != 14:
        result['issues'].append(f"Unusual primary_id length: {primary_id} (length: {len(primary_id)})")
    
    # Check if user has any user_identifier with id_type UNIV_ID
    for identifier in user_data.get("user_identifier", []):
        if identifier.get("id_type", {}).get("value") == "UNIV_ID":
            result['has_univ_id'] = True
            result['univ_id_value'] = identifier.get('value')
            break
    
    with results_lock:
        progress_counter += 1
        if show_progress and progress_counter % 25 == 0:
            print(f"  Progress: {progress_counter} users processed...")
    
    return result

def check_for_duplicate_univ_ids(user_results):
    """Check if any UNIV_IDs appear multiple times in the dataset"""
    univ_id_counts = defaultdict(list)
    
    for result in user_results:
        if result['has_univ_id'] and result['univ_id_value']:
            univ_id_counts[result['univ_id_value']].append(result['primary_id'])
    
    duplicates = {k: v for k, v in univ_id_counts.items() if len(v) > 1}
    return duplicates

def validate_sis_data_integrity(csv_file_path):
    """Validate SIS file structure and data patterns"""
    issues = []
    
    print("🔍 Validating CSV file structure...")
    
    try:
        with open(csv_file_path, mode="r", encoding="utf-8-sig") as csv_file:
            csv_reader = csv.reader(csv_file)
            for row_num, row in enumerate(csv_reader, 1):
                if len(row) < 1:
                    issues.append(f"Row {row_num}: Empty row")
                    continue
                    
                primary_id = row[0].strip()
                
                # Check for suspicious patterns
                if not primary_id:
                    issues.append(f"Row {row_num}: Empty primary_id")
                elif not primary_id.isdigit():
                    issues.append(f"Row {row_num}: Non-numeric primary_id: {primary_id}")
                elif not primary_id.startswith("21222"):
                    issues.append(f"Row {row_num}: Unusual primary_id format: {primary_id}")
                elif len(primary_id) != 14:
                    issues.append(f"Row {row_num}: Unusual primary_id length: {primary_id}")
                
                # Stop after checking 1000 rows to avoid excessive output
                if row_num > 1000:
                    break
                    
    except Exception as e:
        issues.append(f"Error reading CSV file: {str(e)}")
    
    return issues

# Enhanced main analysis function with concurrent processing
def analyze_missing_univ_ids_enhanced(csv_file_path, max_workers=10):
    """
    Enhanced analysis with concurrent processing and safety checks.
    max_workers: Number of concurrent API calls (adjust based on API limits)
    """
    global progress_counter
    progress_counter = 0
    
    print(f"🚀 Starting enhanced analysis of {csv_file_path}...")
    print("=" * 60)
    
    # Step 1: Validate CSV file integrity
    print("📋 Step 1: Validating CSV file integrity...")
    integrity_issues = validate_sis_data_integrity(csv_file_path)
    if integrity_issues:
        print(f"⚠️  Found {len(integrity_issues)} data integrity issues:")
        for issue in integrity_issues[:10]:  # Show first 10
            print(f"    {issue}")
        if len(integrity_issues) > 10:
            print(f"    ... and {len(integrity_issues) - 10} more issues")
    else:
        print("✅ CSV file structure looks good")
    
    # Step 2: Read all primary IDs from CSV
    print("\n📖 Step 2: Reading primary IDs from CSV...")
    primary_ids = []
    
    with open(csv_file_path, mode="r", encoding="utf-8-sig") as csv_file:
        csv_reader = csv.reader(csv_file)
        
        # Skip header if present
        first_row = next(csv_reader, None)
        if first_row and (first_row[0].lower() in ['primary_id', 'user_id', 'id'] or 'id' in first_row[0].lower()):
            print(f"  Skipping header row: {first_row}")
        else:
            # If it's not a header, process it as data
            if first_row:
                primary_id = first_row[0].strip()
                if primary_id:
                    primary_ids.append(primary_id)
        
        # Process remaining rows
        for row in csv_reader:
            if len(row) < 1:
                continue
            
            primary_id = row[0].strip()
            if primary_id:
                primary_ids.append(primary_id)
    
    print(f"  Found {len(primary_ids)} primary IDs to analyze")
    
    # Step 3: Concurrent analysis of users
    print(f"\n🔍 Step 3: Analyzing users with {max_workers} concurrent workers...")
    print("  This may take a few minutes for large datasets...")
    
    start_time = time.time()
    all_results = []
    
    # Process users in batches with concurrent execution
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_id = {executor.submit(user_has_univ_id, pid): pid for pid in primary_ids}
        
        # Collect results as they complete
        for future in as_completed(future_to_id):
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                primary_id = future_to_id[future]
                print(f"  Error processing {primary_id}: {e}")
                all_results.append({
                    'primary_id': primary_id,
                    'has_univ_id': False,
                    'univ_id_value': None,
                    'found': False,
                    'issues': [f"Exception: {str(e)}"]
                })
    
    elapsed_time = time.time() - start_time
    print(f"\n⏱️  Processing completed in {elapsed_time:.1f} seconds")
    
    # Step 4: Analyze results
    print("\n📊 Step 4: Analyzing results...")
    
    users_with_univ_id = [r for r in all_results if r['has_univ_id']]
    users_without_univ_id = [r for r in all_results if r['found'] and not r['has_univ_id']]
    users_not_found = [r for r in all_results if not r['found']]
    users_with_issues = [r for r in all_results if r['issues']]
    
    # Step 5: Check for duplicate UNIV_IDs
    print("\n🔍 Step 5: Checking for duplicate UNIV_IDs...")
    duplicates = check_for_duplicate_univ_ids(all_results)
    
    # Step 6: Generate comprehensive report
    print("\n" + "=" * 60)
    print("📋 COMPREHENSIVE ANALYSIS REPORT")
    print("=" * 60)
    print(f"Total users analyzed: {len(all_results)}")
    print(f"Users WITH UNIV_ID: {len(users_with_univ_id)}")
    print(f"Users WITHOUT UNIV_ID: {len(users_without_univ_id)}")
    print(f"Users not found: {len(users_not_found)}")
    print(f"Users with data issues: {len(users_with_issues)}")
    print(f"Duplicate UNIV_IDs found: {len(duplicates)}")
    print(f"Processing time: {elapsed_time:.1f} seconds")
    print(f"Average time per user: {elapsed_time/len(all_results):.2f} seconds")
    
    # Detailed reporting
    if users_without_univ_id:
        print(f"\n⚠️  Users WITHOUT UNIV_ID ({len(users_without_univ_id)}):")
        for result in users_without_univ_id[:20]:  # Show first 20
            print(f"  - {result['primary_id']}")
        if len(users_without_univ_id) > 20:
            print(f"  ... and {len(users_without_univ_id) - 20} more")
    
    if duplicates:
        print(f"\n⚠️  DUPLICATE UNIV_IDs found ({len(duplicates)}):")
        for univ_id, primary_ids in list(duplicates.items())[:10]:
            print(f"  UNIV_ID {univ_id} appears in: {', '.join(primary_ids)}")
        if len(duplicates) > 10:
            print(f"  ... and {len(duplicates) - 10} more duplicates")
    
    if users_not_found:
        print(f"\n⚠️  Users NOT FOUND ({len(users_not_found)}):")
        for result in users_not_found[:10]:
            print(f"  - {result['primary_id']}")
        if len(users_not_found) > 10:
            print(f"  ... and {len(users_not_found) - 10} more")
    
    # Safety assessment
    print(f"\n🛡️  SAFETY ASSESSMENT:")
    is_safe = (len(users_without_univ_id) == 0 and 
               len(duplicates) == 0 and 
               len(integrity_issues) == 0)
    
    if is_safe:
        print("✅ SAFE TO PROCEED with SIS matching change!")
        print("   - All users have UNIV_IDs")
        print("   - No duplicate UNIV_IDs found")
        print("   - No data integrity issues")
    else:
        print("⚠️  RISKS DETECTED - Review before proceeding:")
        if users_without_univ_id:
            print(f"   - {len(users_without_univ_id)} users without UNIV_ID")
        if duplicates:
            print(f"   - {len(duplicates)} duplicate UNIV_IDs")
        if integrity_issues:
            print(f"   - {len(integrity_issues)} data integrity issues")
    
    # Write detailed results to files
    timestamp = int(time.time())
    
    if users_without_univ_id:
        output_file = f"users_without_univ_id_{timestamp}.csv"
        with open(output_file, mode="w", encoding="utf-8", newline='') as output_csv:
            writer = csv.writer(output_csv)
            writer.writerow(["primary_id", "issues"])
            for result in users_without_univ_id:
                writer.writerow([result['primary_id'], '; '.join(result['issues'])])
        print(f"\n📄 Users without UNIV_ID saved to: {output_file}")
    
    if duplicates:
        dup_file = f"duplicate_univ_ids_{timestamp}.csv"
        with open(dup_file, mode="w", encoding="utf-8", newline='') as dup_csv:
            writer = csv.writer(dup_csv)
            writer.writerow(["univ_id", "primary_ids", "count"])
            for univ_id, primary_ids in duplicates.items():
                writer.writerow([univ_id, '; '.join(primary_ids), len(primary_ids)])
        print(f"📄 Duplicate UNIV_IDs saved to: {dup_file}")
    
    # Summary results file
    summary_file = f"analysis_summary_{timestamp}.csv"
    with open(summary_file, mode="w", encoding="utf-8", newline='') as summary_csv:
        writer = csv.writer(summary_csv)
        writer.writerow(["primary_id", "has_univ_id", "univ_id_value", "found", "issues"])
        for result in all_results:
            writer.writerow([
                result['primary_id'],
                result['has_univ_id'],
                result['univ_id_value'] or '',
                result['found'],
                '; '.join(result['issues'])
            ])
    print(f"📄 Complete analysis saved to: {summary_file}")
    
    return {
        'total': len(all_results),
        'with_univ_id': len(users_with_univ_id),
        'without_univ_id': len(users_without_univ_id),
        'not_found': len(users_not_found),
        'duplicates': len(duplicates),
        'processing_time': elapsed_time,
        'is_safe': is_safe,
        'results': all_results
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
    
    print("🚀 Enhanced Alma UNIV_ID Analysis Tool")
    print("=====================================")
    print(f"Environment: {'SANDBOX' if os.getenv('ALMA_ENV') == 'SANDBOX' else 'PRODUCTION'}")
    print(f"API Base URL: {ALMA_API_BASE_URL}")
    print(f"File to analyze: {csv_file_path}")
    
    # Ask user about concurrent workers
    try:
        workers_input = input("\nEnter number of concurrent workers (1-20, default=10, higher=faster but more API load): ").strip()
        max_workers = int(workers_input) if workers_input and workers_input.isdigit() else 10
        max_workers = max(1, min(20, max_workers))  # Limit between 1-20
    except (ValueError, KeyboardInterrupt):
        max_workers = 10
    
    print(f"Using {max_workers} concurrent workers...")
    
    # Run enhanced analysis
    results = analyze_missing_univ_ids_enhanced(csv_file_path, max_workers=max_workers)
    
    # Final summary
    print(f"\n🎯 FINAL ANSWER:")
    print(f"   {results['without_univ_id']} users out of {results['total']} DO NOT have a UNIV_ID identifier.")
    print(f"   Processing completed in {results['processing_time']:.1f} seconds")
    
    if results['is_safe']:
        print(f"\n✅ RECOMMENDATION: SAFE to change SIS matching from Primary ID to University ID")
    else:
        print(f"\n⚠️  RECOMMENDATION: REVIEW ISSUES before changing SIS matching")