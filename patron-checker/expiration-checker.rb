#!/usr/bin/env ruby
# frozen_string_literal: true

require 'net/http'
require 'json'
require 'uri'
require 'time'
require 'date'
require 'dotenv'

# Prompt for environment selection
def select_environment
  puts "\n" + ('=' * 60)
  puts 'ALMA ENVIRONMENT SELECTION'
  puts '=' * 60
  puts "\nWhich environment would you like to analyze?"
  puts "1. Production"
  puts "2. Sandbox"
  print "\nEnter your choice (1 or 2): "
  
  choice = gets.strip
  
  case choice
  when '1', 'production', 'prod', 'p'
    env_file = '.env'
    env_name = 'Production'
  when '2', 'sandbox', 'sand', 's'
    env_file = '.env.sandbox'
    env_name = 'Sandbox'
  else
    puts "\nInvalid choice. Defaulting to Production."
    env_file = '.env'
    env_name = 'Production'
  end
  
  # Load the selected environment file
  if File.exist?(env_file)
    Dotenv.load(env_file)
    puts "\n✅ Loaded #{env_name} environment from #{env_file}"
  else
    puts "\n❌ Error: #{env_file} not found!"
    exit 1
  end
  
  env_name
end

# Select and load environment
ENVIRONMENT = select_environment

API_KEY = ENV['ALMA_API_KEY']
BASE_URL = ENV['ALMA_API_BASE_URL'] || 'https://api-na.hosted.exlibrisgroup.com'

# Fetch all users from Alma API with pagination
#
# Args:
#   progress (Boolean): Whether to show progress messages
#
# Returns:
#   Array: List of user hashes
def get_all_users(progress: true)
  users = []
  offset = 0
  limit = 100
  
  loop do
    url = URI("#{BASE_URL}/almaws/v1/users")
    params = {
      'limit' => limit,
      'offset' => offset,
      'format' => 'json',
      'expand' => 'full'
    }
    url.query = URI.encode_www_form(params)
    
    http = Net::HTTP.new(url.host, url.port)
    if url.scheme == 'https'
      http.use_ssl = true
      http.verify_mode = OpenSSL::SSL::VERIFY_NONE
    end
    
    request = Net::HTTP::Get.new(url)
    request['Authorization'] = "apikey #{API_KEY}"
    request['Accept'] = 'application/json'
    
    begin
      response = http.request(request)
      
      unless response.is_a?(Net::HTTPSuccess)
        puts "Error fetching users: #{response.code} - #{response.body}" if progress
        break
      end
      
      data = JSON.parse(response.body)
      
      break unless data.key?('user')
      
      batch_users = data['user']
      break if batch_users.empty?
      
      users.concat(batch_users)
      puts "Fetched #{users.length} users so far..." if progress
      
      break if batch_users.length < limit
      
      offset += limit
      
      # Small delay to be nice to the API
      sleep(0.2)
      
    rescue StandardError => e
      puts "Error fetching users: #{e.message}" if progress
      break
    end
  end
  
  users
end

# Parse Alma date format to DateTime object
#
# Args:
#   date_string (String): Date string from Alma API
#
# Returns:
#   DateTime: Parsed date, or nil if parsing fails
def parse_alma_date(date_string)
  return nil if date_string.nil? || date_string.empty?
  
  # Alma dates can be in various formats, try common ones
  date_formats = [
    '%Y-%m-%dZ',           # 2023-12-31Z
    '%Y-%m-%d',            # 2023-12-31
    '%Y-%m-%dT%H:%M:%SZ',  # 2023-12-31T23:59:59Z
    '%Y-%m-%dT%H:%M:%S'    # 2023-12-31T23:59:59
  ]
  
  date_formats.each do |fmt|
    begin
      return DateTime.strptime(date_string, fmt)
    rescue ArgumentError
      next
    end
  end
  
  # Try Ruby's Time.parse as fallback
  begin
    return Time.parse(date_string)
  rescue ArgumentError
    nil
  end
end

# Get users that expired before a specific date
#
# Args:
#   users (Array): List of user hashes
#   cutoff_date (DateTime): Date to check against
#
# Returns:
#   Array: List of expired users with their info
def get_expired_users(users, cutoff_date)
  expired_users = []
  
  users.each_with_index do |user, index|
    expiry_date_str = user['expiry_date']
    
    if expiry_date_str
      expiry_date = parse_alma_date(expiry_date_str)
      
      if expiry_date && expiry_date < cutoff_date
        expired_users << {
          'primary_id' => user['primary_id'],
          'first_name' => user['first_name'] || '',
          'last_name' => user['last_name'] || '',
          'expiry_date' => expiry_date,
          'expiry_date_string' => expiry_date_str,
          'user_group' => user.dig('user_group', 'value') || user['user_group'] || 'Unknown',
          'status' => user.dig('status', 'value') || user['status'] || 'Unknown'
        }
      end
    end
    
    # Progress indicator
    puts "Processed #{index + 1}/#{users.length} users..." if ((index + 1) % 500).zero?
  end
  
  expired_users
end

