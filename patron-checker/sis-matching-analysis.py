import requests
import os
from dotenv import load_dotenv
import json
from collections import defaultdict, Counter
import concurrent.futures
import time

# Load environment variables
load_dotenv()

API_KEY = os.getenv('ALMA_API_KEY')
BASE_URL = os.getenv('ALMA_BASE_URL', 'https://api-na.hosted.exlibrisgroup.com/almaws/v1')

def get_user_details(user_id):
    """Fetch detailed user information including identifiers"""
    headers = {
        'Authorization': f'apikey {API_KEY}',
        'Accept': 'application/json'
    }
    
    url = f"{BASE_URL}/users/{user_id}"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching user details for {user_id}: {e}")
        return None

def get_all_users(max_users=None):
    """Fetch all users from Alma API with pagination"""
    users = []
    offset = 0
    limit = 100
    
    headers = {
        'Authorization': f'apikey {API_KEY}',
        'Accept': 'application/json'
    }
    
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
                
            users.extend(batch_users)
            print(f"Fetched {len(users)} users so far...")
            
            if max_users and len(users) >= max_users:
                users = users[:max_users]
                print(f"Reached limit of {max_users} users")
                break
            
            if len(batch_users) < limit:
                break
                
            offset += limit
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching users: {e}")
            break
    
    return users

def extract_user_identifiers(user, detailed_user=None):
    """Extract all identifiers for a user"""
    user_data = detailed_user if detailed_user else user
    
    result = {
        'primary_id': user.get('primary_id'),
        'univ_id': None,
        'ldap': None,
        'barcode': None,
        'other_ids': [],
        'has_univ_id': False,
        'identifiers': []
    }
    
    # Get identifiers
    identifiers = user_data.get('user_identifier', [])
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    
    for identifier in identifiers:
        if not isinstance(identifier, dict):
            continue
            
        id_value = identifier.get('value', '')
        id_type_obj = identifier.get('id_type', {})
        
        if isinstance(id_type_obj, dict):
            id_type = id_type_obj.get('value', 'Unknown')
        else:
            id_type = id_type_obj
        
        result['identifiers'].append({
            'value': id_value,
            'type': id_type
        })
        
        # Categorize by type
        if id_type == 'UNIV_ID':
            result['univ_id'] = id_value
            result['has_univ_id'] = True
        elif id_type == 'LDAP':
            result['ldap'] = id_value
        elif id_type in ['BARCODE', 'PRIMARY_ID']:
            result['barcode'] = id_value
        else:
            result['other_ids'].append({'type': id_type, 'value': id_value})
    
    return result

def analyze_sis_matching_safety(users):
    """Analyze the safety of switching from Primary ID to UNIV_ID matching"""
    
    print(f"\nAnalyzing SIS matching safety for {len(users)} users...")
    
    # Data structures for analysis
    primary_to_univ = {}  # primary_id -> univ_id
    univ_to_primary = {}  # univ_id -> primary_id
    univ_id_counts = Counter()  # Count occurrences of each univ_id
    
    # User categories
    users_with_both = 0
    users_with_primary_only = 0
    users_with_univ_only = 0
    users_with_neither = 0
    
    # Potential issues
    duplicate_univ_ids = []
    orphaned_users = []
    sample_mappings = []
    
    for i, user in enumerate(users):
        user_id = user.get('primary_id')
        
        # Extract identifiers
        user_identifiers = extract_user_identifiers(user)
        
        primary_id = user_identifiers['primary_id']
        univ_id = user_identifiers['univ_id']
        
        # Save sample mappings for display
        if len(sample_mappings) < 10:
            sample_mappings.append({
                'primary_id': primary_id,
                'univ_id': univ_id,
                'ldap': user_identifiers['ldap'],
                'other_ids': len(user_identifiers['other_ids'])
            })
        
        # Categorize users
        has_primary = primary_id is not None
        has_univ = univ_id is not None
        
        if has_primary and has_univ:
            users_with_both += 1
            
            # Track mappings
            primary_to_univ[primary_id] = univ_id
            univ_id_counts[univ_id] += 1
            
            # Check for conflicts
            if univ_id in univ_to_primary and univ_to_primary[univ_id] != primary_id:
                duplicate_univ_ids.append({
                    'univ_id': univ_id,
                    'primary_ids': [univ_to_primary[univ_id], primary_id]
                })
            else:
                univ_to_primary[univ_id] = primary_id
                
        elif has_primary and not has_univ:
            users_with_primary_only += 1
            orphaned_users.append({
                'primary_id': primary_id,
                'ldap': user_identifiers['ldap'],
                'other_ids': user_identifiers['other_ids']
            })
        elif not has_primary and has_univ:
            users_with_univ_only += 1
        else:
            users_with_neither += 1
        
        # Progress indicator
        if (i + 1) % 100 == 0:
            print(f"Processed {i + 1}/{len(users)} users...")
    
    # Analysis results
    total_users = len(users)
    migration_safety = {
        'safe_to_migrate': True,
        'risk_level': 'LOW',
        'issues': []
    }
    
    # Check for issues
    if users_with_primary_only > 0:
        migration_safety['safe_to_migrate'] = False
        migration_safety['risk_level'] = 'HIGH'
        migration_safety['issues'].append(f"{users_with_primary_only} users would be orphaned (have Primary ID but no UNIV_ID)")
    
    if duplicate_univ_ids:
        migration_safety['safe_to_migrate'] = False
        migration_safety['risk_level'] = 'HIGH'
        migration_safety['issues'].append(f"{len(duplicate_univ_ids)} UNIV_IDs map to multiple Primary IDs")
    
    if users_with_univ_only > 0:
        migration_safety['issues'].append(f"{users_with_univ_only} users have UNIV_ID but no Primary ID (unusual but not blocking)")
    
    if users_with_both < total_users * 0.95:  # Less than 95% have both
        migration_safety['risk_level'] = 'MEDIUM'
        migration_safety['issues'].append("Less than 95% of users have both identifiers")
    
    return {
        'total_users': total_users,
        'users_with_both': users_with_both,
        'users_with_primary_only': users_with_primary_only,
        'users_with_univ_only': users_with_univ_only,
        'users_with_neither': users_with_neither,
        'duplicate_univ_ids': duplicate_univ_ids,
        'orphaned_users': orphaned_users,  # All orphaned users
        'sample_mappings': sample_mappings,
        'migration_safety': migration_safety,
        'primary_to_univ': dict(list(primary_to_univ.items())[:10]),  # Sample mappings
        'univ_id_counts': dict(univ_id_counts.most_common(10))
    }

