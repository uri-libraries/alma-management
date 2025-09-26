import requests
import csv
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import concurrent.futures
import time
from collections import Counter

# Load environment variables
load_dotenv()

# Configuration
API_KEY = os.getenv('ALMA_API_KEY')
BASE_URL = os.getenv('ALMA_BASE_URL', 'https://api-na.hosted.exlibrisgroup.com/almaws/v1')
CSV_FILE_PATH = 'barcode-fails-uid.csv'
OUTPUT_FILE = 'barcode_fails_patron_analysis.json'

def read_uids_from_csv(file_path):
    """
    Read UIDs from CSV file.
    
    Args:
        file_path (str): Path to the CSV file containing UIDs
        
    Returns:
        list: List of UIDs as strings
    """
    uids = []
    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as file:
            # Check if file has headers by reading first few lines
            sample = file.read(1024)
            file.seek(0)
            
            # If the first line contains only digits, treat it as data
            reader = csv.reader(file)
            for row in reader:
                if row and row[0].strip():  # Skip empty rows
                    uid = row[0].strip()
                    if uid.isdigit():  # Ensure it's a valid UID
                        uids.append(uid)
                    else:
                        print(f"Warning: Skipping non-numeric UID: {uid}")
        
        print(f"Successfully read {len(uids)} UIDs from {file_path}")
        return uids
    
    except FileNotFoundError:
        print(f"Error: File {file_path} not found")
        return []
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []

def get_user_details(user_id):
    """
    Fetch detailed user information from Alma API.
    
    Args:
        user_id (str): The user ID to fetch details for
        
    Returns:
        dict: User details from API, or None if error occurs
    """
    headers = {
        'Authorization': f'apikey {API_KEY}',
        'Accept': 'application/json'
    }
    
    url = f"{BASE_URL}/users/{user_id}"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching user details for {user_id}: {e}")
        return None

def parse_alma_date(date_string):
    """
    Parse Alma date format to datetime object.
    
    Args:
        date_string (str): Date string from Alma API
        
    Returns:
        datetime: Parsed datetime object, or None if parsing fails
    """
    if not date_string:
        return None
    
    # Alma dates can be in various formats, try common ones
    date_formats = [
        '%Y-%m-%dZ',           # 2023-12-31Z
        '%Y-%m-%d',            # 2023-12-31
        '%Y-%m-%dT%H:%M:%SZ',  # 2023-12-31T23:59:59Z
        '%Y-%m-%dT%H:%M:%S',   # 2023-12-31T23:59:59
    ]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    
    print(f"Warning: Could not parse date format: {date_string}")
    return None

def extract_patron_info(user_data):
    """
    Extract patron information from Alma user data.
    
    Args:
        user_data (dict): User data from Alma API
        
    Returns:
        dict: Extracted patron information
    """
    if not user_data:
        return None
    
    # Basic info
    user_id = user_data.get('primary_id', 'N/A')
    first_name = user_data.get('first_name', '')
    last_name = user_data.get('last_name', '')
    full_name = f"{first_name} {last_name}".strip()
    
    # Email extraction
    email = 'N/A'
    contact_info = user_data.get('contact_info', {})
    if contact_info and 'email' in contact_info:
        email_list = contact_info['email']
        if isinstance(email_list, list) and len(email_list) > 0:
            email = email_list[0].get('email_address', 'N/A')
    
    # Patron type (user group)
    user_group = user_data.get('user_group', {})
    if isinstance(user_group, dict):
        patron_type = user_group.get('desc', user_group.get('value', 'N/A'))
    else:
        patron_type = user_group if user_group else 'N/A'
    
    # Expiration date
    expiry_date_str = user_data.get('expiry_date', '')
    expiry_date = parse_alma_date(expiry_date_str)
    
    # Creation date
    created_date_str = user_data.get('created_date', user_data.get('record_created_date', ''))
    created_date = parse_alma_date(created_date_str)
    
    # Status
    status = user_data.get('status', {})
    if isinstance(status, dict):
        status_value = status.get('value', 'Unknown')
    else:
        status_value = status if status else 'Unknown'
    
    return {
        'user_id': user_id,
        'name': full_name,
        'first_name': first_name,
        'last_name': last_name,
        'email': email,
        'patron_type': patron_type,
        'expiry_date': expiry_date,
        'expiry_date_string': expiry_date_str,
        'created_date': created_date,
        'created_date_string': created_date_str,
        'status': status_value,
        'is_expired': expiry_date < datetime.now() if expiry_date else None
    }