# Prompt user for a date
#
# Returns:
#   DateTime: The date entered by the user
def prompt_for_date
  puts "\n" + ('=' * 60)
  puts "ALMA USER EXPIRATION CHECKER (#{ENVIRONMENT})"
  puts '=' * 60
  puts "\nThis script will find all users that expired before a given date."
  puts "\nEnter a cutoff date to check for expired users."
  puts "Users that expired BEFORE this date will be identified."
  puts "\nFormat: YYYY-MM-DD (e.g., 2024-12-31)"
  print "\nEnter date: "
  
  date_input = gets.strip
  
  begin
    date = Date.parse(date_input)
    DateTime.new(date.year, date.month, date.day, 23, 59, 59)
  rescue ArgumentError
    puts "\nInvalid date format. Please use YYYY-MM-DD format."
    exit 1
  end
end

# Save results to CSV file
#
# Args:
#   expired_users (Array): List of expired users
#   cutoff_date (DateTime): The cutoff date used
def save_to_csv(expired_users, cutoff_date)
  require 'csv'
  
  filename = "expired_users_before_#{cutoff_date.strftime('%Y%m%d')}.csv"
  
  CSV.open(filename, 'w') do |csv|
    # Write header
    csv << ['Primary ID', 'First Name', 'Last Name', 'Expiry Date', 'User Group', 'Status']
    
    # Write data rows
    expired_users.each do |user|
      csv << [
        user['primary_id'],
        user['first_name'],
        user['last_name'],
        user['expiry_date'].strftime('%Y-%m-%d'),
        user['user_group'],
        user['status']
      ]
    end
  end
  
  puts "\n✅ Results saved to: #{filename}"
end

# Main function
def main
  unless API_KEY && !API_KEY.empty?
    puts 'Error: ALMA_API_KEY not found in environment variables'
    puts "Please ensure your environment file contains ALMA_API_KEY"
    exit 1
  end
  
  puts "\n✅ Using #{ENVIRONMENT} environment"
  
  # Get cutoff date from user
  cutoff_date = prompt_for_date
  
  puts "\n" + ('-' * 60)
  puts "Cutoff date: #{cutoff_date.strftime('%Y-%m-%d')}"
  puts "Searching for users that expired BEFORE this date..."
  puts '-' * 60
  
  # Fetch all users
  puts "\nFetching all users from Alma..."
  users = get_all_users
  
  if users.empty?
    puts "\n❌ No users found or error fetching users."
    exit 1
  end
  
  puts "\n✅ Fetched #{users.length} total users"
  
  # Find expired users
  puts "\nAnalyzing expiration dates..."
  expired_users = get_expired_users(users, cutoff_date)
  
  # Display results
  puts "\n" + ('=' * 60)
  puts 'RESULTS'
  puts '=' * 60
  puts "\nTotal users analyzed: #{users.length}"
  puts "Users expired before #{cutoff_date.strftime('%Y-%m-%d')}: #{expired_users.length}"
  
  if expired_users.any?
    # Group by user group for summary
    by_group = expired_users.group_by { |u| u['user_group'] }
    
    puts "\nExpired users by group:"
    by_group.sort_by { |_group, users| -users.length }.each do |group, users_in_group|
      puts "  #{group}: #{users_in_group.length}"
    end
    
    # Show sample of expired users
    puts "\nSample of expired users (first 20):"
    puts format('%-20s %-20s %-20s %-12s %s', 
                'Primary ID', 'First Name', 'Last Name', 'Expired', 'Group')
    puts '-' * 90
    
    expired_users.first(20).each do |user|
      first_name = user['first_name'][0..18] || ''
      last_name = user['last_name'][0..18] || ''
      puts format('%-20s %-20s %-20s %-12s %s',
                  user['primary_id'],
                  first_name,
                  last_name,
                  user['expiry_date'].strftime('%Y-%m-%d'),
                  user['user_group'])
    end
    
    if expired_users.length > 20
      puts "\n... and #{expired_users.length - 20} more"
    end
    
    # Save to CSV
    puts "\n" + ('-' * 60)
    print "Save results to CSV file? (y/n): "
    response = gets.strip.downcase
    
    if response == 'y' || response == 'yes'
      save_to_csv(expired_users, cutoff_date)
    end
    
    # Save detailed JSON report
    json_filename = "expired_users_before_#{cutoff_date.strftime('%Y%m%d')}.json"
    report = {
      'cutoff_date' => cutoff_date.iso8601,
      'total_users_analyzed' => users.length,
      'expired_users_count' => expired_users.length,
      'by_group' => by_group.transform_values(&:length),
      'expired_users' => expired_users.map do |u|
        u.merge('expiry_date' => u['expiry_date'].iso8601)
      end
    }
    
    File.write(json_filename, JSON.pretty_generate(report))
    puts "✅ Detailed report saved to: #{json_filename}"
    
  else
    puts "\n✅ No users found that expired before #{cutoff_date.strftime('%Y-%m-%d')}"
  end
  
  puts "\n" + ('=' * 60)
  puts 'Done!'
  puts '=' * 60
end

# Run main function if script is executed directly
main if __FILE__ == $PROGRAM_NAME
