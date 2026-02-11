import requests
import os
from dotenv import load_dotenv

def select_environment():
    """Prompt user to select environment"""
    print("\nSelect environment:")
    print("1. Sandbox")
    print("2. Production")
    
    while True:
        choice = input("\nEnter your choice (1 or 2): ").strip()
        if choice == '1':
            load_dotenv('.env.sandbox')
            print("✓ Using SANDBOX environment")
            return 'sandbox'
        elif choice == '2':
            load_dotenv('.env')
            print("✓ Using PRODUCTION environment")
            return 'prod'
        else:
            print("Invalid choice. Please enter 1 or 2.")

def get_users(api_key, base_url, limit=5):
    """Retrieve users from Alma"""
    url = f"{base_url}/almaws/v1/users"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    params = {
        'limit': limit,
        'offset': 0
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"ERROR: API returned status {response.status_code}")
        print(f"Response: {response.text}")
        response.raise_for_status()
    return [user['primary_id'] for user in response.json().get('user', [])]

def get_user(user_id, api_key, base_url):
    """Retrieve user details from Alma"""
    url = f"{base_url}/almaws/v1/users/{user_id}"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Accept': 'application/json'
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def update_user_identifier(user_data, uri_email, api_key, base_url):
    """Add email using INST_ID identifier type"""
    # Check if user_identifiers exists
    if 'user_identifier' not in user_data:
        user_data['user_identifier'] = []
    
    # Check if this email already exists as an INST_ID
    identifier_exists = False
    for identifier in user_data['user_identifier']:
        if identifier.get('id_type', {}).get('value') == 'INST_ID' and identifier.get('value') == uri_email:
            identifier_exists = True
            break
    
    if not identifier_exists:
        user_data['user_identifier'].append({
            'value': uri_email,
            'status': 'ACTIVE',
            'id_type': {'value': 'INST_ID', 'desc': 'Institution ID'},
            'segment_type': 'Internal'
        })
    
    # Remove problematic fields that can cause API errors
    for field in ['link', 'proxy_for_user', 'rs_libraries', 'user_role']:
        user_data.pop(field, None)
    
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
    
    # Update user in Alma
    user_id = user_data['primary_id']
    url = f"{base_url}/almaws/v1/users/{user_id}"
    headers = {
        'Authorization': f'apikey {api_key}',
        'Content-Type': 'application/json'
    }
    response = requests.put(url, headers=headers, json=user_data)
    response.raise_for_status()
    
    # Handle empty or non-JSON responses
    if response.status_code == 204 or not response.text:
        # 204 No Content or empty response means success
        return user_data
    
    try:
        return response.json()
    except:
        # If we can't parse JSON but got a 200, return the original data
        return user_data

def main():
    # Select environment
    env = select_environment()
    
    # Load environment variables
    API_KEY = os.getenv('ALMA_API_KEY')
    API_BASE_URL = os.getenv('ALMA_API_BASE_URL')
    
    if not API_KEY or not API_BASE_URL:
        print("ERROR: Missing API_KEY or API_BASE_URL in environment file")
        return
    
    # Fetch users from Alma (limit to 5)
    MAX_USERS = 5
    print(f"\nFetching {MAX_USERS} users from Alma...")
    user_ids = get_users(API_KEY, API_BASE_URL, MAX_USERS)
    
    print(f"Processing {len(user_ids)} users...")
    
    for i, user_id in enumerate(user_ids, 1):
        try:
            # Get user and extract @uri.edu email
            user_data = get_user(user_id, API_KEY, API_BASE_URL)
            
            # Find @uri.edu email
            uri_email = None
            emails = user_data.get('contact_info', {}).get('email', [])
            
            # Debug: show all emails
            all_email_addresses = [email.get('email_address', '') for email in emails]
            print(f"  [{i}/{len(user_ids)}] {user_id} - All emails: {all_email_addresses}")
            
            for email in emails:
                email_address = email.get('email_address', '')
                if email_address.endswith('@uri.edu'):
                    uri_email = email_address
                    print(f"      -> Found @uri.edu: {uri_email}")
                    break
            
            if uri_email:
                updated_user = update_user_identifier(user_data, uri_email, API_KEY, API_BASE_URL)
                print(f"      ✓ Updated {updated_user.get('primary_id', user_id)}: Added INST_ID = {uri_email}")
            else:
                print(f"      ⚠ No @uri.edu email found")
                
        except requests.exceptions.HTTPError as e:
            print(f"  [{i}/{len(user_ids)}] ✗ Error processing {user_id}: {e.response.status_code}")
            if e.response.text:
                # Try to extract error message from XML
                import re
                error_match = re.search(r'<errorMessage>(.*?)</errorMessage>', e.response.text)
                if error_match:
                    print(f"      Error: {error_match.group(1)}")
                else:
                    print(f"      API Response: {e.response.text[:300]}")
        except Exception as e:
            print(f"  [{i}/{len(user_ids)}] ✗ Error processing {user_id}: {str(e)}")
    
    print("\nDone!")

if __name__ == "__main__":
    main()