def analyze_single_patron(user_id):
    """
    Analyze a single patron's information.
    
    Args:
        user_id (str): The user ID to analyze
        
    Returns:
        tuple: (user_id, patron_info_dict or None)
    """
    try:
        # Add small delay to avoid overwhelming the server
        time.sleep(0.1)
        
        # Fetch user details
        user_data = get_user_details(user_id)
        if not user_data:
            return user_id, None
        
        # Extract patron information
        patron_info = extract_patron_info(user_data)
        return user_id, patron_info
        
    except Exception as e:
        print(f"Error analyzing patron {user_id}: {e}")
        return user_id, None

def analyze_patrons_batch(user_ids, max_workers=3):
    """
    Analyze multiple patrons concurrently.
    
    Args:
        user_ids (list): List of user IDs to analyze
        max_workers (int): Maximum number of concurrent workers
        
    Returns:
        dict: Dictionary with analysis results and statistics
    """
    results = {}
    successful_analyses = 0
    failed_analyses = 0
    
    print(f"Starting analysis of {len(user_ids)} patrons with {max_workers} concurrent workers...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_user = {
            executor.submit(analyze_single_patron, user_id): user_id 
            for user_id in user_ids
        }
        
        # Process completed tasks
        for i, future in enumerate(concurrent.futures.as_completed(future_to_user), 1):
            user_id, patron_info = future.result()
            
            if patron_info:
                results[user_id] = patron_info
                successful_analyses += 1
            else:
                results[user_id] = {
                    'error': 'Failed to retrieve patron information',
                    'user_id': user_id
                }
                failed_analyses += 1
            
            # Progress indicator
            if i % 10 == 0 or i == len(user_ids):
                print(f"Processed {i}/{len(user_ids)} patrons...")
    
    print(f"Analysis complete. Success: {successful_analyses}, Failed: {failed_analyses}")
    return {
        'patron_data': results,
        'statistics': {
            'total_analyzed': len(user_ids),
            'successful': successful_analyses,
            'failed': failed_analyses,
            'analysis_date': datetime.now().isoformat()
        }
    }

def analyze_creation_dates(successful_patrons):
    """
    Analyze patron creation date patterns.
    
    Args:
        successful_patrons (list): List of successful patron data
        
    Returns:
        dict: Creation date analysis statistics
    """
    now = datetime.now()
    creation_dates = []
    no_creation_date = 0
    
    for patron in successful_patrons:
        if patron.get('created_date'):
            creation_dates.append(patron['created_date'])
        else:
            no_creation_date += 1
    
    if not creation_dates:
        return {
            'accounts_with_creation_date': 0,
            'accounts_without_creation_date': no_creation_date,
            'oldest_account': None,
            'newest_account': None,
            'creation_by_year': {},
            'recent_creations': {
                'last_30_days': 0,
                'last_90_days': 0,
                'last_year': 0
            }
        }
    
    # Sort dates for analysis
    creation_dates.sort()
    oldest = creation_dates[0]
    newest = creation_dates[-1]
    
    # Count by year
    creation_by_year = Counter(date.year for date in creation_dates)
    
    # Recent creation analysis
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)
    one_year_ago = now - timedelta(days=365)
    
    recent_30 = len([d for d in creation_dates if d >= thirty_days_ago])
    recent_90 = len([d for d in creation_dates if d >= ninety_days_ago])
    recent_year = len([d for d in creation_dates if d >= one_year_ago])
    
    return {
        'accounts_with_creation_date': len(creation_dates),
        'accounts_without_creation_date': no_creation_date,
        'oldest_account': oldest,
        'newest_account': newest,
        'creation_by_year': dict(sorted(creation_by_year.items())),
        'recent_creations': {
            'last_30_days': recent_30,
            'last_90_days': recent_90,
            'last_year': recent_year
        }
    }

