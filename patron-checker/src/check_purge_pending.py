#!/usr/bin/env python3
"""
Check users from deactivated-all.txt - filter only those in PurgePending/DEL group.
"""
import os
import sys
import csv
import time
import requests
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

def read_ids(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def get_user_details(api_key, base_url, primary_id):
    url = f"{base_url}/almaws/v1/users/{primary_id}"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None

def main():
    load_env()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    
    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set")
        sys.exit(1)
    
    ids = read_ids('deactivated-all.txt')
    print(f"Found {len(ids)} IDs in deactivated-all.txt")
    print("Checking each user's group and expiration...\n")
    
    purge_pending_users = []
    other_group_users = []
    expired_users = []
    not_expired_users = []
    no_expiry_users = []
    failed_users = []
    
    for idx, primary_id in enumerate(ids):
        if (idx + 1) % 100 == 0:
            print(f"Processed {idx + 1}/{len(ids)} users...")
        
        time.sleep(0.1)
        user = get_user_details(api_key, base_url, primary_id)
        
        if not user:
            failed_users.append(primary_id)
            continue
        
        # Get user group
        user_group = user.get('user_group', {})
        group_value = user_group.get('value', '') if isinstance(user_group, dict) else ''
        
        # Check if in PurgePending or DEL group
        if group_value not in ['PurgePending', 'DEL']:
            other_group_users.append({'id': primary_id, 'group': group_value})
            continue
        
        purge_pending_users.append(primary_id)
        
        # Check expiry date
        expiry_date_str = user.get('expiry_date')
        if not expiry_date_str:
            no_expiry_users.append(primary_id)
        else:
            try:
                expiry_date = datetime.strptime(expiry_date_str.replace('Z', ''), '%Y-%m-%d').date()
                today = datetime.now().date()
                
                if expiry_date < today:
                    expired_users.append({'id': primary_id, 'expiry': expiry_date_str, 'group': group_value})
                else:
                    not_expired_users.append({'id': primary_id, 'expiry': expiry_date_str, 'group': group_value})
            except:
                no_expiry_users.append(primary_id)
    
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"Total IDs checked: {len(ids)}")
    print(f"Users in PurgePending/DEL: {len(purge_pending_users)}")
    print(f"Users in other groups: {len(other_group_users)}")
    print(f"Failed to fetch: {len(failed_users)}")
    print(f"\nOf the {len(purge_pending_users)} in PurgePending/DEL:")
    print(f"  - Expired: {len(expired_users)}")
    print(f"  - Not expired yet: {len(not_expired_users)}")
    print(f"  - No expiry date: {len(no_expiry_users)}")
    
    # Save results
    with open('purge_pending_analysis.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Primary ID', 'User Group', 'Expiry Date', 'Status'])
        
        for u in expired_users:
            writer.writerow([u['id'], u['group'], u['expiry'], 'EXPIRED'])
        for u in not_expired_users:
            writer.writerow([u['id'], u['group'], u['expiry'], 'NOT_EXPIRED'])
        for uid in no_expiry_users:
            writer.writerow([uid, 'PurgePending/DEL', '', 'NO_EXPIRY'])
    
    print(f"\nResults saved to: purge_pending_analysis.csv")

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
