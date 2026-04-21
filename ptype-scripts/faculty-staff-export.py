#!/usr/bin/env python3
"""
Alma FacultyStaff User Group Export Script

Retrieves primary ID, first name, last name, and email address for all users
in the FacultyStaff user group and exports to CSV.
"""

import os
import sys
import requests
import csv
from datetime import datetime
from dotenv import load_dotenv


def load_environment():
    """Prompt user to select environment and load appropriate .env file."""
    print("\nSelect environment:")
    print("1. Production")
    print("2. Sandbox")
    
    while True:
        choice = input("\nEnter choice (1 or 2): ").strip()
        if choice == '1':
            if os.path.exists('.env'):
                load_dotenv('.env')
                print("Loaded Production environment")
                return 'production'
            else:
                print("Error: .env file not found")
                sys.exit(1)
        elif choice == '2':
            if os.path.exists('.env.sandbox'):
                load_dotenv('.env.sandbox')
                print("Loaded Sandbox environment")
                return 'sandbox'
            else:
                print("Error: .env.sandbox file not found")
                sys.exit(1)
        else:
            print("Invalid choice. Please enter 1 or 2.")


def get_faculty_staff_users(api_key, base_url):
    """
    Retrieve all users in the FacultyStaff user group.
    
    Args:
        api_key: Alma API key
        base_url: Alma API base URL
        
    Returns:
        List of user dictionaries with primary_id, first_name, last_name, email
    """
    users = []
    offset = 0
    limit = 100
    
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    
    print("\nFetching users from FacultyStaff group...")
    
    while True:
        # Query for users in FacultyStaff group
        url = f"{base_url}/almaws/v1/users"
        params = {
            'q': 'user_group~FacultyStaff',
            'limit': limit,
            'offset': offset
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            
            # Extract user information
            for user in data.get('user', []):
                contact_info = user.get('contact_info', {})
                emails = contact_info.get('email', [])
                
                # Get preferred email or first email
                email = ''
                if emails:
                    preferred = [e for e in emails if e.get('preferred', False)]
                    email = preferred[0].get('email_address', '') if preferred else emails[0].get('email_address', '')
                
                user_info = {
                    'primary_id': user.get('primary_id', ''),
                    'first_name': user.get('first_name', ''),
                    'last_name': user.get('last_name', ''),
                    'email': email
                }
                users.append(user_info)
            
            total_records = data.get('total_record_count', 0)
            print(f"Retrieved {len(users)} of {total_records} users...")
            
            # Check if there are more results
            if offset + limit >= total_records:
                break
                
            offset += limit
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching users: {e}")
            if hasattr(e.response, 'text'):
                print(f"Response: {e.response.text}")
            sys.exit(1)
    
    return users


def save_to_csv(users, environment):
    """Save users to CSV file."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"faculty_staff_users_{environment}_{timestamp}.csv"
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['primary_id', 'first_name', 'last_name', 'email']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for user in users:
            writer.writerow(user)
    
    print(f"\nExported {len(users)} users to {filename}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("Alma FacultyStaff User Group Export")
    print("=" * 60)
    
    # Load environment
    environment = load_environment()
    
    # Get API credentials
    api_key = os.getenv('ALMA_API_KEY')
    base_url = os.getenv('ALMA_API_BASE_URL')
    
    if not api_key or not base_url:
        print("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env file")
        sys.exit(1)
    
    # Fetch users
    users = get_faculty_staff_users(api_key, base_url)
    
    if not users:
        print("\nNo users found in FacultyStaff group")
        return
    
    # Save to CSV
    save_to_csv(users, environment)
    
    print("\nDone!")


if __name__ == '__main__':
    # Suppress SSL warnings since we're using verify=False
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    main()
