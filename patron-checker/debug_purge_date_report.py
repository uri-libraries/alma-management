#!/usr/bin/env python3
"""
Debug purge date and patron type extraction for Alma users.
"""
import os
import sys
import csv
import json
from dotenv import load_dotenv
import requests

def load_env():
    if os.path.exists('.env'):
        load_dotenv('.env')
    else:
        print("Error: .env file not found")
        sys.exit(1)

def get_user(api_key, base_url, primary_id):
    url = f"{base_url}/almaws/v1/users/{primary_id}?expand=full"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    try:
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch user {primary_id}: {response.status_code}")
            return None
    except Exception as e:
        print(f"Exception for user {primary_id}: {e}")
        return None

def main():
    load_env()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env file")
        sys.exit(1)
    ids = []
    with open('deactivated-all.txt', 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                ids.append(line.strip())
    # Only debug the first 3 users
    for primary_id in ids[:3]:
        print(f"\n--- Debugging user {primary_id} ---")
        user = get_user(api_key, base_url, primary_id)
        if user:
            print(json.dumps(user, indent=2))
            print("purge_date:", user.get('purge_date'))
            print("user_group:", user.get('user_group'))
        else:
            print("No user data returned.")

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
