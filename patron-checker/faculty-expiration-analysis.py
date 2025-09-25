import requests
import os
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
from collections import Counter
import concurrent.futures
import time

# Load environment variables
load_dotenv()

API_KEY = os.getenv('ALMA_API_KEY')
BASE_URL = os.getenv('ALMA_BASE_URL', 'https://api-na.hosted.exlibrisgroup.com/almaws/v1')

def get_user_details(user_id):
    """Fetch detailed user information including expiration date"""
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
    """Parse Alma date format to datetime object"""
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

def get_faculty_expiration_info_batch(user_ids, max_workers=3):
    """Fetch expiration information for multiple faculty/staff concurrently"""
    faculty_info = {}
    
    def fetch_single_faculty_expiration(user_id):
        try:
            # Add small delay to avoid overwhelming the server
            time.sleep(0.1)
            details = get_user_details(user_id)
            if details:
                # Extract expiration date
                expiry_date_str = details.get('expiry_date', '')
                expiry_date = parse_alma_date(expiry_date_str)
                
                # Get other relevant info
                user_group = details.get('user_group', {})
                if isinstance(user_group, dict):
                    group_value = user_group.get('value', 'Unknown')
                else:
                    group_value = user_group if user_group else 'Unknown'
                
                status = details.get('status', {})
                if isinstance(status, dict):
                    status_value = status.get('value', 'Unknown')
                else:
                    status_value = status if status else 'Unknown'
                
                return user_id, {
                    'expiry_date': expiry_date,
                    'expiry_date_string': expiry_date_str,
                    'user_group': group_value,
                    'status': status_value,
                    'first_name': details.get('first_name', ''),
                    'last_name': details.get('last_name', ''),
                    'primary_id': details.get('primary_id', user_id)
                }
        except Exception as e:
            print(f"Error fetching expiration info for {user_id}: {e}")
        return user_id, None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_user = {executor.submit(fetch_single_faculty_expiration, user_id): user_id for user_id in user_ids}
        
        for future in concurrent.futures.as_completed(future_to_user):
            user_id, user_info = future.result()
            if user_info:
                faculty_info[user_id] = user_info
    
    return faculty_info

