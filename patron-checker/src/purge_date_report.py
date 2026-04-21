#!/usr/bin/env python3
"""
Print all users in Alma who don't have an expiration date. Lists Primary ID, Email address, and Patron Type in the terminal
and also writes to a timestamped CSV file in patron-checker/outputs. Uses offset pagination to fetch all users, and handles API errors gracefully. Designed to run against a test environment with a limited number of users, 
but can be run against production by commenting out the MAX_USERS limiter. Make sure to set ALMA_API_KEY and ALMA_API_BASE_URL in a .env file before running.
"""

# Required packages. Since you might want to use this as a standalone script, I've listed them out here, though you
# could also just put them in a requirements.txt file:
import csv
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv
import requests


# Page limit for Alma API calls. Adjust as needed, but 100 is a good balance between speed and reliability.
# Requests will timeout after 30 seconds to avoid hanging indefinitely on a bad response. Adjust as needed based on your expected response times.
PAGE_LIMIT = 100
REQUEST_TIMEOUT = 30

# I've included a MAX_USERS limiter for demonstration, but comment this out in production to run against all users in Alma. 
MAX_USERS = 500

# Ensure you have an .env file with the Alma Base URL and API key. 
def load_env():
    if os.path.exists('.env'):
        load_dotenv('.env')
    else:
        print("Error: .env file not found")
        sys.exit(1)

# This function uses offset pagination to fetch all users from the Alma API. It yields user records one at a time, which is memory efficient for large datasets. It handles API errors gracefully by printing error messages to stderr and breaking the loop if an error occurs.
def get_all_users(api_key, base_url):
    """Yield user records from Alma using offset pagination."""
    offset = 0
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }

    while True:
        params = {
            'limit': PAGE_LIMIT,
            'offset': offset,
            'format': 'json',
            'expand': 'full'
        }
        url = f"{base_url.rstrip('/')}/almaws/v1/users"

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                verify=False,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            print(f"Error fetching users at offset {offset}: {exc}", file=sys.stderr)
            break

        if response.status_code != 200:
            print(
                f"Error fetching users at offset {offset}: {response.status_code} {response.text}",
                file=sys.stderr,
            )
            break
# If we get here, we have a successful response. Parse the JSON and yield user records.
        data = response.json()
        users = data.get('user', []) or []
        if not users:
            break

        for user in users:
            yield user

        total = data.get('total_record_count')
        offset += PAGE_LIMIT
        if total is None:
            if len(users) < PAGE_LIMIT:
                break
        elif offset >= total:
            break

        time.sleep(0.2) # Sleep briefly to avoid hitting API rate limits

def get_preferred_email(user):
    """Return the preferred email address, or the first email if none is marked preferred."""
    emails = user.get('contact_info', {}).get('email', []) or []
    for email in emails:
        if email.get('preferred'):
            return email.get('email_address', '')
    if emails:
        return emails[0].get('email_address', '')
    return ''

def get_expiration_date(user):
    """Return Alma's raw user expiration field."""
    return user.get('expiry_date')

def build_output_path():
    """Return a timestamped CSV path under patron-checker/outputs."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    output_dir = os.path.join(project_dir, 'outputs')
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(output_dir, f'users_without_expiration_{timestamp}.csv')

def main():
    load_env()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env file")
        sys.exit(1)
        
# This is the main processing loop. It iterates through all users, checks for the presence of an expiration date, and writes those without one to a CSV file. It also keeps track of totals and prints progress updates to stderr.
    total_users = 0
    missing_expiration = 0
    output_path = build_output_path()

    with open(output_path, 'w', encoding='utf-8', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Primary ID', 'Email Address', 'Patron Type'])

        for user in get_all_users(api_key, base_url):
            total_users += 1
            if MAX_USERS and total_users > MAX_USERS:
                print(f"Reached demo limit ({MAX_USERS}) - stopping early", file=sys.stderr)
                break
            expiration_date = get_expiration_date(user)
            if expiration_date:
                continue

            missing_expiration += 1
            primary_id = user.get('primary_id', '')
            email = get_preferred_email(user)
            patron_type = user.get('user_group', {}).get('value', '')
            writer.writerow([primary_id, email, patron_type])

            if total_users % 100 == 0:
                print(f"Processed {total_users} users...", file=sys.stderr)

# This final block prints a summary of the results to stderr, including the total number of users processed, how many were missing expiration dates, and where the CSV was saved.
    print("\nSummary:", file=sys.stderr)
    print(f"Total users processed: {total_users}", file=sys.stderr)
    print(f"Users without expiration date: {missing_expiration}", file=sys.stderr)
    print(f"CSV written to: {output_path}", file=sys.stderr)

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
