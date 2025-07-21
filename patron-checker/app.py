from flask import Flask, render_template, request, jsonify
import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Get API credentials from environment variables
ALMA_API_KEY = os.getenv('ALMA_API_KEY')
ALMA_API_BASE_URL = os.getenv('ALMA_API_BASE_URL')

def call_alma_api(endpoint, params=None, suppress_errors=False):
    """
    Makes a GET request to the Alma API.
    """
    url = f"{ALMA_API_BASE_URL}/almaws/v1{endpoint}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"apikey {ALMA_API_KEY}"
    }
    if params is None:
        params = {}
    params['apikey'] = ALMA_API_KEY

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        if not suppress_errors:
            print(f"HTTP error occurred: {http_err} - {response.text}")
    except Exception as e:
        if not suppress_errors:
            print(f"An error occurred: {e}")
    return None

def get_user_by_barcode(barcode):
    """Retrieves user information using a barcode."""
    user_data = call_alma_api(f"/users/{barcode}")
    if not user_data:
        user_data = call_alma_api(f"/users/{barcode}", params={"user_id_type": "BARCODE"})
    return user_data

def search_users_by_name(first_name, last_name):
    """Searches for users by first and last name."""
    search_params = {
        'q': f'last_name~{last_name} AND first_name~{first_name}',
        'limit': 10
    }
    users_data = call_alma_api("/users", params=search_params)
    
    if not users_data or 'user' not in users_data:
        return None
    
    users = users_data['user']
    if len(users) == 0:
        return None
    elif len(users) == 1:
        # Get full user details
        user_id = users[0].get('primary_id')
        if user_id:
            return call_alma_api(f"/users/{user_id}")
        return users[0]
    else:
        # Return list for user to choose from
        return users

def search_users_by_email(email):
    """Searches for users by email address."""
    search_params = {
        'q': f'email~{email}',
        'limit': 10
    }
    users_data = call_alma_api("/users", params=search_params)
    
    if not users_data or 'user' not in users_data:
        return None
    
    users = users_data['user']
    if len(users) == 0:
        return None
    elif len(users) == 1:
        # Get full user details
        user_id = users[0].get('primary_id')
        if user_id:
            return call_alma_api(f"/users/{user_id}")
        return users[0]
    else:
        # Return list for user to choose from
        return users

def get_user_details(user_data):
    """Processes user data and returns formatted information."""
    if not user_data:
        return None
    
    user_id = user_data.get('primary_id')
    if not user_id:
        return None

    # Basic user info
    first_name = user_data.get('first_name', 'N/A')
    last_name = user_data.get('last_name', 'N/A')
    full_name = f"{first_name} {last_name}"
    email = user_data.get('contact_info', {}).get('email', [{}])[0].get('email_address', 'N/A')
    patron_group = user_data.get('user_group', {}).get('desc', 'N/A')

    # Get loans
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
                    due_date = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                    now = datetime.now(due_date.tzinfo)
                    if now > due_date:
                        overdue_loans_count += 1
                        days_overdue = (now - due_date).days
                        overdue_details.append({
                            'title': loan.get('title', 'N/A'),
                            'due_date': due_date.strftime('%Y-%m-%d'),
                            'days_overdue': days_overdue
                        })
                except ValueError:
                    pass

    # Get fines
    fees_data = call_alma_api(f"/users/{user_id}/fees")
    total_fines_amount = 0.0

    if fees_data and 'fee' in fees_data:
        for fee in fees_data['fee']:
            if fee.get('status', {}).get('value') == 'ACTIVE':
                total_fines_amount += float(fee.get('amount', 0.0))

    # Get blocks
    active_blocks = []
    block_keys_to_check = ['user_block', 'user_blocks', 'blocks', 'userBlocks', 'patron_blocks']
    for key in block_keys_to_check:
        if key in user_data and user_data[key]:
            user_blocks_data = user_data[key]
            
            if isinstance(user_blocks_data, list):
                for block in user_blocks_data:
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
                            'created_by': block.get('created_by', 'N/A')
                        }
                        active_blocks.append(block_info)
                        break

    return {
        'user_id': user_id,
        'full_name': full_name,
        'email': email,
        'patron_group': patron_group,
        'current_loans': current_loans_count,
        'overdue_loans': overdue_loans_count,
        'overdue_details': overdue_details,
        'total_fines': total_fines_amount,
        'active_blocks': active_blocks
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    search_type = request.json.get('search_type')
    
    if search_type == 'barcode':
        barcode = request.json.get('barcode')
        if not barcode:
            return jsonify({'error': 'Barcode is required'}), 400
        
        user_data = get_user_by_barcode(barcode)
        if not user_data:
            return jsonify({'error': 'User not found'}), 404
            
        result = get_user_details(user_data)
        return jsonify(result)
    
    elif search_type == 'name':
        first_name = request.json.get('first_name')
        last_name = request.json.get('last_name')
        if not first_name or not last_name:
            return jsonify({'error': 'First and last names are required'}), 400
        
        users = search_users_by_name(first_name, last_name)
        if not users:
            return jsonify({'error': 'User not found'}), 404
        
        # If it's a list, return the list for selection
        if isinstance(users, list):
            user_list = []
            for user in users:
                user_list.append({
                    'primary_id': user.get('primary_id'),
                    'name': f"{user.get('first_name', '')} {user.get('last_name', '')}"
                })
            return jsonify({'multiple_users': user_list})
        
        # Single user found
        result = get_user_details(users)
        return jsonify(result)
    
    elif search_type == 'email':
        email = request.json.get('email')
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        users = search_users_by_email(email)
        if not users:
            return jsonify({'error': 'User not found'}), 404
        
        # If it's a list, return the list for selection
        if isinstance(users, list):
            user_list = []
            for user in users:
                user_list.append({
                    'primary_id': user.get('primary_id'),
                    'name': f"{user.get('first_name', '')} {user.get('last_name', '')}"
                })
            return jsonify({'multiple_users': user_list})
        
        # Single user found
        result = get_user_details(users)
        return jsonify(result)
    
    return jsonify({'error': 'Invalid search type'}), 400

@app.route('/get_user/<user_id>')
def get_user(user_id):
    """Get specific user by ID (used when multiple users are found)"""
    user_data = call_alma_api(f"/users/{user_id}")
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    result = get_user_details(user_data)
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
