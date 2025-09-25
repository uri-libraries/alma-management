import requests
import os
from dotenv import load_dotenv
from collections import defaultdict, Counter
import json
import concurrent.futures
import threading
import time

# Load environment variables
load_dotenv()

API_KEY = os.getenv('ALMA_API_KEY')
BASE_URL = os.getenv('ALMA_BASE_URL', 'https://api-na.hosted.exlibrisgroup.com/almaws/v1')

def get_user_details(user_id):
    """Fetch detailed user information including identifiers"""
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

def get_all_users(max_users=None):
    """Fetch all users from Alma API with pagination"""
    users = []
    offset = 0
    limit = 100  # Max allowed by Alma API
    
    headers = {
        'Authorization': f'apikey {API_KEY}',
        'Accept': 'application/json'
    }
    
    while True:
        url = f"{BASE_URL}/users"
        params = {
            'limit': limit,
            'offset': offset,
            'format': 'json',
            'expand': 'full'  # Try to get more detailed info
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if 'user' not in data:
                break
                
            batch_users = data['user']
            if not batch_users:
                break
                
            users.extend(batch_users)
            print(f"Fetched {len(users)} users so far...")
            
            # Stop if we've reached the max_users limit
            if max_users and len(users) >= max_users:
                users = users[:max_users]
                print(f"Reached limit of {max_users} users")
                break
            
            # Check if we've got all users
            if len(batch_users) < limit:
                break
                
            offset += limit
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching users: {e}")
            break
    
    return users

def get_user_details_batch(user_ids, max_workers=3):
    """Fetch detailed user information for multiple users concurrently"""
    user_details = {}
    
    def fetch_single_user(user_id):
        try:
            # Add small delay to avoid overwhelming the server
            time.sleep(0.1)
            details = get_user_details(user_id)
            if details:
                return user_id, details
        except Exception as e:
            print(f"Error fetching user {user_id}: {e}")
        return user_id, None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_user = {executor.submit(fetch_single_user, user_id): user_id for user_id in user_ids}
        
        for future in concurrent.futures.as_completed(future_to_user):
            user_id, details = future.result()
            if details:
                user_details[user_id] = details
    
    return user_details

def analyze_user_id_types(users):
    """Analyze User ID Types across all users"""
    
    # Track user ID types
    id_type_counts = Counter()
    users_with_id_types = defaultdict(set)
    total_users = len(users)
    
    print(f"\nAnalyzing ID types for {total_users} users...")
    
    # First, check if user_identifier is already in the bulk data
    users_needing_details = []
    users_with_identifiers = 0
    
    for user in users:
        if 'user_identifier' in user and user['user_identifier']:
            users_with_identifiers += 1
        else:
            users_needing_details.append(user.get('primary_id'))
    
    print(f"Users with identifiers in bulk data: {users_with_identifiers}")
    print(f"Users needing detailed fetch: {len(users_needing_details)}")
    
    # Process users that already have identifier data
    for user in users:
        if 'user_identifier' in user and user['user_identifier']:
            process_user_identifiers(user, user['user_identifier'], id_type_counts, users_with_id_types)
    
        # Fetch detailed info for remaining users in batches
        if users_needing_details:
            print(f"Fetching detailed information for {len(users_needing_details)} users...")
            
            batch_size = 5  # Small batch for debugging
            for i in range(0, len(users_needing_details), batch_size):
                batch = users_needing_details[i:i + batch_size]
                print(f"Processing batch {i//batch_size + 1} ({len(batch)} users)...")
                
                detailed_users = get_user_details_batch(batch)
                
                for user_id, detailed_user in detailed_users.items():
                    identifiers = detailed_user.get('user_identifier', [])
                    
                    # Debug: Print actual identifier structure for first user
                    if i == 0 and user_id == batch[0]:
                        print(f"\nDEBUG - User {user_id} identifier structure:")
                        print(f"Primary ID: {detailed_user.get('primary_id')}")
                        print(f"Identifiers: {json.dumps(identifiers, indent=2)}")
                    
                    process_user_identifiers({'primary_id': user_id}, identifiers, id_type_counts, users_with_id_types)
                
                print(f"Processed {min(i + batch_size, len(users_needing_details))}/{len(users_needing_details)} users...")
    
    return id_type_counts, users_with_id_types, total_users

def process_user_identifiers(user, identifiers, id_type_counts, users_with_id_types):
    """Process identifiers for a single user"""
    user_id = user.get('primary_id', 'Unknown')
    
    # Handle case where user_identifier might be a single dict instead of list
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    
    user_id_types = set()
    
    # First, add the primary ID as a "PRIMARY_ID" type
    if user_id and user_id != 'Unknown':
        user_id_types.add('PRIMARY_ID')
        id_type_counts['PRIMARY_ID'] += 1
    
    # Then process the additional identifiers
    for identifier in identifiers:
        if isinstance(identifier, dict):
            # Try different possible structures
            id_type = None
            if 'id_type' in identifier:
                if isinstance(identifier['id_type'], dict):
                    id_type = identifier['id_type'].get('value', 'Unknown')
                else:
                    id_type = identifier['id_type']
            elif 'type' in identifier:
                if isinstance(identifier['type'], dict):
                    id_type = identifier['type'].get('value', 'Unknown')
                else:
                    id_type = identifier['type']
            
            if id_type:
                user_id_types.add(id_type)
                id_type_counts[id_type] += 1
    
    # Track which users have which ID types
    for id_type in user_id_types:
        users_with_id_types[id_type].add(user_id)

def print_analysis(id_type_counts, users_with_id_types, total_users):
    """Print the analysis results"""
    
    print(f"\n{'='*60}")
    print(f"USER ID TYPE ANALYSIS")
    print(f"{'='*60}")
    print(f"Total Users Analyzed: {total_users}")
    print(f"Total User ID Instances: {sum(id_type_counts.values())}")
    print(f"\n{'ID Type':<20} {'Count':<10} {'Users':<10} {'% of Users':<12}")
    print(f"{'-'*60}")
    
    if not id_type_counts:
        print("No ID types found! Check the debug output above.")
        return
    
    # Sort by percentage of users (descending)
    sorted_types = sorted(users_with_id_types.items(), 
                         key=lambda x: len(x[1]), reverse=True)
    
    for id_type, user_set in sorted_types:
        count = id_type_counts[id_type]
        unique_users = len(user_set)
        percentage = (unique_users / total_users) * 100 if total_users > 0 else 0
        
        print(f"{id_type:<20} {count:<10} {unique_users:<10} {percentage:>8.1f}%")
    
    print(f"\n{'='*60}")
    
    # Additional statistics
    if users_with_id_types:
        users_with_multiple_types = sum(1 for user_id in set().union(*users_with_id_types.values()) 
                                       if sum(1 for type_users in users_with_id_types.values() 
                                             if user_id in type_users) > 1)
        
        print(f"Users with multiple ID types: {users_with_multiple_types}")
        print(f"Average ID types per user: {sum(id_type_counts.values()) / total_users:.2f}")

def save_detailed_report(id_type_counts, users_with_id_types, total_users):
    """Save detailed report to JSON file"""
    
    report = {
        'summary': {
            'total_users': total_users,
            'total_id_instances': sum(id_type_counts.values()),
            'unique_id_types': len(id_type_counts)
        },
        'id_type_analysis': {}
    }
    
    for id_type, user_set in users_with_id_types.items():
        count = id_type_counts[id_type]
        unique_users = len(user_set)
        percentage = (unique_users / total_users) * 100 if total_users > 0 else 0
        
        report['id_type_analysis'][id_type] = {
            'total_instances': count,
            'unique_users': unique_users,
            'percentage_of_users': round(percentage, 2)
        }
    
    with open('user_id_type_analysis.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nDetailed report saved to: user_id_type_analysis.json")

def main():
    """Main function to run the analysis"""
    
    if not API_KEY:
        print("Error: ALMA_API_KEY not found in environment variables")
        return
    
    print("Starting User ID Type analysis...")
    print("This will fetch detailed information for each user and may take a while...")
    
    # Fetch first 5 users for testing and debugging
    users = get_all_users(max_users=5)
    
    if not users:
        print("No users found or error fetching users")
        return
    
    # Analyze user ID types
    id_type_counts, users_with_id_types, total_users = analyze_user_id_types(users)
    
    # Print analysis
    print_analysis(id_type_counts, users_with_id_types, total_users)
    
    # Save detailed report
    if id_type_counts:
        save_detailed_report(id_type_counts, users_with_id_types, total_users)

if __name__ == "__main__":
    main()