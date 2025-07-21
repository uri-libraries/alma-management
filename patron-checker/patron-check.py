import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv

# --- Configuration ---
# Load environment variables from .env file
load_dotenv()

# Get API credentials from environment variables
ALMA_API_KEY = os.getenv('ALMA_API_KEY')
ALMA_API_BASE_URL = os.getenv('ALMA_API_BASE_URL')

# --- Helper Function to Make API Calls ---
def call_alma_api(endpoint, params=None, suppress_errors=False):
    """
    Makes a GET request to the Alma API.

    Args:
        endpoint (str): The API endpoint (e.g., "/users/12345").
        params (dict, optional): Dictionary of query parameters. Defaults to None.
        suppress_errors (bool, optional): If True, suppresses error messages. Defaults to False.

    Returns:
        dict: The JSON response from the API, or None if an error occurs.
    """
    url = f"{ALMA_API_BASE_URL}/almaws/v1{endpoint}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"apikey {ALMA_API_KEY}"
    }
    if params is None:
        params = {}
    params['apikey'] = ALMA_API_KEY # Ensure API key is always in params for some endpoints

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        if not suppress_errors:
            print(f"HTTP error occurred: {http_err} - {response.text}")
    except requests.exceptions.ConnectionError as conn_err:
        if not suppress_errors:
            print(f"Connection error occurred: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        if not suppress_errors:
            print(f"Timeout error occurred: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        if not suppress_errors:
            print(f"An unexpected error occurred: {req_err}")
    except json.JSONDecodeError:
        if not suppress_errors:
            print(f"Error decoding JSON response from {url}: {response.text}")
    return None

# --- Main Function to Get User Information ---
def get_user_by_barcode(barcode):
    """
    Retrieves user information using a barcode.

    Args:
        barcode (str): The barcode of the Alma user.
    """
    print(f"\n--- Searching for user with barcode: {barcode} ---")
    
    # Try different approaches to find user by barcode
    user_data = call_alma_api(f"/users/{barcode}")
    
    if not user_data:
        # Try with explicit barcode parameter
        user_data = call_alma_api(f"/users/{barcode}", params={"user_id_type": "BARCODE"})
    
    return user_data

def search_users_by_name(first_name, last_name):
    """
    Searches for users by first and last name.

    Args:
        first_name (str): The first name to search for.
        last_name (str): The last name to search for.
    """
    print(f"\n--- Searching for users with name: {first_name} {last_name} ---")
    
    # Search users endpoint with name parameters
    search_params = {
        'q': f'last_name~{last_name} AND first_name~{first_name}',
        'limit': 10
    }
    
    users_data = call_alma_api("/users", params=search_params)
    
    if not users_data or 'user' not in users_data:
        print(f"No users found with name: {first_name} {last_name}")
        return None
    
    users = users_data['user']
    if len(users) == 0:
        print(f"No users found with name: {first_name} {last_name}")
        return None
    elif len(users) == 1:
        print(f"Found 1 user matching the name.")
        selected_user = users[0]
    else:
        print(f"Found {len(users)} users matching the name:")
        for i, user in enumerate(users, 1):
            name = f"{user.get('first_name', 'N/A')} {user.get('last_name', 'N/A')}"
            user_id = user.get('primary_id', 'N/A')
            print(f"  {i}. {name} (ID: {user_id})")
        
        while True:
            try:
                choice = input(f"\nSelect user (1-{len(users)}) or 'cancel' to go back: ").strip()
                if choice.lower() == 'cancel':
                    return None
                choice_num = int(choice)
                if 1 <= choice_num <= len(users):
                    selected_user = users[choice_num - 1]
                    break
                else:
                    print(f"Please enter a number between 1 and {len(users)}")
            except ValueError:
                print("Please enter a valid number or 'cancel'")
    
    # Now get the full user details using the primary_id
    user_id = selected_user.get('primary_id')
    if user_id:
        print(f"Getting full details for user: {user_id}")
        full_user_data = call_alma_api(f"/users/{user_id}")
        return full_user_data
    else:
        print("Could not get primary_id for selected user")
        return selected_user

def search_users_by_email(email):
    """
    Searches for users by email address.

    Args:
        email (str): The email address to search for.
    """
    print(f"\n--- Searching for users with email: {email} ---")
    
    # Search users endpoint with email parameter
    search_params = {
        'q': f'email~{email}',
        'limit': 10
    }
    
    users_data = call_alma_api("/users", params=search_params)
    
    if not users_data or 'user' not in users_data:
        print(f"No users found with email: {email}")
        return None
    
    users = users_data['user']
    if len(users) == 0:
        print(f"No users found with email: {email}")
        return None
    elif len(users) == 1:
        print(f"Found 1 user matching the email.")
        selected_user = users[0]
    else:
        print(f"Found {len(users)} users matching the email:")
        for i, user in enumerate(users, 1):
            name = f"{user.get('first_name', 'N/A')} {user.get('last_name', 'N/A')}"
            user_id = user.get('primary_id', 'N/A')
            print(f"  {i}. {name} (ID: {user_id})")
        
        while True:
            try:
                choice = input(f"\nSelect user (1-{len(users)}) or 'cancel' to go back: ").strip()
                if choice.lower() == 'cancel':
                    return None
                choice_num = int(choice)
                if 1 <= choice_num <= len(users):
                    selected_user = users[choice_num - 1]
                    break
                else:
                    print(f"Please enter a number between 1 and {len(users)}")
            except ValueError:
                print("Please enter a valid number or 'cancel'")
    
    # Now get the full user details using the primary_id
    user_id = selected_user.get('primary_id')
    if user_id:
        print(f"Getting full details for user: {user_id}")
        full_user_data = call_alma_api(f"/users/{user_id}")
        return full_user_data
    else:
        print("Could not get primary_id for selected user")
        return selected_user

def display_user_info(user_data):
    """
    Displays detailed information for a user.

    Args:
        user_data (dict): The user data from Alma API.
    """
    if not user_data:
        return

    user_id = user_data.get('primary_id')
    if not user_id:
        print("Could not retrieve primary ID for the user.")
        return

    # Extract basic user info
    first_name = user_data.get('first_name', 'N/A')
    last_name = user_data.get('last_name', 'N/A')
    full_name = f"{first_name} {last_name}"
    email = user_data.get('contact_info', {}).get('email', [{}])[0].get('email_address', 'N/A')
    patron_group = user_data.get('user_group', {}).get('desc', 'N/A')

    print(f"\nUser Found: {full_name} (ID: {user_id})")
    print(f"  Email: {email}")
    print(f"  Patron Group: {patron_group}")

    # 2. Get User Loans
    loans_data = call_alma_api(f"/users/{user_id}/loans")
    current_loans_count = 0
    overdue_loans_count = 0
    overdue_details = []

    if loans_data and 'item_loan' in loans_data:
        for loan in loans_data['item_loan']:
            current_loans_count += 1
            due_date_str = loan.get('due_date')
            if due_date_str:
                try:
                    # Alma dates are often in ISO format, e.g., "2025-07-20T23:59:00Z"
                    due_date = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                    now = datetime.now(due_date.tzinfo) # Use timezone-aware now
                    if now > due_date:
                        overdue_loans_count += 1
                        days_overdue = (now - due_date).days
                        overdue_details.append({
                            'title': loan.get('title', 'N/A'),
                            'due_date': due_date.strftime('%Y-%m-%d %H:%M'),
                            'days_overdue': days_overdue
                        })
                except ValueError:
                    print(f"Warning: Could not parse due date for loan: {due_date_str}")
            else:
                print(f"Warning: Loan without a due date found: {loan.get('title', 'N/A')}")

    print(f"\nLoan Information:")
    print(f"  Number of current loans: {current_loans_count}")
    print(f"  Number of overdue loans: {overdue_loans_count}")

    if overdue_loans_count > 0:
        print("  Overdue Loan Details:")
        for detail in overdue_details:
            print(f"    - Title: {detail['title']}, Due: {detail['due_date']}, Overdue by: {detail['days_overdue']} days")

    # 3. Get User Fines
    fees_data = call_alma_api(f"/users/{user_id}/fees")
    total_fines_amount = 0.0

    if fees_data and 'fee' in fees_data:
        for fee in fees_data['fee']:
            if fee.get('status', {}).get('value') == 'ACTIVE': # Only sum active fines
                total_fines_amount += float(fee.get('amount', 0.0))

    print(f"\nFine Information:")
    print(f"  Total amount of active fines: ${total_fines_amount:.2f}")

    # 4. Get User Blocks
    print(f"\nBlock Information:")
    active_blocks = []
    
    # Check various possible keys for blocks in the main user data
    block_keys_to_check = ['user_block', 'user_blocks', 'blocks', 'userBlocks', 'patron_blocks']
    for key in block_keys_to_check:
        if key in user_data and user_data[key]:
            user_blocks_data = user_data[key]
            
            # Handle if it's a list directly (which is what we're seeing)
            if isinstance(user_blocks_data, list):
                for block in user_blocks_data:
                    # Check different possible status field names and values
                    status_active = False
                    if 'block_status' in block and block['block_status'] == 'ACTIVE':
                        status_active = True
                    elif 'status' in block and block.get('status', {}).get('value') == 'ACTIVE':
                        status_active = True
                    elif 'status' in block and block['status'] == 'ACTIVE':
                        status_active = True
                    
                    if status_active:
                        block_info = {
                            'type': block.get('block_type', {}).get('desc', 'N/A'),
                            'description': block.get('block_description', {}).get('desc', 'N/A'),
                            'created_date': block.get('created_date', 'N/A'),
                            'created_by': block.get('created_by', 'N/A'),
                            'note': block.get('note', '')
                        }
                        active_blocks.append(block_info)
                        break  # Found blocks in main data, no need to check API endpoints
            
            # Handle if it's nested in a dict structure
            elif isinstance(user_blocks_data, dict) and 'user_block' in user_blocks_data:
                for block in user_blocks_data['user_block']:
                    status_active = False
                    if 'block_status' in block and block['block_status'] == 'ACTIVE':
                        status_active = True
                    elif 'status' in block and block.get('status', {}).get('value') == 'ACTIVE':
                        status_active = True
                    elif 'status' in block and block['status'] == 'ACTIVE':
                        status_active = True
                    
                    if status_active:
                        block_info = {
                            'type': block.get('block_type', {}).get('desc', 'N/A'),
                            'description': block.get('block_description', {}).get('desc', 'N/A'),
                            'created_date': block.get('created_date', 'N/A'),
                            'created_by': block.get('created_by', 'N/A'),
                            'note': block.get('note', '')
                        }
                        active_blocks.append(block_info)
                        break  # Found blocks in main data, no need to check API endpoints

    # Display results
    if active_blocks:
        print(f"  Number of active blocks: {len(active_blocks)}")
        print("  Active Block Details:")
        for i, block in enumerate(active_blocks, 1):
            print(f"    {i}. Type: {block['type']}")
            print(f"       Description: {block['description']}")
            print(f"       Created: {block['created_date']}")
            if block['created_by']:
                print(f"       Created by: {block['created_by']}")
            if block['note']:
                print(f"       Note: {block['note']}")
            if i < len(active_blocks):  # Add separator between blocks
                print()
    else:
        print("  The patron has no blocks.")

# --- Main Execution Block ---
if __name__ == "__main__":
    print("Welcome to the Alma User Information Script!")
    print("Please ensure your ALMA_API_KEY and ALMA_API_BASE_URL environment variables are set.")

    if not ALMA_API_KEY or not ALMA_API_BASE_URL:
        print("\nERROR: Please set the following environment variables:")
        print("  ALMA_API_KEY - Your Alma API key")
        print("  ALMA_API_BASE_URL - Your Alma API base URL (e.g., https://api-na.exlibrisgroup.com)")
        print("\nYou can set them by running:")
        print("  export ALMA_API_KEY='your_api_key_here'")
        print("  export ALMA_API_BASE_URL='your_base_url_here'")
        exit(1)
    else:
        while True:
            print("\n" + "="*50)
            print("How would you like to search for the user?")
            print("1. Barcode")
            print("2. Name (First and Last)")
            print("3. Email Address")
            print("4. Quit")
            
            choice = input("\nEnter your choice (1-4): ").strip()
            
            if choice == '1':
                barcode = input("Enter the barcode: ").strip()
                if barcode:
                    user_data = get_user_by_barcode(barcode)
                    if user_data:
                        display_user_info(user_data)
                    else:
                        print(f"Could not find user with barcode: {barcode}")
                else:
                    print("Barcode cannot be empty.")
                    
            elif choice == '2':
                first_name = input("Enter the first name: ").strip()
                if first_name:
                    last_name = input("Enter the last name: ").strip()
                    if last_name:
                        user_data = search_users_by_name(first_name, last_name)
                        if user_data:
                            display_user_info(user_data)
                    else:
                        print("Last name cannot be empty.")
                else:
                    print("First name cannot be empty.")
                    
            elif choice == '3':
                email = input("Enter the email address: ").strip()
                if email:
                    user_data = search_users_by_email(email)
                    if user_data:
                        display_user_info(user_data)
                else:
                    print("Email address cannot be empty.")
                    
            elif choice == '4' or choice.lower() == 'quit':
                break
                
            else:
                print("Invalid choice. Please enter 1, 2, 3, or 4.")

    print("\nGoodbye!")
