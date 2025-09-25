import requests
import os
from dotenv import load_dotenv
import json
from collections import Counter
import concurrent.futures
import time

# Load environment variables
load_dotenv()

API_KEY = os.getenv('ALMA_API_KEY')
BASE_URL = os.getenv('ALMA_BASE_URL', 'https://api-na.hosted.exlibrisgroup.com/almaws/v1')

def get_user_details(user_id):
    """Fetch detailed user information including user group"""
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

def get_user_groups_batch(user_ids, max_workers=3):
    """Fetch user group information for multiple users concurrently"""
    user_groups = {}
    
    def fetch_single_user_group(user_id):
        try:
            # Add small delay to avoid overwhelming the server
            time.sleep(0.1)
            details = get_user_details(user_id)
            if details:
                # Extract user group information
                user_group = details.get('user_group', {})
                if isinstance(user_group, dict):
                    group_value = user_group.get('value', 'Unknown')
                    group_desc = user_group.get('desc', 'No description')
                else:
                    group_value = user_group if user_group else 'Unknown'
                    group_desc = 'No description'
                
                # Also get status
                status = details.get('status', {})
                if isinstance(status, dict):
                    status_value = status.get('value', 'Unknown')
                else:
                    status_value = status if status else 'Unknown'
                
                return user_id, {
                    'user_group': group_value,
                    'group_description': group_desc,
                    'status': status_value,
                    'first_name': details.get('first_name', ''),
                    'last_name': details.get('last_name', ''),
                    'primary_id': details.get('primary_id', user_id)
                }
        except Exception as e:
            print(f"Error fetching user group for {user_id}: {e}")
        return user_id, None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_user = {executor.submit(fetch_single_user_group, user_id): user_id for user_id in user_ids}
        
        for future in concurrent.futures.as_completed(future_to_user):
            user_id, user_info = future.result()
            if user_info:
                user_groups[user_id] = user_info
    
    return user_groups

def analyze_orphaned_user_groups():
    """Analyze user groups of all orphaned users"""
    
    # Load orphaned users list
    try:
        with open('orphaned_users_list.json', 'r') as f:
            data = json.load(f)
            orphaned_users = data['orphaned_users']
    except FileNotFoundError:
        print("Error: orphaned_users_list.json not found. Run orphaned-users-count.py first.")
        return
    
    print(f"Analyzing user groups for {len(orphaned_users)} orphaned users...")
    
    # Process users in batches
    batch_size = 50
    all_user_info = {}
    
    for i in range(0, len(orphaned_users), batch_size):
        batch = orphaned_users[i:i + batch_size]
        print(f"Processing batch {i//batch_size + 1} ({len(batch)} users)...")
        
        batch_info = get_user_groups_batch(batch)
        all_user_info.update(batch_info)
        
        print(f"Processed {min(i + batch_size, len(orphaned_users))}/{len(orphaned_users)} users...")
        
        # Small delay between batches
        time.sleep(1)
    
    # Analyze user groups
    group_counts = Counter()
    status_counts = Counter()
    
    for user_id, user_info in all_user_info.items():
        group_counts[user_info['user_group']] += 1
        status_counts[user_info['status']] += 1
    
    # Print analysis
    print(f"\n{'='*60}")
    print(f"ORPHANED USERS BY USER GROUP")
    print(f"{'='*60}")
    print(f"Total orphaned users analyzed: {len(all_user_info)}")
    print(f"Users with missing data: {len(orphaned_users) - len(all_user_info)}")
    
    print(f"\nUSER GROUP DISTRIBUTION:")
    print(f"{'Group':<30} {'Count':<10} {'Percentage'}")
    print("-" * 50)
    
    for group, count in group_counts.most_common():
        percentage = (count / len(all_user_info)) * 100 if all_user_info else 0
        print(f"{group:<30} {count:<10} {percentage:.1f}%")
    
    print(f"\nSTATUS DISTRIBUTION:")
    print(f"{'Status':<20} {'Count':<10} {'Percentage'}")
    print("-" * 40)
    
    for status, count in status_counts.most_common():
        percentage = (count / len(all_user_info)) * 100 if all_user_info else 0
        print(f"{status:<20} {count:<10} {percentage:.1f}%")
    
    # Show sample users by group
    print(f"\nSAMPLE USERS BY GROUP:")
    print("-" * 60)
    
    groups_shown = set()
    for user_id, user_info in list(all_user_info.items())[:20]:  # Show first 20 as examples
        group = user_info['user_group']
        if group not in groups_shown:
            name = f"{user_info['first_name']} {user_info['last_name']}".strip()
            if not name:
                name = "No name"
            print(f"{group}: {user_id} ({name}) - Status: {user_info['status']}")
            groups_shown.add(group)
            
            if len(groups_shown) >= 10:  # Show max 10 different groups
                break
    
    # Save detailed report
    report = {
        'total_orphaned_users': len(orphaned_users),
        'users_analyzed': len(all_user_info),
        'group_distribution': dict(group_counts),
        'status_distribution': dict(status_counts),
        'detailed_user_info': all_user_info
    }
    
    with open('orphaned_users_group_analysis.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nDetailed analysis saved to: orphaned_users_group_analysis.json")
    
    return report

if __name__ == "__main__":
    if not API_KEY:
        print("Error: ALMA_API_KEY not found in environment variables")
    else:
        analyze_orphaned_user_groups()