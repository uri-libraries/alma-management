#!/usr/bin/env python3
"""
Alma Expiration Checker (Python)

Finds users who expired before a user-supplied date and exports results to CSV/JSON.

Behavior:
- Prompts for Production or Sandbox environment and loads `.env` or `.env.sandbox`.
- Prompts for a cutoff date (YYYY-MM-DD) and finds users whose expiration date is strictly before that date.
- Fetches users via Alma Users API with pagination.
- Exports results to a timestamped CSV and JSON file.

If you haven't already, you'll need to use pip to install requests and python-dotenv. 

Save as `expiration-checker.py` and run with:

    pip install requests python-dotenv
    python3 expiration-checker.py

"""


# === Import required libraries ===
import os
import sys
import csv
import json
import time
from datetime import datetime, date
import requests
from requests.exceptions import RequestException
import re
from dotenv import load_dotenv

# === Configuration and network settings ===
# Timeout for HTTP requests (in seconds)
REQUEST_TIMEOUT = 30
# Number of users to fetch per API call (pagination)
PAGE_LIMIT = 50
# Limit number of users processed for quick testing (set to None to disable)
QUICK_SCAN_LIMIT = 1000
# Print the first user returned for debugging if True
DEBUG_SAMPLE = False

############################################################
# Function: select_environment
# Prompts the user to select Production or Sandbox environment.
# Loads the appropriate .env file for API credentials.
############################################################
def select_environment():
    print("\nSelect environment:")
    print("1. Production")
    print("2. Sandbox")
    while True:
        choice = input("\nEnter choice (1 or 2): ").strip()
        if choice == '1':
            if os.path.exists('.env'):
                load_dotenv('.env')
                print('Loaded Production environment')
                return 'production'
            else:
                print('Error: .env file not found')
                sys.exit(1)
        elif choice == '2':
            if os.path.exists('.env.sandbox'):
                load_dotenv('.env.sandbox')
                print('Loaded Sandbox environment')
                return 'sandbox'
            else:
                print('Error: .env.sandbox file not found')
                sys.exit(1)
        else:
            print('Invalid choice. Please enter 1 or 2.')

# This is the prompt for the cutoff date
############################################################
# Function: prompt_for_date
# Prompts the user to enter a cutoff date in YYYY-MM-DD format.
# Returns a datetime object representing the end of that day.
############################################################
def prompt_for_date():
    while True:
        s = input('\nEnter cutoff date (YYYY-MM-DD): ').strip()
        try:
            d = datetime.strptime(s, '%Y-%m-%d').date()
            return datetime(d.year, d.month, d.day, 23, 59, 59)
        except Exception:
            print('Invalid date format. Use YYYY-MM-DD.')


############################################################
# Function: parse_alma_date
# Tries to parse various Alma date formats into a datetime object.
# Returns None if parsing fails.
############################################################
def parse_alma_date(s):
    if not s:
        return None
    s = str(s).strip()
    # Try several common formats, return a datetime
    fmts = ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S']
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            # If format was date-only, dt will be at midnight; that's fine
            return dt
        except Exception:
            continue
    # Handle ISO with Z by replacing Z with +00:00 for fromisoformat
    try:
        if s.endswith('Z'):
            s2 = s.replace('Z', '+00:00')
            return datetime.fromisoformat(s2)
        return datetime.fromisoformat(s)
    except Exception:
        return None


############################################################
# Function: extract_email_from_contact
# Extracts the preferred email address from a user's contact info.
# Returns an empty string if not found.
############################################################
def extract_email_from_contact(contact_info):
    if not contact_info:
        return ''
    emails = contact_info.get('email', [])
    if not emails:
        return ''
    # prefer preferred email
    preferred = [e for e in emails if e.get('preferred')]
    if preferred:
        return preferred[0].get('email_address', '')
    return emails[0].get('email_address', '')


############################################################
# Function: get_all_users
# Generator that fetches all users from Alma via paginated API calls.
# Yields each user as a dictionary.
############################################################
def get_all_users(api_key, base_url, q=None):
    limit = PAGE_LIMIT
    offset = 0
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }

    while True:
        params = {
            'limit': limit,
            'offset': offset,
            'format': 'json',
            'expand': 'full'
        }
        if q:
            params['q'] = q
        url = f"{base_url.rstrip('/')}/almaws/v1/users"
        print(f"Fetching users: offset={offset} limit={limit}")
        try:
            resp = requests.get(url, headers=headers, params=params, verify=False, timeout=REQUEST_TIMEOUT)
        except RequestException as e:
            print(f"Request error: {e}")
            break
        if resp.status_code != 200:
            print(f"Failed to fetch users: {resp.status_code} {resp.text}")
            break
        data = resp.json()
        users = data.get('user', []) or []
        print(f"  Received {len(users)} users")
        if not users:
            break
        for user in users:
            yield user
        total = data.get('total_record_count')
        offset += limit
        if total is None:
            # no total provided - stop when fewer than limit returned
            if len(users) < limit:
                break
        else:
            if offset >= total:
                break
        # be kind to API
        time.sleep(0.2)


############################################################
# Function: sanitize_group_name
# Returns a filesystem-safe version of a group name for filenames.
############################################################
def sanitize_group_name(name: str) -> str:
    if not name:
        return 'group'
    s = name.strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Za-z0-9_\-]", "", s)
    return s or 'group'


