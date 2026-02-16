#!/usr/bin/env python3
"""
Verify PurgePending group: check all members have passed expiration date.
"""
import os
import sys
import requests
import time
import json
from datetime import datetime
from dotenv import load_dotenv

def load_env():
    if os.path.exists('.env'):
        load_dotenv('.env')
    elif os.path.exists('../.env'):
        load_dotenv('../.env')
    else:
        print("Error: .env file not found")
        sys.exit(1)

def get_user_ids_in_group(api_key, base_url, group_name, limit=100):
    """Fetch primary IDs of all users in a specific user group."""
    all_user_ids = []
    offset = 0
    
    while True:
        url = f"{base_url}/almaws/v1/users"
        params = {
            'user_group': group_name,
            'limit': limit,
            'offset': offset
        }
        headers = {
            'Authorization': f'apikey {api_key}',
            'Accept': 'application/json'
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, verify=False)
            if response.status_code == 200:
                data = response.json()
                users = data.get('user', [])
                if not users:
                    break
                
                # Extract only primary IDs
                user_ids = [u.get('primary_id') for u in users if u.get('primary_id')]
                all_user_ids.extend(user_ids)
                
                total_record_count = data.get('total_record_count', 0)
                print(f"Fetched {len(all_user_ids)}/{total_record_count} user IDs...")
                
                if len(all_user_ids) >= total_record_count:
                    break
                offset += limit
            else:
                print(f"Error fetching users: {response.status_code} - {response.text}")
                break
        except Exception as e:
            print(f"Exception: {e}")
            break
    
    return all_user_ids

def get_user_details(api_key, base_url, primary_id, retries=3):
    """Fetch full details for a single user with retry logic."""
    url = f"{base_url}/almaws/v1/users/{primary_id}"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=30)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:  # Rate limit
                print(f"Rate limited, waiting 60s...")
                time.sleep(60)
                continue
            else:
                return None
        except Exception as e:
            if attempt < retries - 1:
                print(f"Error fetching {primary_id}, retrying... ({e})")
                time.sleep(5)
            else:
                return None
    return None

def check_expiration(users):
    """Check if users have passed their expiration date."""
    # This function is no longer used, kept for compatibility
    pass

def main():
    load_env()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    
    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env file")
        sys.exit(1)
    
    group_name = 'PurgePending'
    print(f"Fetching user IDs in group: {group_name}")
    print("=" * 60)
    
    user_ids = get_user_ids_in_group(api_key, base_url, group_name)
    
    print("\n" + "=" * 60)
    print(f"Total users in {group_name}: {len(user_ids)}")
    print("=" * 60)
    
    if not user_ids:
        print("No users found in this group.")
        return
    
    print("\nFetching full details for each user (this may take a while)...")
    
    # Try to load progress from previous run
    progress_file = 'verify_purge_progress.json'
    if os.path.exists(progress_file):
        with open(progress_file, 'r') as f:
            progress = json.load(f)
            expired_users = progress.get('expired_users', [])
            not_expired_users = progress.get('not_expired_users', [])
            no_expiration_users = progress.get('no_expiration_users', [])
            failed_users = progress.get('failed_users', [])
            start_idx = progress.get('last_index', 0)
            print(f"Resuming from user {start_idx + 1}...")
    else:
        expired_users = []
        not_expired_users = []
        no_expiration_users = []
        failed_users = []
        start_idx = 0
    
    for idx, primary_id in enumerate(user_ids[start_idx:], start=start_idx):
        if (idx + 1) % 100 == 0:
            print(f"Processed {idx + 1}/{len(user_ids)} users...")
            # Save progress every 100 users
            with open(progress_file, 'w') as f:
                json.dump({
                    'last_index': idx + 1,
                    'expired_users': expired_users,
                    'not_expired_users': not_expired_users,
                    'no_expiration_users': no_expiration_users,
                    'failed_users': failed_users
                }, f)
        
        time.sleep(0.2)  # Rate limiting delay
        user = get_user_details(api_key, base_url, primary_id)
        if not user:
            failed_users.append(primary_id)
            continue
        
        expiry_date_str = user.get('expiry_date')
        
        if not expiry_date_str:
            no_expiration_users.append(primary_id)
            continue
        
        try:
            # Parse expiry_date (format: YYYY-MM-DDZ)
            expiry_date = datetime.strptime(expiry_date_str.replace('Z', ''), '%Y-%m-%d').date()
            today = datetime.now().date()
            
            if expiry_date < today:
                expired_users.append({'primary_id': primary_id, 'expiry_date': expiry_date_str})
            else:
                not_expired_users.append({'primary_id': primary_id, 'expiry_date': expiry_date_str})
        except Exception as e:
            print(f"Error parsing expiry date for {primary_id}: {e}")
            no_expiration_users.append(primary_id)
    
    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS FOR PURGEPENDING GROUP")
    print("=" * 60)
    print(f"\n📊 TOTAL USERS IN GROUP: {len(user_ids)}")
    print(f"✅ Users with expired dates (passed expiration): {len(expired_users)}")
    print(f"⚠️  Users NOT yet expired: {len(not_expired_users)}")
    print(f"⚠️  Users with no expiration date: {len(no_expiration_users)}")
    if failed_users:
        print(f"❌ Failed to fetch details: {len(failed_users)}")
    
    if not_expired_users:
        print("\n" + "=" * 60)
        print("⚠️  USERS NOT YET EXPIRED:")
        print("=" * 60)
        for user in not_expired_users:
            print(f"  {user['primary_id']} (expires: {user['expiry_date']})")
    
    if no_expiration_users:
        print("\n" + "=" * 60)
        print("⚠️  USERS WITH NO EXPIRATION DATE:")
        print("=" * 60)
        for primary_id in no_expiration_users:
            print(f"  {primary_id}")
    
    if not not_expired_users and not no_expiration_users:
        print("\n" + "=" * 60)
        print("✅ ALL USERS IN PURGEPENDING HAVE PASSED THEIR EXPIRATION DATE")
        print("=" * 60)

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
