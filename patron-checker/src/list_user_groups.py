#!/usr/bin/env python3
"""
List all user groups in Alma.
"""
import os
import sys
import requests
from dotenv import load_dotenv

def load_env():
    if os.path.exists('.env'):
        load_dotenv('.env')
    elif os.path.exists('../.env'):
        load_dotenv('../.env')
    else:
        print("Error: .env file not found")
        sys.exit(1)

def main():
    load_env()
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    
    url = f"{base_url}/almaws/v1/conf/user-groups"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    
    response = requests.get(url, headers=headers, verify=False)
    if response.status_code == 200:
        data = response.json()
        groups = data.get('user_group', [])
        print(f"Found {len(groups)} user groups:\n")
        print(f"{'Code':<30} {'Description'}")
        print("=" * 80)
        for group in groups:
            code = group.get('code', '')
            desc = group.get('desc', '')
            print(f"{code:<30} {desc}")
    else:
        print(f"Error: {response.status_code} - {response.text}")

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
