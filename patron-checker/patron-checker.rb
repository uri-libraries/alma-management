#!/usr/bin/env ruby
# frozen_string_literal: true

require 'net/http'
require 'json'
require 'uri'
require 'time'
require 'dotenv/load'
# the point of this script it to get detailed information about a user in Alma
# --- Configuration ---
# Load environment variables from .env file
Dotenv.load

# Get API credentials from environment variables
ALMA_API_KEY = ENV['ALMA_API_KEY']
ALMA_API_BASE_URL = ENV['ALMA_API_BASE_URL']

# --- Helper Function to Make API Calls ---
# Makes a GET request to the Alma API.
#
# Args:
#   endpoint (String): The API endpoint (e.g., "/users/12345").
#   params (Hash, optional): Hash of query parameters. Defaults to {}.
#   suppress_errors (Boolean, optional): If true, suppresses error messages. Defaults to false.
#
# Returns:
#   Hash: The JSON response from the API, or nil if an error occurs.
def call_alma_api(endpoint, params = {}, suppress_errors: false)
  url = URI("#{ALMA_API_BASE_URL}/almaws/v1#{endpoint}")
  
  # Add query parameters
  params['apikey'] = ALMA_API_KEY
  url.query = URI.encode_www_form(params) unless params.empty?

  begin
    http = Net::HTTP.new(url.host, url.port)
    if url.scheme == 'https'
      http.use_ssl = true
      http.verify_mode = OpenSSL::SSL::VERIFY_NONE
    end
    
    request = Net::HTTP::Get.new(url)
    request['Accept'] = 'application/json'
    request['Authorization'] = "apikey #{ALMA_API_KEY}"
    
    response = http.request(request)
    
    if response.is_a?(Net::HTTPSuccess)
      JSON.parse(response.body)
    else
      puts "HTTP error occurred: #{response.code} - #{response.body}" unless suppress_errors
      nil
    end
  rescue Net::HTTPError => e
    puts "HTTP error occurred: #{e.message}" unless suppress_errors
    nil
  rescue SocketError => e
    puts "Connection error occurred: #{e.message}" unless suppress_errors
    nil
  rescue Timeout::Error => e
    puts "Timeout error occurred: #{e.message}" unless suppress_errors
    nil
  rescue JSON::ParserError => e
    puts "Error decoding JSON response from #{url}: #{e.message}" unless suppress_errors
    nil
  rescue StandardError => e
    puts "An unexpected error occurred: #{e.message}" unless suppress_errors
    nil
  end
end

# --- Main Function to Get User Information ---
# Retrieves user information using a barcode.
#
# Args:
#   barcode (String): The barcode of the Alma user.
def get_user_by_barcode(barcode)
  puts "\n--- Searching for user with barcode: #{barcode} ---"
  
  # Try different approaches to find user by barcode
  user_data = call_alma_api("/users/#{barcode}")
  
  if user_data.nil?
    # Try with explicit barcode parameter
    user_data = call_alma_api("/users/#{barcode}", { 'user_id_type' => 'BARCODE' })
  end
  
  user_data
end

# Searches for users by first and last name.
#
# Args:
#   first_name (String): The first name to search for.
#   last_name (String): The last name to search for.
def search_users_by_name(first_name, last_name)
  puts "\n--- Searching for users with name: #{first_name} #{last_name} ---"
  
  # Search users endpoint with name parameters
  search_params = {
    'q' => "last_name~#{last_name} AND first_name~#{first_name}",
    'limit' => 10
  }
  
  users_data = call_alma_api('/users', search_params)
  
  if users_data.nil? || !users_data.key?('user')
    puts "No users found with name: #{first_name} #{last_name}"
    return nil
  end
  
  users = users_data['user']
  if users.empty?
    puts "No users found with name: #{first_name} #{last_name}"
    return nil
  elsif users.length == 1
    puts 'Found 1 user matching the name.'
    selected_user = users[0]
  else
    puts "Found #{users.length} users matching the name:"
    users.each_with_index do |user, index|
      name = "#{user['first_name'] || 'N/A'} #{user['last_name'] || 'N/A'}"
      user_id = user['primary_id'] || 'N/A'
      puts "  #{index + 1}. #{name} (ID: #{user_id})"
    end
    
    loop do
      print "\nSelect user (1-#{users.length}) or 'cancel' to go back: "
      choice = gets.strip
      
      if choice.downcase == 'cancel'
        return nil
      end
      
      choice_num = choice.to_i
      if choice_num.between?(1, users.length)
        selected_user = users[choice_num - 1]
        break
      else
        puts "Please enter a number between 1 and #{users.length}"
      end
    end
  end
  
  # Now get the full user details using the primary_id
  user_id = selected_user['primary_id']
  if user_id
    puts "Getting full details for user: #{user_id}"
    full_user_data = call_alma_api("/users/#{user_id}")
    full_user_data
  else
    puts 'Could not get primary_id for selected user'
    selected_user
  end
