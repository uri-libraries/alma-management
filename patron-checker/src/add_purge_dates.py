#!/usr/bin/env python3
"""
Add purge dates to users in blank-purge-date.csv via Alma API.
Sets purge date to input date for all Primary IDs in the spreadsheet. CSV may have other columns, but must have a "Primary ID" column. Make sure to set ALMA_API_KEY and ALMA_API_BASE_URL in a .env file before running.
"""

import os
import sys
import csv
from datetime import datetime
import requests
from dotenv import load_dotenv

def load_env():
    """Load environment variables from .env file."""
    if os.path.exists('.env'):
        load_dotenv('.env')
    else:
        print("Error: .env file not found")
        sys.exit(1)

def update_user_purge_date(api_key, base_url, primary_id, purge_date):
    """Update user's purge date via Alma API."""
    url = f"{base_url}/almaws/v1/users/{primary_id}"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    # First, get the current user data
    try:
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code != 200:
            print(f"Error: Could not fetch user {primary_id} (status {response.status_code})")
            return False
        
        user_data = response.json()
        
        # Update the purge_date field
        user_data['purge_date'] = purge_date
        
        # Send the updated data back
        response = requests.put(url, headers=headers, json=user_data, verify=False)
        if response.status_code == 200:
            return True
        else:
            print(f"Error: Could not update user {primary_id} (status {response.status_code})")
            if response.text:
                print(f"  Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"Error updating user {primary_id}: {e}")
        return False

def prompt_for_purge_date():
    """Prompt for a purge date in YYYY-MM-DD format and return Alma's expected value."""
    while True:
        raw_date = input("Enter the purge date to set (YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(raw_date, '%Y-%m-%d')
            return f"{raw_date}Z"
        except ValueError:
            print("Error: Please enter a valid date in YYYY-MM-DD format.")

def main():
    """Process blank-purge-date.csv and add purge dates via API."""
    load_env()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    
    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env file")
        sys.exit(1)
    
    input_file = 'blank-purge-date.csv'
    purge_date = prompt_for_purge_date()
    
    try:
        with open(input_file, 'r', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            
            primary_ids = [row['Primary ID'] for row in reader if row.get('Primary ID')]
            
        print(f"Found {len(primary_ids)} users to update.")
        print(f"Setting purge date to: {purge_date}\n")
        
        success_count = 0
        failure_count = 0
        
        for idx, primary_id in enumerate(primary_ids):
            if update_user_purge_date(api_key, base_url, primary_id, purge_date):
                success_count += 1
            else:
                failure_count += 1
            
            # Progress indicator
            if (idx + 1) % 50 == 0:
                print(f"Processed {idx + 1}/{len(primary_ids)} users...")
        
        print(f"\nUpdate complete!")
        print(f"Successfully updated: {success_count}")
        print(f"Failed to update: {failure_count}")
        print(f"Total processed: {len(primary_ids)}")
        
    except FileNotFoundError:
        print(f"Error: {input_file} not found.")
    except Exception as e:
        print(f"Error processing file: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
