#!/usr/bin/env ruby
# frozen_string_literal: true

require 'net/http'
require 'json'
require 'uri'
require 'dotenv'
# Limiter: Set to an integer to process only that many users. Comment out to process all.
MAX_DEACTIVATIONS = 10 # Change this value or comment out to disable limit

# Prompt for environment selection
def select_environment
  puts "\n" + ('=' * 60)
  puts 'ALMA ENVIRONMENT SELECTION'
  puts '=' * 60
  puts "\nWhich environment would you like to use?"
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

# Fetch user details from Alma
#
# Args:
#   user_id (String): The primary identifier of the user
#
# Returns:
#   Hash: User data, or nil if error
def get_user(user_id)
  url = URI("#{BASE_URL}/almaws/v1/users/#{user_id}")
  
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
    
    if response.is_a?(Net::HTTPSuccess)
      JSON.parse(response.body)
    else
      puts "  ❌ Error fetching user: #{response.code}"
      nil
    end
  rescue StandardError => e
    puts "  ❌ Error: #{e.message}"
    nil
  end
end

# Update user status to INACTIVE
#
# Args:
#   user_id (String): The primary identifier of the user
#   user_data (Hash): The current user data
#
# Returns:
#   Hash: { success: Boolean, error: String or nil }
def deactivate_user(user_id, user_data)
  url = URI("#{BASE_URL}/almaws/v1/users/#{user_id}")
  
  http = Net::HTTP.new(url.host, url.port)
  if url.scheme == 'https'
    http.use_ssl = true
    http.verify_mode = OpenSSL::SSL::VERIFY_NONE
  end
  
  # Clean up user data to avoid validation errors
  # Remove fields that might cause issues when updating
  user_data.delete('link')
  user_data.delete('proxy_for_user')
  user_data.delete('rs_libraries')
  
  # Clean up contact_info - remove invalid phone entries
  if user_data['contact_info'] && user_data['contact_info']['phone']
    valid_phone_types = ['mobile', 'home', 'office', 'other']
    
    valid_phones = user_data['contact_info']['phone'].select do |phone|
      if phone['phone_type']
        phone_type = phone['phone_type']
        type_value = if phone_type.is_a?(Hash)
                       phone_type['value'] || phone_type['desc']
                     else
                       phone_type.to_s
                     end
        
        # Keep only valid phone types
        valid_phone_types.include?(type_value.to_s.downcase)
      else
        false # Remove phones without type
      end
    end
    
    # Update with only valid phones
    if valid_phones.empty?
      user_data['contact_info'].delete('phone')
    else
      user_data['contact_info']['phone'] = valid_phones
    end
  end
  
  # Clean up user_identifier to remove duplicates
  if user_data['user_identifier']
    identifiers = user_data['user_identifier']
    identifiers = [identifiers] unless identifiers.is_a?(Array)
    
    # Group by value and keep only one of each
    seen_values = {}
    unique_identifiers = []
    
    identifiers.each do |id|
      value = id['value']
      id_type = id['id_type']
      type_value = id_type.is_a?(Hash) ? id_type['value'] : id_type.to_s
      
      # Create a key that combines value
      if !seen_values[value]
        unique_identifiers << id
        seen_values[value] = true
      end
    end
    
    user_data['user_identifier'] = unique_identifiers
  end
  
  # Modify the user status
  user_data['status'] = { 'value' => 'INACTIVE' }
  
  request = Net::HTTP::Put.new(url)
  request['Authorization'] = "apikey #{API_KEY}"
  request['Accept'] = 'application/json'
  request['Content-Type'] = 'application/json'
  request.body = JSON.generate(user_data)
  
  begin
    response = http.request(request)
    
    if response.is_a?(Net::HTTPSuccess)
      { success: true, error: nil }
    else
      error_msg = "HTTP #{response.code}"
      begin
        error_body = JSON.parse(response.body)
        if error_body['errorList'] && error_body['errorList']['error']
          errors = error_body['errorList']['error']
          errors = [errors] unless errors.is_a?(Array)
          error_details = errors.map { |e| "#{e['errorCode']}: #{e['errorMessage']}" }.join('; ')
          error_msg = "#{error_msg} - #{error_details}"
        end
      rescue
        error_msg = "#{error_msg} - #{response.body[0..200]}"
      end
      puts "  ❌ Error updating user: #{error_msg}"
      { success: false, error: error_msg }
    end
  rescue StandardError => e
    error_msg = e.message
    puts "  ❌ Error: #{error_msg}"
    { success: false, error: error_msg }
  end
end

# Read primary identifiers from file
#
# Args:
#   filename (String): Path to the file containing identifiers
#
# Returns:
#   Array: List of primary identifiers (stripped of whitespace)
def read_identifiers(filename)
  unless File.exist?(filename)
    puts "\n❌ Error: File '#{filename}' not found!"
    exit 1
  end
  
  lines = File.readlines(filename).map(&:strip).reject(&:empty?)
  
  if lines.empty?
    puts "\n❌ Error: File '#{filename}' is empty!"
    exit 1
  end
  
  # Check if file contains CSV data (contains commas)
  # If so, extract only the first column (primary ID)
  identifiers = lines.map do |line|
    if line.include?(',')
      # CSV format - extract first column
      line.split(',').first.strip
    else
      # Plain text format - use as is
      line
    end
  end
  
  identifiers.reject(&:empty?)