end

# Searches for users by email address.
#
# Args:
#   email (String): The email address to search for.
def search_users_by_email(email)
  puts "\n--- Searching for users with email: #{email} ---"
  
  # Search users endpoint with email parameter
  search_params = {
    'q' => "email~#{email}",
    'limit' => 10
  }
  
  users_data = call_alma_api('/users', search_params)
  
  if users_data.nil? || !users_data.key?('user')
    puts "No users found with email: #{email}"
    return nil
  end
  
  users = users_data['user']
  if users.empty?
    puts "No users found with email: #{email}"
    return nil
  elsif users.length == 1
    puts 'Found 1 user matching the email.'
    selected_user = users[0]
  else
    puts "Found #{users.length} users matching the email:"
    users.each_with_index do |user, index|
      name = "#{user['first_name'] || 'N/A'} #{user['last_name'] || 'N/A'}"
      user_id = user['primary_id'] || 'N/A'
      puts "  #{index + 1}. #{name} (ID: #{user_id})"
    end
    
    loop do
      print "\nSelect user (1-#{users.length}) or 'cancel' to go back: "
      choice = gets.strip
      
      if choice.downcase == 'cancel'
        return nil
      end
      
      choice_num = choice.to_i
      if choice_num.between?(1, users.length)
        selected_user = users[choice_num - 1]
        break
      else
        puts "Please enter a number between 1 and #{users.length}"
      end
    end
  end
  
  # Now get the full user details using the primary_id
  user_id = selected_user['primary_id']
  if user_id
    puts "Getting full details for user: #{user_id}"
    full_user_data = call_alma_api("/users/#{user_id}")
    full_user_data
  else
    puts 'Could not get primary_id for selected user'
    selected_user
  end
end

# Displays detailed information for a user.
#
# Args:
#   user_data (Hash): The user data from Alma API.
def display_user_info(user_data)
  return if user_data.nil?

  user_id = user_data['primary_id']
  if user_id.nil?
    puts 'Could not retrieve primary ID for the user.'
    return
  end

  # Extract basic user info
  first_name = user_data['first_name'] || 'N/A'
  last_name = user_data['last_name'] || 'N/A'
  full_name = "#{first_name} #{last_name}"
  email = user_data.dig('contact_info', 'email', 0, 'email_address') || 'N/A'
  patron_group = user_data.dig('user_group', 'desc') || 'N/A'

  puts "\nUser Found: #{full_name} (ID: #{user_id})"
  puts "  Email: #{email}"
  puts "  Patron Group: #{patron_group}"

  # 2. Get User Loans
  loans_data = call_alma_api("/users/#{user_id}/loans")
  current_loans_count = 0
  overdue_loans_count = 0
  overdue_details = []

  if loans_data && loans_data.key?('item_loan')
    loans_data['item_loan'].each do |loan|
      current_loans_count += 1
      due_date_str = loan['due_date']
      if due_date_str
        begin
          # Alma dates are often in ISO format, e.g., "2025-07-20T23:59:00Z"
          due_date = Time.parse(due_date_str)
          now = Time.now
          if now > due_date
            overdue_loans_count += 1
            days_overdue = ((now - due_date) / 86400).to_i
            overdue_details << {
              'title' => loan['title'] || 'N/A',
              'due_date' => due_date.strftime('%Y-%m-%d %H:%M'),
              'days_overdue' => days_overdue
            }
          end
        rescue ArgumentError
          puts "Warning: Could not parse due date for loan: #{due_date_str}"
        end
      else
        puts "Warning: Loan without a due date found: #{loan['title'] || 'N/A'}"
      end
    end
  end

  puts "\nLoan Information:"
  puts "  Number of current loans: #{current_loans_count}"
  puts "  Number of overdue loans: #{overdue_loans_count}"

  if overdue_loans_count > 0
    puts '  Overdue Loan Details:'
    overdue_details.each do |detail|
      puts "    - Title: #{detail['title']}, Due: #{detail['due_date']}, Overdue by: #{detail['days_overdue']} days"
    end
  end

  # 3. Get User Fines
  fees_data = call_alma_api("/users/#{user_id}/fees")
  total_fines_amount = 0.0

  if fees_data && fees_data.key?('fee')
    fees_data['fee'].each do |fee|
      if fee.dig('status', 'value') == 'ACTIVE' # Only sum active fines
        total_fines_amount += (fee['amount'] || 0.0).to_f
      end
    end
  end

  puts "\nFine Information:"
  puts "  Total amount of active fines: $#{format('%.2f', total_fines_amount)}"

  # 4. Get User Blocks
  puts "\nBlock Information:"
  active_blocks = []
  
  # Check various possible keys for blocks in the main user data
  block_keys_to_check = %w[user_block user_blocks blocks userBlocks patron_blocks]
  block_keys_to_check.each do |key|
    next unless user_data.key?(key) && user_data[key]

    user_blocks_data = user_data[key]
    
    # Handle if it's a list directly
    if user_blocks_data.is_a?(Array)
      user_blocks_data.each do |block|
        # Check different possible status field names and values
        status_active = false
        if block['block_status'] == 'ACTIVE'
          status_active = true
        elsif block.dig('status', 'value') == 'ACTIVE'
          status_active = true
        elsif block['status'] == 'ACTIVE'
          status_active = true
        end
        
        if status_active
          block_info = {
            'type' => block.dig('block_type', 'desc') || 'N/A',
            'description' => block.dig('block_description', 'desc') || 'N/A',
            'created_date' => block['created_date'] || 'N/A',
            'created_by' => block['created_by'] || 'N/A',
            'note' => block['note'] || ''
          }
          active_blocks << block_info
          break # Found blocks in main data, no need to check API endpoints
        end
      end
    # Handle if it's nested in a dict structure
    elsif user_blocks_data.is_a?(Hash) && user_blocks_data.key?('user_block')
      user_blocks_data['user_block'].each do |block|
        status_active = false
        if block['block_status'] == 'ACTIVE'
          status_active = true
        elsif block.dig('status', 'value') == 'ACTIVE'
          status_active = true
        elsif block['status'] == 'ACTIVE'
          status_active = true
        end
        
        if status_active
          block_info = {
            'type' => block.dig('block_type', 'desc') || 'N/A',
            'description' => block.dig('block_description', 'desc') || 'N/A',
            'created_date' => block['created_date'] || 'N/A',
            'created_by' => block['created_by'] || 'N/A',
            'note' => block['note'] || ''
          }
          active_blocks << block_info
          break # Found blocks in main data, no need to check API endpoints
        end
      end
    end
  end

  # Display results
  if active_blocks.any?
    puts "  Number of active blocks: #{active_blocks.length}"
    puts '  Active Block Details:'
    active_blocks.each_with_index do |block, index|
      puts "    #{index + 1}. Type: #{block['type']}"
      puts "       Description: #{block['description']}"
      puts "       Created: #{block['created_date']}"
      puts "       Created by: #{block['created_by']}" unless block['created_by'].empty?
      puts "       Note: #{block['note']}" unless block['note'].empty?
      puts if index < active_blocks.length - 1 # Add separator between blocks
    end
  else
    puts '  The patron has no blocks.'
  end
