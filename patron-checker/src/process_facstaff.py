#!/usr/bin/env python3
"""
Process fac-staff.csv to extract patron information from Alma API.
Reads Primary ID, Purge Date, and Patron Type from fac-staff.csv,
fetches additional details from Alma API, and outputs to facstaffreview.csv
"""

import os
import sys
import csv
import requests
from dotenv import load_dotenv

def load_env():
    """Load environment variables from .env file."""
    if os.path.exists('.env'):
        load_dotenv('.env')
    else:
        print("Error: .env file not found")
        sys.exit(1)

def get_user(api_key, base_url, primary_id):
    """Fetch user details from Alma API."""
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
            print(f"Warning: Could not fetch user {primary_id} (status {response.status_code})")
            return None
    except Exception as e:
        print(f"Warning: Error fetching user {primary_id}: {e}")
        return None

def process_facstaff():
    """Process faculty/staff CSV and extract required fields."""
    load_env()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    
    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env file")
        sys.exit(1)
    
    input_file = 'fac-staff.csv'
    output_file = 'facstaffreview.csv'
    
    try:
        with open(input_file, 'r', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            
            # Prepare output data
            output_rows = []
            
            for idx, row in enumerate(reader):
                primary_id = row.get('Primary ID', '')
                
                # Fetch user details from Alma API
                user = get_user(api_key, base_url, primary_id)
                
                if user:
                    first_name = user.get('first_name', '')
                    last_name = user.get('last_name', '')
                    # Get primary email from contact_info
                    email = ''
                    contact_info = user.get('contact_info', {})
                    emails = contact_info.get('email', [])
                    if emails:
                        # Find preferred email or use first one
                        for email_obj in emails:
                            if email_obj.get('preferred', False):
                                email = email_obj.get('email_address', '')
                                break
                        if not email and emails:
                            email = emails[0].get('email_address', '')
                else:
                    first_name = ''
                    last_name = ''
                    email = ''
                
                output_row = {
                    'Primary ID': primary_id,
                    'First Name': first_name,
                    'Last Name': last_name,
                    'Email Address': email,
                    'Patron Type': row.get('Patron Type', ''),
                    'Purge Date': row.get('Purge Date', '')
                }
                output_rows.append(output_row)
                
                # Progress indicator
                if (idx + 1) % 50 == 0:
                    print(f"Processed {idx + 1} users...")
            
            # Write to output file
            with open(output_file, 'w', encoding='utf-8', newline='') as outfile:
                fieldnames = ['Primary ID', 'First Name', 'Last Name', 
                             'Email Address', 'Patron Type', 'Purge Date']
                writer = csv.DictWriter(outfile, fieldnames=fieldnames)
                
                writer.writeheader()
                writer.writerows(output_rows)
            
            print(f"\nSuccessfully processed {len(output_rows)} records.")
            print(f"Output written to {output_file}")
            
    except FileNotFoundError:
        print(f"Error: {input_file} not found.")
    except Exception as e:
        print(f"Error processing file: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    process_facstaff()