############################################################
# Function: get_user_groups
# Fetches user groups from Alma configuration endpoint.
# Returns a list of group names.
############################################################
def get_user_groups(api_key, base_url):
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    groups = []
    offset = 0
    limit = 200
    while True:
        params = {'limit': limit, 'offset': offset}
        url = f"{base_url.rstrip('/')}/almaws/v1/conf/user_groups"
        try:
            resp = requests.get(url, headers=headers, params=params, verify=False, timeout=REQUEST_TIMEOUT)
        except RequestException as e:
            print(f"Failed to fetch user groups: {e}")
            break
        if resp.status_code != 200:
            print(f"Failed to fetch user groups: {resp.status_code} {resp.text}")
            break
        data = resp.json()
        items = data.get('user_group') or data.get('user_groups') or []
        if not items:
            break
        for g in items:
            name = g.get('value') or g.get('desc') or g.get('code') or g.get('name')
            if name:
                groups.append(str(name))
        total = data.get('total_record_count')
        offset += limit
        if total is None:
            if len(items) < limit:
                break
        else:
            if offset >= total:
                break
        time.sleep(0.2)
    return groups


############################################################
# Function: collect_expired_users
# Iterates through all users and collects those whose expiration date
# is before or equal to the cutoff date. Returns the list and total scanned.
############################################################
def collect_expired_users(api_key, base_url, cutoff_date, q=None, max_processed=None):
    results = []
    count = 0
    # Apply quick-scan limiter if provided and caller didn't pass a max
    if max_processed is None and QUICK_SCAN_LIMIT:
        max_processed = QUICK_SCAN_LIMIT
        print(f"Quick-scan limiter active: will stop after {max_processed} users")
    for user in get_all_users(api_key, base_url, q=q):
        count += 1
        if count == 1 and DEBUG_SAMPLE:
            try:
                print('\n--- Debug: sample user (first returned) ---')
                print('Available keys:', ', '.join(sorted(user.keys())))
                # Show commonly relevant fields
                sample = {
                    'primary_id': user.get('primary_id'),
                    'expiry_date': user.get('expiry_date'),
                    'expiration_date': user.get('expiration_date'),
                    'contact_info_keys': list(user.get('contact_info', {}).keys()) if isinstance(user.get('contact_info'), dict) else None,
                    'user_group': user.get('user_group')
                }
                print(json.dumps(sample, indent=2, default=str))
            except Exception as e:
                print('Debug sample error:', e)
        if max_processed and count > max_processed:
            print(f"Reached scanning limit ({max_processed}) - stopping early")
            break
        primary_id = user.get('primary_id') or user.get('primaryId') or user.get('primary')
        first_name = user.get('first_name') or user.get('firstName') or ''
        last_name = user.get('last_name') or user.get('lastName') or ''
        # expiration might be named several ways in different responses
        expiration_raw = user.get('expiration_date') or user.get('expiry_date') or user.get('expirationDate') or user.get('expiryDate') or user.get('expiration')
        expiration = parse_alma_date(expiration_raw)
        email = extract_email_from_contact(user.get('contact_info') or {})

        # Compare datetimes: include expiry on the cutoff date (<=)
        if expiration and cutoff_date and expiration <= cutoff_date:
            results.append({
                'primary_id': primary_id,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'expiration_date': expiration.isoformat()
            })

    return results, count


############################################################
# Function: save_csv
# Saves the list of expired users to a timestamped CSV file.
# Returns the filename.
############################################################
def save_csv(rows, environment, suffix=None):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if suffix:
        filename = f"expired_users_{environment}_{suffix}_{ts}.csv"
    else:
        filename = f"expired_users_{environment}_{ts}.csv"
    fieldnames = ['primary_id', 'first_name', 'last_name', 'email', 'expiration_date']
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return filename


############################################################
# Function: save_json
# Saves the list of expired users to a timestamped JSON file.
# Returns the filename.
############################################################
def save_json(rows, environment, suffix=None):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if suffix:
        filename = f"expired_users_{environment}_{suffix}_{ts}.json"
    else:
        filename = f"expired_users_{environment}_{ts}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(rows, f, indent=2)
    return filename


############################################################
# Main program logic
# - Prints header
# - Loads environment and API credentials
# - Prompts for cutoff date
# - Scans users and collects expired ones
# - Saves results to CSV and JSON
############################################################
def main():
    print('=' * 60)
    print('ALMA EXPIRATION CHECKER (Python)')
    print('=' * 60)

    env = select_environment()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')

    if not api_key or not base_url:
        print('Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in the chosen .env')
        sys.exit(1)

    # simple interactive flow: prompt for cutoff and scan all users
    cutoff = prompt_for_date()
    print(f"\nFinding users expired before {cutoff.isoformat()}...")

    rows, scanned = collect_expired_users(api_key, base_url, cutoff)
    print(f"\nScanned {scanned} users; found {len(rows)} expired users")

    if rows:
        csv_file = save_csv(rows, env)
        json_file = save_json(rows, env)
        print(f"\nSaved CSV: {csv_file}")
        print(f"Saved JSON: {json_file}")
    else:
        print('\nNo expired users found for that cutoff date.')

    print('\nDone!')


############################################################
# Script entry point
# - Suppresses SSL warnings for demo purposes
# - Ensures QUICK_SCAN_LIMIT is defined
# - Calls main()
############################################################
if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        QUICK_SCAN_LIMIT
    except NameError:
        QUICK_SCAN_LIMIT = None
    main()
