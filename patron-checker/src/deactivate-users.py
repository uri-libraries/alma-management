#!/usr/bin/env python3
"""
Alma Bulk User Deactivation Script
Brandon Katzir
"""

import os
import sys
import requests
import json
import time
from datetime import datetime
from dotenv import load_dotenv
import argparse

# Limiter: Set to an integer to process only that many users. Comment out to process all.
# MAX_DEACTIVATIONS = 30  # Change this value or comment out to disable limit

def select_environment_arg():
    parser = argparse.ArgumentParser(description="Alma Bulk User Deactivation Script")
    parser.add_argument('--sandbox', action='store_true', help='Use sandbox environment')
    args = parser.parse_args()
    if args.sandbox:
        env_file = '.env.sandbox'
        env_name = 'sandbox'
    else:
        env_file = '.env'
        env_name = 'production'
    if not os.path.exists(env_file):
        print(f"Error: {env_file} file not found")
        sys.exit(1)
    load_dotenv(env_file)
    print(f"Loaded {env_name.capitalize()} environment")
    return env_name

def read_identifiers(filename):
    """Read identifiers from a file.

    Accepts plain lists (one ID per line) or CSV-style rows. The primary
    identifier is taken from the first column. If a header row is present
    (e.g. "Primary ID"), it will be skipped.
    """
    import csv

    ids = []
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            first = row[0].strip()
            if not first:
                continue
            ids.append(first)

    # If the first value looks like a header (contains letters), drop it
    if ids and any(c.isalpha() for c in ids[0]):
        ids = ids[1:]

    return ids

def get_user(api_key, base_url, primary_id):
    url = f"{base_url}/almaws/v1/users/{primary_id}"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    try:
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"  ❌ Failed to fetch user {primary_id}: {response.status_code}")
            return None
    except Exception as e:
        print(f"  ❌ Exception fetching user {primary_id}: {e}")
        return None

def deactivate_user(api_key, base_url, primary_id, user_data):
    url = f"{base_url}/almaws/v1/users/{primary_id}"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    # Set status to INACTIVE as a dictionary (Alma API expects this structure)
    user_data['status'] = { 'value': 'INACTIVE' }
    # Remove problematic fields if present
    for field in ['link', 'proxy_for_user', 'rs_libraries']:
        user_data.pop(field, None)
    # Remove invalid phone types
    if 'contact_info' in user_data and 'phone' in user_data['contact_info']:
        valid_types = {'mobile', 'home', 'office', 'other'}
        user_data['contact_info']['phone'] = [
            p for p in user_data['contact_info']['phone']
            if isinstance(p.get('phone_type', ''), str) and p.get('phone_type', '').lower() in valid_types
        ]
    # Deduplicate identifiers
    if 'user_identifier' in user_data:
        seen = set()
        deduped = []
        for ident in user_data['user_identifier']:
            val = ident.get('value')
            if val and val not in seen:
                deduped.append(ident)
                seen.add(val)
        user_data['user_identifier'] = deduped
    try:
        response = requests.put(url, headers=headers, data=json.dumps(user_data), verify=False)
        if response.status_code in (200, 204):
            return {'success': True}
        else:
            error_msg = response.text
            print(f"  ❌ Failed to deactivate {primary_id}: {error_msg}")
            return {'success': False, 'error': error_msg}
    except Exception as e:
        print(f"  ❌ Exception deactivating {primary_id}: {e}")
        return {'success': False, 'error': str(e)}