end

# --- Main Execution Block ---
if __FILE__ == $PROGRAM_NAME
  puts 'Welcome to the Alma User Information Script!'
  puts 'Please ensure your ALMA_API_KEY and ALMA_API_BASE_URL environment variables are set.'

  if ALMA_API_KEY.nil? || ALMA_API_KEY.empty? || ALMA_API_BASE_URL.nil? || ALMA_API_BASE_URL.empty?
    puts "\nERROR: Please set the following environment variables:"
    puts '  ALMA_API_KEY - Your Alma API key'
    puts '  ALMA_API_BASE_URL - Your Alma API base URL (e.g., https://api-na.exlibrisgroup.com)'
    puts "\nYou can set them in your .env file or by running:"
    puts "  export ALMA_API_KEY='your_api_key_here'"
    puts "  export ALMA_API_BASE_URL='your_base_url_here'"
    exit 1
  else
    loop do
      puts "\n" + ('=' * 50)
      puts 'How would you like to search for the user?'
      puts '1. Barcode'
      puts '2. Name (First and Last)'
      puts '3. Email Address'
      puts '4. Quit'
      
      print "\nEnter your choice (1-4): "
      choice = gets.strip
      
      case choice
      when '1'
        print 'Enter the barcode: '
        barcode = gets.strip
        if !barcode.empty?
          user_data = get_user_by_barcode(barcode)
          if user_data
            display_user_info(user_data)
          else
            puts "Could not find user with barcode: #{barcode}"
          end
        else
          puts 'Barcode cannot be empty.'
        end
        
      when '2'
        print 'Enter the first name: '
        first_name = gets.strip
        if !first_name.empty?
          print 'Enter the last name: '
          last_name = gets.strip
          if !last_name.empty?
            user_data = search_users_by_name(first_name, last_name)
            display_user_info(user_data) if user_data
          else
            puts 'Last name cannot be empty.'
          end
        else
          puts 'First name cannot be empty.'
        end
        
      when '3'
        print 'Enter the email address: '
        email = gets.strip
        if !email.empty?
          user_data = search_users_by_email(email)
          display_user_info(user_data) if user_data
        else
          puts 'Email address cannot be empty.'
        end
        
      when '4', 'quit'
        break
        
      else
        puts 'Invalid choice. Please enter 1, 2, 3, or 4.'
      end
    end
  end

  puts "\nGoodbye!"
end