def analyze_facultystaff_expirations():
    """Analyze expiration dates of orphaned FacultyStaff users"""
    
    # Load orphaned users group analysis
    try:
        with open('orphaned_users_group_analysis.json', 'r') as f:
            data = json.load(f)
            detailed_user_info = data['detailed_user_info']
    except FileNotFoundError:
        print("Error: orphaned_users_group_analysis.json not found. Run orphaned-users-group-analysis.py first.")
        return
    
    # Filter for FacultyStaff, Faculty, and Staff users
    faculty_users = {}
    target_groups = ['FacultyStaff', 'Faculty', 'Staff']
    
    for user_id, user_info in detailed_user_info.items():
        if user_info['user_group'] in target_groups:
            faculty_users[user_id] = user_info
    
    print(f"Found {len(faculty_users)} faculty/staff users in orphaned users:")
    for group in target_groups:
        count = sum(1 for info in faculty_users.values() if info['user_group'] == group)
        if count > 0:
            print(f"  {group}: {count}")
    
    if not faculty_users:
        print("No FacultyStaff, Faculty, or Staff users found in orphaned users.")
        return
    
    print(f"\nFetching expiration dates for {len(faculty_users)} faculty/staff...")
    
    # Process faculty/staff in batches to get expiration info
    batch_size = 25
    faculty_ids = list(faculty_users.keys())
    all_faculty_expiry_info = {}
    
    for i in range(0, len(faculty_ids), batch_size):
        batch = faculty_ids[i:i + batch_size]
        print(f"Processing batch {i//batch_size + 1} ({len(batch)} faculty/staff)...")
        
        batch_info = get_faculty_expiration_info_batch(batch)
        all_faculty_expiry_info.update(batch_info)
        
        print(f"Processed {min(i + batch_size, len(faculty_ids))}/{len(faculty_ids)} faculty/staff...")
        
        # Small delay between batches
        time.sleep(1)
    
    # Analyze expiration status
    current_date = datetime.now()
    print(f"\nAnalysis date: {current_date.strftime('%Y-%m-%d')}")
    
    # Categorize faculty/staff by expiration status
    expired_faculty = {}
    active_faculty = {}
    no_expiry_date = {}
    
    for user_id, faculty_info in all_faculty_expiry_info.items():
        if faculty_info['expiry_date']:
            if faculty_info['expiry_date'] < current_date:
                expired_faculty[user_id] = faculty_info
            else:
                active_faculty[user_id] = faculty_info
        else:
            no_expiry_date[user_id] = faculty_info
    
    # Generate analysis by group
    group_analysis = {}
    for group in target_groups:
        group_expired = sum(1 for info in expired_faculty.values() if info['user_group'] == group)
        group_active = sum(1 for info in active_faculty.values() if info['user_group'] == group)
        group_no_date = sum(1 for info in no_expiry_date.values() if info['user_group'] == group)
        group_total = group_expired + group_active + group_no_date
        
        if group_total > 0:  # Only include groups with users
            group_analysis[group] = {
                'total': group_total,
                'expired': group_expired,
                'active': group_active,
                'no_expiry_date': group_no_date,
                'expired_percentage': (group_expired / group_total * 100) if group_total > 0 else 0
            }
    
    # Print results
    print(f"\n{'='*70}")
    print(f"FACULTY/STAFF EXPIRATION ANALYSIS")
    print(f"{'='*70}")
    
    total_faculty = len(all_faculty_expiry_info)
    total_expired = len(expired_faculty)
    total_active = len(active_faculty)
    total_no_date = len(no_expiry_date)
    
    print(f"Total faculty/staff analyzed: {total_faculty}")
    print(f"Faculty/staff with missing expiration data: {len(faculty_users) - total_faculty}")
    
    print(f"\nOVERALL EXPIRATION STATUS:")
    print(f"{'Status':<20} {'Count':<10} {'Percentage'}")
    print("-" * 40)
    print(f"{'Expired':<20} {total_expired:<10} {total_expired/total_faculty*100:.1f}%")
    print(f"{'Active (not expired)':<20} {total_active:<10} {total_active/total_faculty*100:.1f}%")
    print(f"{'No expiry date':<20} {total_no_date:<10} {total_no_date/total_faculty*100:.1f}%")
    
    print(f"\nBY FACULTY/STAFF GROUP:")
    print(f"{'Group':<15} {'Total':<8} {'Expired':<10} {'Active':<8} {'No Date':<10} {'% Expired'}")
    print("-" * 70)
    
    for group, analysis in group_analysis.items():
        print(f"{group:<15} {analysis['total']:<8} {analysis['expired']:<10} "
              f"{analysis['active']:<8} {analysis['no_expiry_date']:<10} {analysis['expired_percentage']:.1f}%")
    
    # Show sample expired faculty/staff
    if expired_faculty:
        print(f"\nSAMPLE EXPIRED FACULTY/STAFF:")
        print(f"{'Name':<25} {'Group':<15} {'Primary ID':<18} {'Expired Date'}")
        print("-" * 80)
        
        count = 0
        for user_id, info in expired_faculty.items():
            if count >= 10:  # Show max 10 examples
                break
            name = f"{info['first_name']} {info['last_name']}".strip()
            if not name:
                name = "No name"
            expired_date = info['expiry_date'].strftime('%Y-%m-%d') if info['expiry_date'] else 'Unknown'
            print(f"{name:<25} {info['user_group']:<15} {info['primary_id']:<18} {expired_date}")
            count += 1
    
    # Show active faculty/staff (these are the concerning ones)
    if active_faculty:
        print(f"\nACTIVE FACULTY/STAFF WITHOUT UNIV_ID:")
        print(f"{'Name':<25} {'Group':<15} {'Primary ID':<18} {'Expires'}")
        print("-" * 80)
        
        for user_id, info in active_faculty.items():
            name = f"{info['first_name']} {info['last_name']}".strip()
            if not name:
                name = "No name"
            expiry_date = info['expiry_date'].strftime('%Y-%m-%d') if info['expiry_date'] else 'Never'
            print(f"{name:<25} {info['user_group']:<15} {info['primary_id']:<18} {expiry_date}")
    
    # Save detailed report
    report = {
        'analysis_date': current_date.isoformat(),
        'summary': {
            'total_faculty_analyzed': total_faculty,
            'total_expired': total_expired,
            'total_active': total_active,
            'total_no_expiry_date': total_no_date,
            'overall_expired_percentage': (total_expired / total_faculty * 100) if total_faculty > 0 else 0
        },
        'by_group': group_analysis,
        'expired_faculty': {user_id: {
            **info,
            'expiry_date': info['expiry_date'].isoformat() if info['expiry_date'] else None,
            'days_expired': (current_date - info['expiry_date']).days if info['expiry_date'] else None
        } for user_id, info in expired_faculty.items()},
        'active_faculty': {user_id: {
            **info,
            'expiry_date': info['expiry_date'].isoformat() if info['expiry_date'] else None,
            'days_until_expiry': (info['expiry_date'] - current_date).days if info['expiry_date'] else None
        } for user_id, info in active_faculty.items()},
        'no_expiry_date_faculty': no_expiry_date
    }
    
    with open('faculty_expiration_analysis.json', 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\nDetailed analysis saved to: faculty_expiration_analysis.json")
    
    return report

if __name__ == "__main__":
    if not API_KEY:
        print("Error: ALMA_API_KEY not found in environment variables")
    else:
        analyze_facultystaff_expirations()