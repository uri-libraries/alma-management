#!/usr/bin/env python3
"""
Generate purge date and patron type report for Alma users.
"""
import os
import sys
import csv
import json
from datetime import datetime
from dotenv import load_dotenv
import requests

def load_env():
    if os.path.exists('.env'):
        load_dotenv('.env')
    else:
        print("Error: .env file not found")
        sys.exit(1)

def read_ids(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

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
            return None
    except Exception:
        return None

def main():
    load_env()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env file")
        sys.exit(1)
    ids = read_ids('deactivated-all.txt')
    print(f"Found {len(ids)} primary IDs to process.")
    output_rows = []
    with open('purge_date_report.csv', 'w', encoding='utf-8', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Primary ID', 'Purge Date', 'Patron Type'])
        found_purge = 0
        missing_purge = 0
        for idx, primary_id in enumerate(ids):
            user = get_user(api_key, base_url, primary_id)
            purge_date = user.get('purge_date') if user else None
            patron_type = user.get('user_group', {}).get('value') if user and 'user_group' in user else None
            writer.writerow([primary_id, purge_date or '', patron_type or ''])
            csvfile.flush()
            if purge_date:
                found_purge += 1
            else:
                missing_purge += 1
            if (idx + 1) % 100 == 0:
                print(f"Processed {idx + 1} users...")
    print("\nSummary:")
    print(f"Total users processed: {len(ids)}")
    print(f"Users with purge date: {found_purge}")
    print(f"Users without purge date: {missing_purge}")
    print("Report saved to purge_date_report.csv")

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