def generate_analysis_summary(results):
    """
    Generate a comprehensive analysis summary.
    
    Args:
        results (dict): Results from analyze_patrons_batch
        
    Returns:
        dict: Summary statistics and insights
    """
    patron_data = results['patron_data']
    successful_patrons = [p for p in patron_data.values() if 'error' not in p]
    
    if not successful_patrons:
        return {
            'summary': 'No successful patron data retrieved',
            'patron_type_distribution': {},
            'expiration_analysis': {},
            'status_distribution': {},
            'creation_analysis': {
                'accounts_with_creation_date': 0,
                'accounts_without_creation_date': 0,
                'oldest_account': None,
                'newest_account': None,
                'creation_by_year': {},
                'recent_creations': {
                    'last_30_days': 0,
                    'last_90_days': 0,
                    'last_year': 0
                }
            }
        }
    
    # Patron type distribution
    patron_types = Counter(p['patron_type'] for p in successful_patrons if p['patron_type'] != 'N/A')
    
    # Status distribution  
    statuses = Counter(p['status'] for p in successful_patrons if p['status'] != 'Unknown')
    
    # Expiration analysis
    now = datetime.now()
    expired_count = 0
    expiring_soon_count = 0  # Within 30 days
    valid_count = 0
    no_expiry_count = 0
    
    for patron in successful_patrons:
        if patron['expiry_date']:
            if patron['is_expired']:
                expired_count += 1
            elif patron['expiry_date'] - now <= timedelta(days=30):
                expiring_soon_count += 1
            else:
                valid_count += 1
        else:
            no_expiry_count += 1
    
    # Email analysis
    valid_emails = len([p for p in successful_patrons if p['email'] != 'N/A' and '@' in p['email']])
    missing_emails = len([p for p in successful_patrons if p['email'] == 'N/A'])
    
    # Creation date analysis
    creation_analysis = analyze_creation_dates(successful_patrons)
    
    return {
        'summary': {
            'total_patrons_analyzed': len(successful_patrons),
            'failed_retrievals': len([p for p in patron_data.values() if 'error' in p]),
        },
        'patron_type_distribution': dict(patron_types.most_common()),
        'status_distribution': dict(statuses.most_common()),
        'expiration_analysis': {
            'expired': expired_count,
            'expiring_soon_30_days': expiring_soon_count,
            'valid': valid_count,
            'no_expiry_date': no_expiry_count
        },
        'email_analysis': {
            'valid_emails': valid_emails,
            'missing_emails': missing_emails,
            'email_completion_rate': f"{(valid_emails / len(successful_patrons) * 100):.1f}%" if successful_patrons else "0%"
        },
        'creation_analysis': creation_analysis
    }

def save_results_to_json(results, filename):
    """
    Save analysis results to JSON file.
    
    Args:
        results (dict): Analysis results to save
        filename (str): Output filename
    """
    try:
        # Convert datetime objects to strings for JSON serialization
        def datetime_handler(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object {obj} is not JSON serializable")
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, default=datetime_handler, ensure_ascii=False)
        
        print(f"Results successfully saved to {filename}")
        
    except Exception as e:
        print(f"Error saving results to {filename}: {e}")