def print_analysis_report(analysis):
    """Print detailed analysis report"""
    
    print("\n" + "="*70)
    print("SIS IMPORT MATCHING ANALYSIS REPORT")
    print("="*70)
    
    total = analysis['total_users']
    
    print(f"\nUSER IDENTIFIER DISTRIBUTION:")
    print(f"{'Category':<30} {'Count':<10} {'Percentage'}")
    print("-" * 50)
    print(f"{'Users with both Primary & UNIV ID':<30} {analysis['users_with_both']:<10} {analysis['users_with_both']/total*100:.1f}%")
    print(f"{'Users with Primary ID only':<30} {analysis['users_with_primary_only']:<10} {analysis['users_with_primary_only']/total*100:.1f}%")
    print(f"{'Users with UNIV ID only':<30} {analysis['users_with_univ_only']:<10} {analysis['users_with_univ_only']/total*100:.1f}%")
    print(f"{'Users with neither':<30} {analysis['users_with_neither']:<10} {analysis['users_with_neither']/total*100:.1f}%")
    
    print(f"\nMIGRATION SAFETY ASSESSMENT:")
    print("-" * 50)
    safety = analysis['migration_safety']
    print(f"Safe to migrate: {safety['safe_to_migrate']}")
    print(f"Risk level: {safety['risk_level']}")
    
    if safety['issues']:
        print(f"\nISSUES IDENTIFIED:")
        for issue in safety['issues']:
            print(f"⚠️  {issue}")
    
    if analysis['duplicate_univ_ids']:
        print(f"\nDUPLICATE UNIV_ID CONFLICTS:")
        for dup in analysis['duplicate_univ_ids'][:5]:  # Show first 5
            print(f"   UNIV_ID '{dup['univ_id']}' -> Primary IDs: {dup['primary_ids']}")
    
    if analysis['orphaned_users']:
        print(f"\nORPHANED USERS (Primary ID but no UNIV_ID): {len(analysis['orphaned_users'])} total")
        print("First 10 examples:")
        for user in analysis['orphaned_users'][:10]:
            ldap_display = user['ldap'] or 'None'
            other_count = len(user['other_ids'])
            print(f"   {user['primary_id']} (LDAP: {ldap_display}, Other IDs: {other_count})")
    
    print(f"\nSAMPLE ID MAPPINGS:")
    print(f"{'Primary ID':<15} {'UNIV ID':<15} {'LDAP':<20} {'Other IDs'}")
    print("-" * 65)
    for mapping in analysis['sample_mappings']:
        univ_display = mapping['univ_id'] or 'None'
        ldap_display = mapping['ldap'] or 'None'
        print(f"{mapping['primary_id']:<15} {univ_display:<15} {ldap_display:<20} {mapping['other_ids']}")
    
    print(f"\nRECOMMENDATION:")
    print("-" * 50)
    if safety['safe_to_migrate']:
        print("✅ SAFE to switch SIS import matching from Primary ID to UNIV_ID")
        print("   • All users have consistent identifier mapping")
        print("   • No risk of creating duplicate users")
        print("   • This will solve your barcode mismatch issues")
    else:
        print("❌ NOT SAFE to switch without addressing issues first")
        print("   • Fix the issues identified above before migrating")
        print("   • Consider data cleanup or alternative approaches")

def save_detailed_report(analysis):
    """Save detailed analysis to JSON file"""
    
    with open('sis_matching_analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)
    
    print(f"\nDetailed analysis saved to: sis_matching_analysis.json")

def main():
    """Main function"""
    
    if not API_KEY:
        print("Error: ALMA_API_KEY not found in environment variables")
        return
    
    print("Starting SIS Import Matching Analysis...")
    print("This will analyze the safety of switching from Primary ID to UNIV_ID matching")
    
    # Fetch all users for complete analysis
    users = get_all_users()  # No limit - get all users
    
    if not users:
        print("No users found or error fetching users")
        return
    
    # Analyze matching safety
    analysis = analyze_sis_matching_safety(users)
    
    # Print report
    print_analysis_report(analysis)
    
    # Save detailed report
    save_detailed_report(analysis)

if __name__ == "__main__":
    main()