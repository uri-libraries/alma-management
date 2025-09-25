import requests
import os
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

API_KEY = os.getenv('ALMA_API_KEY')
BASE_URL = os.getenv('ALMA_BASE_URL', 'https://api-na.hosted.exlibrisgroup.com/almaws/v1')

def count_orphaned_users():
    """Quick count of users with Primary ID but no UNIV_ID"""
    
    headers = {
        'Authorization': f'apikey {API_KEY}',
        'Accept': 'application/json'
    }
    
    total_users = 0
    orphaned_count = 0
    orphaned_users = []
    offset = 0
    limit = 100
    
    print("Counting orphaned users (Primary ID but no UNIV_ID)...")
    
    while True:
        url = f"{BASE_URL}/users"
        params = {
            'limit': limit,
            'offset': offset,
            'format': 'json',
            'expand': 'full'
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if 'user' not in data:
                break
                
            batch_users = data['user']
            if not batch_users:
                break
            
            # Process this batch
            for user in batch_users:
                total_users += 1
                primary_id = user.get('primary_id')
                
                # Check if user has UNIV_ID
                has_univ_id = False
                identifiers = user.get('user_identifier', [])
                
                if isinstance(identifiers, dict):
                    identifiers = [identifiers]
                
                for identifier in identifiers:
                    if isinstance(identifier, dict):
                        id_type = identifier.get('id_type', {})
                        if isinstance(id_type, dict):
                            type_value = id_type.get('value', '')
                        else:
                            type_value = id_type
                        
                        if type_value == 'UNIV_ID':
                            has_univ_id = True
                            break
                
                # If has primary but no univ_id, it's orphaned
                if primary_id and not has_univ_id:
                    orphaned_count += 1
                    orphaned_users.append(primary_id)
            
            print(f"Processed {total_users} users, found {orphaned_count} orphaned so far...")
            
            if len(batch_users) < limit:
                break
                
            offset += limit
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching users: {e}")
            break
    
    print(f"\n{'='*50}")
    print(f"ORPHANED USERS SUMMARY")
    print(f"{'='*50}")
    print(f"Total users analyzed: {total_users}")
    print(f"Orphaned users (Primary ID but no UNIV_ID): {orphaned_count}")
    print(f"Percentage orphaned: {orphaned_count/total_users*100:.2f}%")
    
    # Save list of orphaned users
    with open('orphaned_users_list.json', 'w') as f:
        json.dump({
            'total_users': total_users,
            'orphaned_count': orphaned_count,
            'orphaned_users': orphaned_users
        }, f, indent=2)
    
    print(f"\nComplete list saved to: orphaned_users_list.json")
    
    if orphaned_count > 0:
        print(f"\nFirst 10 orphaned user IDs:")
        for user_id in orphaned_users[:10]:
            print(f"  {user_id}")
    
    return orphaned_count, total_users

if __name__ == "__main__":
    if not API_KEY:
        print("Error: ALMA_API_KEY not found in environment variables")
    else:
        count_orphaned_users()