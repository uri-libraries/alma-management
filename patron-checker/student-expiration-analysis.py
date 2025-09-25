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

def get_student_expiration_info_batch(user_ids, max_workers=3):
    """Fetch expiration information for multiple students concurrently"""
    student_info = {}
    
    def fetch_single_student_expiration(user_id):
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
        future_to_user = {executor.submit(fetch_single_student_expiration, user_id): user_id for user_id in user_ids}
        
        for future in concurrent.futures.as_completed(future_to_user):
            user_id, user_info = future.result()
            if user_info:
                student_info[user_id] = user_info
    
    return student_info

def analyze_student_expirations():
    """Analyze expiration dates of orphaned undergraduate and graduate students"""
    
    # Load orphaned users group analysis
    try:
        with open('orphaned_users_group_analysis.json', 'r') as f:
            data = json.load(f)
            detailed_user_info = data['detailed_user_info']
    except FileNotFoundError:
        print("Error: orphaned_users_group_analysis.json not found. Run orphaned-users-group-analysis.py first.")
        return
    
    # Filter for undergraduate and graduate students
    student_users = {}
    target_groups = ['Undergraduate', 'Gradstudent']
    
    for user_id, user_info in detailed_user_info.items():
        if user_info['user_group'] in target_groups:
            student_users[user_id] = user_info
    
    print(f"Found {len(student_users)} students in orphaned users:")
    for group in target_groups:
        count = sum(1 for info in student_users.values() if info['user_group'] == group)
        print(f"  {group}: {count}")
    
    if not student_users:
        print("No undergraduate or graduate students found in orphaned users.")
        return
    
    print(f"\nFetching expiration dates for {len(student_users)} students...")
    
    # Process students in batches to get expiration info
    batch_size = 25
    student_ids = list(student_users.keys())
    all_student_expiry_info = {}
    
    for i in range(0, len(student_ids), batch_size):
        batch = student_ids[i:i + batch_size]
        print(f"Processing batch {i//batch_size + 1} ({len(batch)} students)...")
        
        batch_info = get_student_expiration_info_batch(batch)
        all_student_expiry_info.update(batch_info)
        
        print(f"Processed {min(i + batch_size, len(student_ids))}/{len(student_ids)} students...")
        
        # Small delay between batches
        time.sleep(1)
    
    # Analyze expiration status
    current_date = datetime.now()
    print(f"\nAnalysis date: {current_date.strftime('%Y-%m-%d')}")
    
    # Categorize students by expiration status
    expired_students = {}
    active_students = {}
    no_expiry_date = {}
    
    for user_id, student_info in all_student_expiry_info.items():
        if student_info['expiry_date']:
            if student_info['expiry_date'] < current_date:
                expired_students[user_id] = student_info
            else:
                active_students[user_id] = student_info
        else:
            no_expiry_date[user_id] = student_info
    
    # Generate analysis by group
    group_analysis = {}
    for group in target_groups:
        group_expired = sum(1 for info in expired_students.values() if info['user_group'] == group)
        group_active = sum(1 for info in active_students.values() if info['user_group'] == group)
        group_no_date = sum(1 for info in no_expiry_date.values() if info['user_group'] == group)
        group_total = group_expired + group_active + group_no_date
        
        group_analysis[group] = {
            'total': group_total,
            'expired': group_expired,
            'active': group_active,
            'no_expiry_date': group_no_date,
            'expired_percentage': (group_expired / group_total * 100) if group_total > 0 else 0
        }
    
    # Print results
    print(f"\n{'='*70}")
    print(f"STUDENT EXPIRATION ANALYSIS")
    print(f"{'='*70}")
    
    total_students = len(all_student_expiry_info)
    total_expired = len(expired_students)
    total_active = len(active_students)
    total_no_date = len(no_expiry_date)
    
    print(f"Total students analyzed: {total_students}")
    print(f"Students with missing expiration data: {len(student_users) - total_students}")
    
    print(f"\nOVERALL EXPIRATION STATUS:")
    print(f"{'Status':<20} {'Count':<10} {'Percentage'}")
    print("-" * 40)
    print(f"{'Expired':<20} {total_expired:<10} {total_expired/total_students*100:.1f}%")
    print(f"{'Active (not expired)':<20} {total_active:<10} {total_active/total_students*100:.1f}%")
    print(f"{'No expiry date':<20} {total_no_date:<10} {total_no_date/total_students*100:.1f}%")
    
    print(f"\nBY STUDENT GROUP:")
    print(f"{'Group':<15} {'Total':<8} {'Expired':<10} {'Active':<8} {'No Date':<10} {'% Expired'}")
    print("-" * 70)
    
    for group, analysis in group_analysis.items():
        print(f"{group:<15} {analysis['total']:<8} {analysis['expired']:<10} "
              f"{analysis['active']:<8} {analysis['no_expiry_date']:<10} {analysis['expired_percentage']:.1f}%")
    
    # Show sample expired students
    if expired_students:
        print(f"\nSAMPLE EXPIRED STUDENTS:")
        print(f"{'Name':<25} {'Group':<15} {'Primary ID':<18} {'Expired Date'}")
        print("-" * 80)
        
        count = 0
        for user_id, info in expired_students.items():
            if count >= 10:  # Show max 10 examples
                break
            name = f"{info['first_name']} {info['last_name']}".strip()
            if not name:
                name = "No name"
            expired_date = info['expiry_date'].strftime('%Y-%m-%d') if info['expiry_date'] else 'Unknown'
            print(f"{name:<25} {info['user_group']:<15} {info['primary_id']:<18} {expired_date}")
            count += 1
    
    # Save detailed report
    report = {
        'analysis_date': current_date.isoformat(),
        'summary': {
            'total_students_analyzed': total_students,
            'total_expired': total_expired,
            'total_active': total_active,
            'total_no_expiry_date': total_no_date,
            'overall_expired_percentage': (total_expired / total_students * 100) if total_students > 0 else 0
        },
        'by_group': group_analysis,
        'expired_students': {user_id: {
            **info,
            'expiry_date': info['expiry_date'].isoformat() if info['expiry_date'] else None,
            'days_expired': (current_date - info['expiry_date']).days if info['expiry_date'] else None
        } for user_id, info in expired_students.items()},
        'active_students': {user_id: {
            **info,
            'expiry_date': info['expiry_date'].isoformat() if info['expiry_date'] else None,
            'days_until_expiry': (info['expiry_date'] - current_date).days if info['expiry_date'] else None
        } for user_id, info in active_students.items()},
        'no_expiry_date_students': no_expiry_date
    }
    
    with open('student_expiration_analysis.json', 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\nDetailed analysis saved to: student_expiration_analysis.json")
    
    return report

if __name__ == "__main__":
    if not API_KEY:
        print("Error: ALMA_API_KEY not found in environment variables")
    else:
        analyze_student_expirations()