def main():
    print("=" * 60)
    print("ALMA BULK USER DEACTIVATION TOOL (KATZIR)")
    print("=" * 60)

    environment = select_environment_arg()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')

    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env file")
        sys.exit(1)

    filename = 'deactivate.txt'
    print(f"\nReading identifiers from {filename}...")
    identifiers = read_identifiers(filename)
    print(f"✅ Found {len(identifiers)} identifiers to process")

    print("\n" + ('⚠️  ' * 20))
    print(f"WARNING: This will change {len(identifiers)} users from ACTIVE to INACTIVE")
    print(f"Environment: {environment}")
    print('⚠️  ' * 20)
    # Remove confirmation input for automation
    # confirmation = input("\nAre you sure you want to proceed? (yes/no): ").strip().lower()
    # if confirmation not in ('yes', 'y'):
    #     print("\n❌ Operation cancelled by user")
    #     sys.exit(0)

    print("\n" + ('-' * 60))
    print("Processing users...")
    print('-' * 60)

    successful = []
    failed = []
    skipped = []

    for idx, primary_id in enumerate(identifiers):
        # Limiter: skip if over MAX_DEACTIVATIONS
        if 'MAX_DEACTIVATIONS' in globals() and MAX_DEACTIVATIONS and idx >= MAX_DEACTIVATIONS:
            print(f"Limiter reached: processed {MAX_DEACTIVATIONS} users. Remove or comment out MAX_DEACTIVATIONS to process all.")
            break
        print(f"\n[{idx + 1}/{len(identifiers)}] Processing: {primary_id}")

        user_data = get_user(api_key, base_url, primary_id)
        if not user_data:
            failed.append({'user_id': primary_id, 'reason': 'Failed to fetch user'})
            continue

        current_status = user_data.get('status', {}).get('value') if isinstance(user_data.get('status'), dict) else user_data.get('status')
        print(f"  Current status: {current_status}")

        if current_status == 'INACTIVE':
            print("  ℹ️  Already inactive - skipping")
            skipped.append(primary_id)
            continue

        result = deactivate_user(api_key, base_url, primary_id, user_data)
        if result['success']:
            print("  ✅ Successfully deactivated")
            successful.append(primary_id)
        else:
            print("  ❌ Failed to deactivate")
            failed.append({'user_id': primary_id, 'reason': result.get('error', 'Update request failed')})

        # Save progress every 100 users
        if (idx + 1) % 100 == 0:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            with open(f"deactivated_progress_{timestamp}.txt", 'w', encoding='utf-8') as f:
                f.write('\n'.join(successful))
            with open(f"already_inactive_progress_{timestamp}.txt", 'w', encoding='utf-8') as f:
                f.write('\n'.join(skipped))
            with open(f"deactivation_failed_progress_{timestamp}.json", 'w', encoding='utf-8') as f:
                json.dump(failed, f, indent=2)
            print(f"Progress saved after {idx + 1} users.")
        time.sleep(0.3)

    print("\n" + ('=' * 60))
    print("SUMMARY")
    print('=' * 60)
    print(f"\nTotal processed: {len(identifiers)}")
    print(f"✅ Successfully deactivated: {len(successful)}")
    print(f"ℹ️  Already inactive (skipped): {len(skipped)}")
    print(f"❌ Failed: {len(failed)}")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if successful:
        success_file = f"deactivated_{timestamp}.txt"
        with open(success_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(successful))
        print(f"\n✅ Successfully deactivated users saved to: {success_file}")

    if skipped:
        skipped_file = f"already_inactive_{timestamp}.txt"
        with open(skipped_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(skipped))
        print(f"ℹ️  Already inactive users saved to: {skipped_file}")

    if failed:
        failed_file = f"deactivation_failed_{timestamp}.json"
        with open(failed_file, 'w', encoding='utf-8') as f:
            json.dump(failed, f, indent=2)
        print(f"❌ Failed deactivations saved to: {failed_file}")

    report = {
        'timestamp': timestamp,
        'environment': environment,
        'total_processed': len(identifiers),
        'successful_count': len(successful),
        'skipped_count': len(skipped),
        'failed_count': len(failed),
        'successful_users': successful,
        'skipped_users': skipped,
        'failed_users': failed
    }
    report_file = f"deactivation_report_{timestamp}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    print(f"\n📄 Detailed report saved to: {report_file}")

    print("\n" + ('=' * 60))
    print("Done!")
    print('=' * 60)

if __name__ == '__main__':
    # Suppress SSL warnings since we're using verify=False
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
