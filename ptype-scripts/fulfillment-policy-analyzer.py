import os
import requests
from collections import defaultdict
from dotenv import load_dotenv

# Load API key and base URL from .env
load_dotenv()
API_KEY = os.getenv('ALMA_API_KEY')
BASE_URL = os.getenv('ALMA_API_BASE_URL')

HEADERS = {'Authorization': f'apikey {API_KEY}'}

# Get all user groups (patron types) from types.csv
import csv
def get_user_groups():
    user_groups = []
    with open('types.csv', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Use the 'Code' as the user group code
            user_groups.append({'code': row['Code'], 'description': row['Description']})
    return user_groups

# Get all fulfillment rules
def get_fulfillment_rules():
    url = f"{BASE_URL}/almaws/v1/conf/fulfillment-rules"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json().get('fulfillment_rule', [])

# Get all fulfillment policies
def get_fulfillment_policies():
    url = f"{BASE_URL}/almaws/v1/conf/fulfillment-policies"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json().get('policy', [])

# Main logic: compare policies for all user groups

def main():
    groups = get_user_groups()
    rules = get_fulfillment_rules()
    policies = get_fulfillment_policies()
    # Map policy id to policy details
    policy_map = {p['id']: p for p in policies}
    # Map user group to set of policy ids (across all rules)
    group_policy_sets = defaultdict(set)
    for rule in rules:
        user_group = rule.get('user_group', {}).get('value')
        policy_id = rule.get('policy', {}).get('value')
        if user_group and policy_id:
            group_policy_sets[user_group].add(policy_id)
    # Compare sets
    reverse = defaultdict(list)
    for group in groups:
        code = group['code']
        policy_set = group_policy_sets.get(code, set())
        reverse[frozenset(policy_set)].append(code)
    print("Patron types with identical fulfillment policy sets:")
    for policy_set, codes in reverse.items():
        if len(codes) > 1:
            print(f"  {', '.join(codes)}")
    print("\nSuggestion: The above patron types could potentially be combined without affecting borrowing policies.")

if __name__ == "__main__":
    main()
