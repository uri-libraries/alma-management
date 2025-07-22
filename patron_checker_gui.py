import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv
import threading

# Load environment variables
load_dotenv()

class AlmaPatronChecker:
    def __init__(self, root):
        self.root = root
        self.root.title("Alma Patron Checker")
        self.root.geometry("800x700")
        self.root.configure(bg='#f0f0f0')
        
        # API Configuration
        self.alma_api_key = os.getenv('ALMA_API_KEY')
        self.alma_api_base_url = os.getenv('ALMA_API_BASE_URL')
        
        if not self.alma_api_key or not self.alma_api_base_url:
            messagebox.showerror("Configuration Error", 
                               "API credentials not found. Please ensure .env file is present with ALMA_API_KEY and ALMA_API_BASE_URL")
            return
        
        self.setup_ui()
    
    def setup_ui(self):
        # Title
        title_frame = tk.Frame(self.root, bg='#f0f0f0')
        title_frame.pack(pady=10)
        
        title_label = tk.Label(title_frame, text="🔍 Alma Patron Checker", 
                              font=('Arial', 18, 'bold'), bg='#f0f0f0', fg='#333')
        title_label.pack()
        
        # Search Section
        search_frame = tk.LabelFrame(self.root, text="Search Options", 
                                   font=('Arial', 12, 'bold'), bg='#f0f0f0', fg='#333')
        search_frame.pack(padx=20, pady=10, fill='x')
        
        # Search Type Selection
        self.search_type = tk.StringVar(value="barcode")
        
        radio_frame = tk.Frame(search_frame, bg='#f0f0f0')
        radio_frame.pack(pady=10)
        
        tk.Radiobutton(radio_frame, text="Barcode", variable=self.search_type, 
                      value="barcode", command=self.update_search_fields,
                      bg='#f0f0f0', font=('Arial', 10)).pack(side='left', padx=10)
        tk.Radiobutton(radio_frame, text="Name", variable=self.search_type, 
                      value="name", command=self.update_search_fields,
                      bg='#f0f0f0', font=('Arial', 10)).pack(side='left', padx=10)
        tk.Radiobutton(radio_frame, text="Email", variable=self.search_type, 
                      value="email", command=self.update_search_fields,
                      bg='#f0f0f0', font=('Arial', 10)).pack(side='left', padx=10)
        
        # Input Fields Frame
        self.input_frame = tk.Frame(search_frame, bg='#f0f0f0')
        self.input_frame.pack(padx=20, pady=10, fill='x')
        
        # Initialize input fields
        self.update_search_fields()
        
        # Search Button
        self.search_button = tk.Button(search_frame, text="🔍 Search", 
                                     command=self.search_patron, bg='#007bff', fg='white',
                                     font=('Arial', 12, 'bold'), padx=20, pady=5)
        self.search_button.pack(pady=10)
        
        # Progress Bar
        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(padx=20, pady=5, fill='x')
        
        # Results Section
        self.results_frame = tk.LabelFrame(self.root, text="Results", 
                                         font=('Arial', 12, 'bold'), bg='#f0f0f0', fg='#333')
        self.results_frame.pack(padx=20, pady=10, fill='both', expand=True)
        
        # Results Text Area
        self.results_text = scrolledtext.ScrolledText(self.results_frame, 
                                                    height=20, font=('Courier', 10),
                                                    bg='white', fg='#333')
        self.results_text.pack(padx=10, pady=10, fill='both', expand=True)
        
        # Clear Button
        clear_button = tk.Button(self.results_frame, text="Clear Results", 
                               command=self.clear_results, bg='#6c757d', fg='white',
                               font=('Arial', 10))
        clear_button.pack(pady=5)
    
    def update_search_fields(self):
        # Clear existing widgets
        for widget in self.input_frame.winfo_children():
            widget.destroy()
        
        search_type = self.search_type.get()
        
        if search_type == "barcode":
            tk.Label(self.input_frame, text="Barcode:", bg='#f0f0f0', 
                    font=('Arial', 10, 'bold')).pack(anchor='w')
            self.barcode_entry = tk.Entry(self.input_frame, font=('Arial', 12))
            self.barcode_entry.pack(fill='x', pady=5)
            self.barcode_entry.focus()
            
        elif search_type == "name":
            tk.Label(self.input_frame, text="First Name:", bg='#f0f0f0', 
                    font=('Arial', 10, 'bold')).pack(anchor='w')
            self.first_name_entry = tk.Entry(self.input_frame, font=('Arial', 12))
            self.first_name_entry.pack(fill='x', pady=2)
            
            tk.Label(self.input_frame, text="Last Name:", bg='#f0f0f0', 
                    font=('Arial', 10, 'bold')).pack(anchor='w', pady=(10,0))
            self.last_name_entry = tk.Entry(self.input_frame, font=('Arial', 12))
            self.last_name_entry.pack(fill='x', pady=2)
            self.first_name_entry.focus()
            
        elif search_type == "email":
            tk.Label(self.input_frame, text="Email Address:", bg='#f0f0f0', 
                    font=('Arial', 10, 'bold')).pack(anchor='w')
            self.email_entry = tk.Entry(self.input_frame, font=('Arial', 12))
            self.email_entry.pack(fill='x', pady=5)
            self.email_entry.focus()
    
    def call_alma_api(self, endpoint, params=None):
        """Makes a GET request to the Alma API."""
        url = f"{self.alma_api_base_url}/almaws/v1{endpoint}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"apikey {self.alma_api_key}"
        }
        if params is None:
            params = {}
        params['apikey'] = self.alma_api_key
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise Exception(f"API Error: {str(e)}")
    
    def search_patron(self):
        # Start search in a separate thread to prevent UI freezing
        search_thread = threading.Thread(target=self._perform_search)
        search_thread.daemon = True
        search_thread.start()
    
    def _perform_search(self):
        try:
            # Update UI on main thread
            self.root.after(0, self._start_search_ui)
            
            search_type = self.search_type.get()
            
            if search_type == "barcode":
                barcode = self.barcode_entry.get().strip()
                if not barcode:
                    raise ValueError("Please enter a barcode")
                user_data = self._get_user_by_barcode(barcode)
                
            elif search_type == "name":
                first_name = self.first_name_entry.get().strip()
                last_name = self.last_name_entry.get().strip()
                if not first_name or not last_name:
                    raise ValueError("Please enter both first and last names")
                user_data = self._search_users_by_name(first_name, last_name)
                
            elif search_type == "email":
                email = self.email_entry.get().strip()
                if not email:
                    raise ValueError("Please enter an email address")
                user_data = self._search_users_by_email(email)
            
            if user_data:
                result_text = self._format_user_info(user_data)
                self.root.after(0, lambda: self._display_results(result_text))
            else:
                self.root.after(0, lambda: self._display_results("No user found with the provided information."))
                
        except Exception as e:
            self.root.after(0, lambda: self._display_error(str(e)))
        finally:
            self.root.after(0, self._stop_search_ui)
    
    def _start_search_ui(self):
        self.search_button.config(state='disabled', text='Searching...')
        self.progress.start()
        self.clear_results()
    
    def _stop_search_ui(self):
        self.search_button.config(state='normal', text='🔍 Search')
        self.progress.stop()
    
    def _get_user_by_barcode(self, barcode):
        user_data = self.call_alma_api(f"/users/{barcode}")
        if not user_data:
            user_data = self.call_alma_api(f"/users/{barcode}", params={"user_id_type": "BARCODE"})
        return user_data
    
    def _search_users_by_name(self, first_name, last_name):
        search_params = {
            'q': f'last_name~{last_name} AND first_name~{first_name}',
            'limit': 10
        }
        users_data = self.call_alma_api("/users", params=search_params)
        
        if not users_data or 'user' not in users_data:
            return None
        
        users = users_data['user']
        if len(users) == 0:
            return None
        elif len(users) == 1:
            user_id = users[0].get('primary_id')
            if user_id:
                return self.call_alma_api(f"/users/{user_id}")
            return users[0]
        else:
            # Handle multiple users - for simplicity, return the first one
            # In a more advanced version, you could show a selection dialog
            user_id = users[0].get('primary_id')
            if user_id:
                return self.call_alma_api(f"/users/{user_id}")
            return users[0]
    
    def _search_users_by_email(self, email):
        search_params = {
            'q': f'email~{email}',
            'limit': 10
        }
        users_data = self.call_alma_api("/users", params=search_params)
        
        if not users_data or 'user' not in users_data:
            return None
        
        users = users_data['user']
        if len(users) == 0:
            return None
        elif len(users) == 1:
            user_id = users[0].get('primary_id')
            if user_id:
                return self.call_alma_api(f"/users/{user_id}")
            return users[0]
        else:
            # Handle multiple users - return the first one
            user_id = users[0].get('primary_id')
            if user_id:
                return self.call_alma_api(f"/users/{user_id}")
            return users[0]
    
    def _format_user_info(self, user_data):
        if not user_data:
            return "No user data available."
        
        user_id = user_data.get('primary_id')
        if not user_id:
            return "Could not retrieve user ID."
        
        # Basic user info
        first_name = user_data.get('first_name', 'N/A')
        last_name = user_data.get('last_name', 'N/A')
        full_name = f"{first_name} {last_name}"
        email = user_data.get('contact_info', {}).get('email', [{}])[0].get('email_address', 'N/A')
        patron_group = user_data.get('user_group', {}).get('desc', 'N/A')
        
        result = f"""
═══════════════════════════════════════════════════
                    USER INFORMATION
═══════════════════════════════════════════════════

👤 Name: {full_name}
🆔 ID: {user_id}
📧 Email: {email}
👥 Patron Group: {patron_group}

"""
        
        # Get loans
        try:
            loans_data = self.call_alma_api(f"/users/{user_id}/loans")
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
            
            result += f"""📚 LOAN INFORMATION
───────────────────────────────────────────────────
• Current Loans: {current_loans_count}
• Overdue Loans: {overdue_loans_count}
"""
            
            if overdue_details:
                result += "\n⚠️  OVERDUE ITEMS:\n"
                for item in overdue_details:
                    result += f"   • {item['title'][:50]}{'...' if len(item['title']) > 50 else ''}\n"
                    result += f"     Due: {item['due_date']} ({item['days_overdue']} days overdue)\n\n"
        
        except Exception as e:
            result += f"📚 LOAN INFORMATION: Error retrieving loan data ({str(e)})\n"
        
        # Get fines
        try:
            fees_data = self.call_alma_api(f"/users/{user_id}/fees")
            total_fines_amount = 0.0
            
            if fees_data and 'fee' in fees_data:
                for fee in fees_data['fee']:
                    if fee.get('status', {}).get('value') == 'ACTIVE':
                        total_fines_amount += float(fee.get('amount', 0.0))
            
            result += f"""
💰 FINE INFORMATION
───────────────────────────────────────────────────
• Total Active Fines: ${total_fines_amount:.2f}
"""
        except Exception as e:
            result += f"\n💰 FINE INFORMATION: Error retrieving fine data ({str(e)})\n"
        
        # Get blocks
        try:
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
            
            result += f"""
🚫 BLOCK INFORMATION
───────────────────────────────────────────────────
"""
            if active_blocks:
                result += f"• Number of Active Blocks: {len(active_blocks)}\n\n"
                for i, block in enumerate(active_blocks, 1):
                    result += f"   Block {i}:\n"
                    result += f"   • Type: {block['type']}\n"
                    result += f"   • Description: {block['description']}\n"
                    result += f"   • Created: {block['created_date']}\n"
                    result += f"   • Created by: {block['created_by']}\n\n"
            else:
                result += "• No active blocks found.\n"
                
        except Exception as e:
            result += f"🚫 BLOCK INFORMATION: Error retrieving block data ({str(e)})\n"
        
        result += "\n═══════════════════════════════════════════════════\n"
        return result
    
    def _display_results(self, text):
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(tk.END, text)
    
    def _display_error(self, error_message):
        error_text = f"""
❌ ERROR
═══════════════════════════════════════════════════

{error_message}

Please check your input and try again.

═══════════════════════════════════════════════════
"""
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(tk.END, error_text)
    
    def clear_results(self):
        self.results_text.delete(1.0, tk.END)

def main():
    root = tk.Tk()
    app = AlmaPatronChecker(root)
    
    # Center the window on screen
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - (root.winfo_width() // 2)
    y = (root.winfo_screenheight() // 2) - (root.winfo_height() // 2)
    root.geometry(f"+{x}+{y}")
    
    root.mainloop()

if __name__ == "__main__":
    main()