end

# Main function
def main
  unless API_KEY && !API_KEY.empty?
    puts 'Error: ALMA_API_KEY not found in environment variables'
    puts "Please ensure your environment file contains ALMA_API_KEY"
    exit 1
  end
  
  puts "\n" + ('=' * 60)
  puts "ALMA USER DEACTIVATION TOOL (#{ENVIRONMENT})"
  puts '=' * 60
  
  filename = 'deactivate.txt'
  
  # Read identifiers from file
  puts "\nReading identifiers from #{filename}..."
  identifiers = read_identifiers(filename)
  puts "✅ Found #{identifiers.length} identifiers to process"
  
  # Confirm before proceeding
  puts "\n" + ('⚠️  ' * 20)
  puts "WARNING: This will change #{identifiers.length} users from ACTIVE to INACTIVE"
  puts "Environment: #{ENVIRONMENT}"
  puts '⚠️  ' * 20
  print "\nAre you sure you want to proceed? (yes/no): "
  
  confirmation = gets.strip.downcase
  unless confirmation == 'yes' || confirmation == 'y'
    puts "\n❌ Operation cancelled by user"
    exit 0
  end
  
  # Process each identifier
  puts "\n" + ('-' * 60)
  puts "Processing users..."
  puts '-' * 60
  
  successful = []
  failed = []
  skipped = []
  
    identifiers.each_with_index do |primary_id, idx|
      # Limiter: skip if over MAX_DEACTIVATIONS
      if defined?(MAX_DEACTIVATIONS) && MAX_DEACTIVATIONS && idx >= MAX_DEACTIVATIONS
        puts "Limiter reached: processed #{MAX_DEACTIVATIONS} users. Remove or comment out MAX_DEACTIVATIONS to process all."
        break
      end
    puts "\n[#{index + 1}/#{identifiers.length}] Processing: #{user_id}"
    
    # Fetch current user data
    user_data = get_user(user_id)
    
    unless user_data
      failed << { 'user_id' => user_id, 'reason' => 'Failed to fetch user' }
      next
    end
    
    # Check current status
    current_status = user_data.dig('status', 'value') || user_data['status']
    puts "  Current status: #{current_status}"
    
    if current_status == 'INACTIVE'
      puts "  ℹ️  Already inactive - skipping"
      skipped << user_id
      next
    end
    
    # Deactivate user
    result = deactivate_user(user_id, user_data)
    if result[:success]
      puts "  ✅ Successfully deactivated"
      successful << user_id
    else
      puts "  ❌ Failed to deactivate"
      failed << { 'user_id' => user_id, 'reason' => result[:error] || 'Update request failed' }
    end
    
    # Small delay to be nice to the API
    sleep(0.3)
  end
  
  # Summary
  puts "\n" + ('=' * 60)
  puts 'SUMMARY'
  puts '=' * 60
  puts "\nTotal processed: #{identifiers.length}"
  puts "✅ Successfully deactivated: #{successful.length}"
  puts "ℹ️  Already inactive (skipped): #{skipped.length}"
  puts "❌ Failed: #{failed.length}"
  
  # Save results
  timestamp = Time.now.strftime('%Y%m%d_%H%M%S')
  
  # Save successful deactivations
  if successful.any?
    success_file = "deactivated_#{timestamp}.txt"
    File.write(success_file, successful.join("\n"))
    puts "\n✅ Successfully deactivated users saved to: #{success_file}"
  end
  
  # Save skipped users
  if skipped.any?
    skipped_file = "already_inactive_#{timestamp}.txt"
    File.write(skipped_file, skipped.join("\n"))
    puts "ℹ️  Already inactive users saved to: #{skipped_file}"
  end
  
  # Save failed attempts
  if failed.any?
    failed_file = "deactivation_failed_#{timestamp}.json"
    File.write(failed_file, JSON.pretty_generate(failed))
    puts "❌ Failed deactivations saved to: #{failed_file}"
  end
  
  # Save detailed report
  report = {
    'timestamp' => timestamp,
    'environment' => ENVIRONMENT,
    'total_processed' => identifiers.length,
    'successful_count' => successful.length,
    'skipped_count' => skipped.length,
    'failed_count' => failed.length,
    'successful_users' => successful,
    'skipped_users' => skipped,
    'failed_users' => failed
  }
  
  report_file = "deactivation_report_#{timestamp}.json"
  File.write(report_file, JSON.pretty_generate(report))
  puts "\n📄 Detailed report saved to: #{report_file}"
  
  puts "\n" + ('=' * 60)
  puts 'Done!'
  puts '=' * 60
end

# Run main function if script is executed directly
main if __FILE__ == $PROGRAM_NAME