def print_summary_report(analysis_summary):
    """
    Print a formatted summary report to console.
    
    Args:
        analysis_summary (dict): Summary data from generate_analysis_summary
    """
    print("\n" + "="*60)
    print("PATRON ANALYSIS SUMMARY REPORT")
    print("="*60)
    
    # Basic statistics
    summary = analysis_summary['summary']
    print(f"\nAnalysis Overview:")
    print(f"  Total patrons successfully analyzed: {summary['total_patrons_analyzed']}")
    print(f"  Failed retrievals: {summary['failed_retrievals']}")
    
    # Patron type distribution
    print(f"\nPatron Type Distribution:")
    for patron_type, count in analysis_summary['patron_type_distribution'].items():
        percentage = (count / summary['total_patrons_analyzed'] * 100) if summary['total_patrons_analyzed'] > 0 else 0
        print(f"  {patron_type}: {count} ({percentage:.1f}%)")
    
    # Status distribution
    print(f"\nStatus Distribution:")
    for status, count in analysis_summary['status_distribution'].items():
        percentage = (count / summary['total_patrons_analyzed'] * 100) if summary['total_patrons_analyzed'] > 0 else 0
        print(f"  {status}: {count} ({percentage:.1f}%)")
    
    # Expiration analysis
    exp_analysis = analysis_summary['expiration_analysis']
    print(f"\nExpiration Analysis:")
    print(f"  Expired accounts: {exp_analysis['expired']}")
    print(f"  Expiring within 30 days: {exp_analysis['expiring_soon_30_days']}")
    print(f"  Valid accounts: {exp_analysis['valid']}")
    print(f"  No expiry date: {exp_analysis['no_expiry_date']}")
    
    # Email analysis
    email_analysis = analysis_summary['email_analysis']
    print(f"\nEmail Analysis:")
    print(f"  Valid emails: {email_analysis['valid_emails']}")
    print(f"  Missing emails: {email_analysis['missing_emails']}")
    print(f"  Email completion rate: {email_analysis['email_completion_rate']}")
    
    # Creation date analysis
    creation_analysis = analysis_summary['creation_analysis']
    print(f"\nAccount Creation Analysis:")
    print(f"  Accounts with creation date: {creation_analysis['accounts_with_creation_date']}")
    print(f"  Accounts without creation date: {creation_analysis['accounts_without_creation_date']}")
    
    if creation_analysis['oldest_account']:
        print(f"  Oldest account created: {creation_analysis['oldest_account'].strftime('%Y-%m-%d')}")
        print(f"  Newest account created: {creation_analysis['newest_account'].strftime('%Y-%m-%d')}")
        
        # Recent creations
        recent = creation_analysis['recent_creations']
        print(f"  Created in last 30 days: {recent['last_30_days']}")
        print(f"  Created in last 90 days: {recent['last_90_days']}")
        print(f"  Created in last year: {recent['last_year']}")
        
        # Top creation years
        print(f"  Creation by year (top 5):")
        sorted_years = sorted(creation_analysis['creation_by_year'].items(), key=lambda x: x[1], reverse=True)[:5]
        for year, count in sorted_years:
            print(f"    {year}: {count} accounts")
    
    print("\n" + "="*60)

def main():
    """
    Main execution function.
    """
    print("Starting Barcode Fails UID Patron Analysis")
    print("="*50)
    
    # Check for required environment variables
    if not API_KEY:
        print("Error: ALMA_API_KEY environment variable not set")
        print("Please create a .env file with your Alma API credentials")
        return
    
    if not BASE_URL:
        print("Error: ALMA_BASE_URL environment variable not set")
        return
    
    # Read UIDs from CSV
    print(f"Reading UIDs from {CSV_FILE_PATH}...")
    uids = read_uids_from_csv(CSV_FILE_PATH)
    
    if not uids:
        print("No UIDs found to process. Exiting.")
        return
    
    print(f"Found {len(uids)} UIDs to analyze")
    
    # Option to limit for testing
    if len(uids) > 100:
        response = input(f"Found {len(uids)} UIDs. Process all? (y/N) or enter number to limit: ").strip()
        if response.lower() == 'y':
            pass  # Process all
        elif response.isdigit():
            limit = int(response)
            uids = uids[:limit]
            print(f"Limited to first {limit} UIDs for analysis")
        else:
            print("Processing first 10 UIDs for testing...")
            uids = uids[:10]
    
    # Analyze patrons
    print(f"\nStarting analysis of {len(uids)} patrons...")
    start_time = datetime.now()
    
    try:
        results = analyze_patrons_batch(uids, max_workers=3)
        
        # Generate analysis summary
        analysis_summary = generate_analysis_summary(results)
        
        # Add summary to results
        results['analysis_summary'] = analysis_summary
        
        # Print summary report
        print_summary_report(analysis_summary)
        
        # Save results to JSON
        save_results_to_json(results, OUTPUT_FILE)
        
        # Processing time
        end_time = datetime.now()
        processing_time = end_time - start_time
        print(f"\nTotal processing time: {processing_time}")
        print(f"Average time per patron: {processing_time.total_seconds() / len(uids):.2f} seconds")
        
        print(f"\nAnalysis complete! Results saved to {OUTPUT_FILE}")
        
    except KeyboardInterrupt:
        print("\nAnalysis interrupted by user. Partial results may be available.")
    except Exception as e:
        print(f"Error during analysis: {e}")
        print("Check your API credentials and network connection.")

if __name__ == "__main__":
    main()