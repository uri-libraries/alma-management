#!/usr/bin/env ruby
# frozen_string_literal: true

require 'net/http'
require 'json'
require 'uri'
require 'dotenv/load'

#the point of this script is to analyze the safety of switching SIS import matching from Primary ID to UNIV_ID  
# Load environment variables
Dotenv.load

API_KEY = ENV['ALMA_API_KEY']
BASE_URL = ENV['ALMA_BASE_URL'] || 'https://api-na.hosted.exlibrisgroup.com/almaws/v1'

# Fetch detailed user information including identifiers
#
# Args:
#   user_id (String): The user ID to fetch
#
# Returns:
#   Hash: The user data, or nil if an error occurs
def get_user_details(user_id)
  url = URI("#{BASE_URL}/users/#{user_id}")
  
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
      puts "Error fetching user details for #{user_id}: #{response.code} - #{response.body}"
      nil
    end
  rescue StandardError => e
    puts "Error fetching user details for #{user_id}: #{e.message}"
    nil
  end
end

# Fetch all users from Alma API with pagination
#
# Args:
#   max_users (Integer, optional): Maximum number of users to fetch
#
# Returns:
#   Array: List of user hashes
def get_all_users(max_users = nil)
  users = []
  offset = 0
  limit = 100
  
  loop do
    url = URI("#{BASE_URL}/users")
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
        puts "Error fetching users: #{response.code} - #{response.body}"
        break
      end
      
      data = JSON.parse(response.body)
      
      break unless data.key?('user')
      
      batch_users = data['user']
      break if batch_users.empty?
      
      users.concat(batch_users)
      puts "Fetched #{users.length} users so far..."
      
      if max_users && users.length >= max_users
        users = users[0...max_users]
        puts "Reached limit of #{max_users} users"
        break
      end
      
      break if batch_users.length < limit
      
      offset += limit
      
    rescue StandardError => e
      puts "Error fetching users: #{e.message}"
      break
    end
  end
  
  users
end

# Extract all identifiers for a user
#
# Args:
#   user (Hash): User data from API
#   detailed_user (Hash, optional): Detailed user data if available
#
# Returns:
#   Hash: Extracted identifier information
def extract_user_identifiers(user, detailed_user = nil)
  user_data = detailed_user || user
  
  result = {
    'primary_id' => user['primary_id'],
    'univ_id' => nil,
    'ldap' => nil,
    'barcode' => nil,
    'other_ids' => [],
    'has_univ_id' => false,
    'identifiers' => []
  }
  
  # Get identifiers
  identifiers = user_data['user_identifier'] || []
  identifiers = [identifiers] if identifiers.is_a?(Hash)
  
  identifiers.each do |identifier|
    next unless identifier.is_a?(Hash)
    
    id_value = identifier['value'] || ''
    id_type_obj = identifier['id_type'] || {}
    
    id_type = if id_type_obj.is_a?(Hash)
                id_type_obj['value'] || 'Unknown'
              else
                id_type_obj
              end
    
    result['identifiers'] << {
      'value' => id_value,
      'type' => id_type
    }
    
    # Categorize by type
    case id_type
    when 'UNIV_ID'
      result['univ_id'] = id_value
      result['has_univ_id'] = true
    when 'LDAP'
      result['ldap'] = id_value
    when 'BARCODE', 'PRIMARY_ID'
      result['barcode'] = id_value
    else
      result['other_ids'] << { 'type' => id_type, 'value' => id_value }
    end
  end
  
  result
end

# Analyze the safety of switching from Primary ID to UNIV_ID matching
#
# Args:
#   users (Array): List of user hashes
#
# Returns:
#   Hash: Analysis results
def analyze_sis_matching_safety(users)
  puts "\nAnalyzing SIS matching safety for #{users.length} users..."
  
  # Data structures for analysis
  primary_to_univ = {}  # primary_id -> univ_id
  univ_to_primary = {}  # univ_id -> primary_id
  univ_id_counts = Hash.new(0)  # Count occurrences of each univ_id
  
  # User categories
  users_with_both = 0
  users_with_primary_only = 0
  users_with_univ_only = 0
  users_with_neither = 0
  
  # Potential issues
  duplicate_univ_ids = []
  orphaned_users = []
  sample_mappings = []
  
  users.each_with_index do |user, i|
    # Extract identifiers
    user_identifiers = extract_user_identifiers(user)
    
    primary_id = user_identifiers['primary_id']
    univ_id = user_identifiers['univ_id']
    
    # Save sample mappings for display
    if sample_mappings.length < 10
      sample_mappings << {
        'primary_id' => primary_id,
        'univ_id' => univ_id,
        'ldap' => user_identifiers['ldap'],
        'other_ids' => user_identifiers['other_ids'].length
      }
    end
    
    # Categorize users
    has_primary = !primary_id.nil?
    has_univ = !univ_id.nil?
    
    if has_primary && has_univ
      users_with_both += 1
      
      # Track mappings
      primary_to_univ[primary_id] = univ_id
      univ_id_counts[univ_id] += 1
      
      # Check for conflicts
      if univ_to_primary.key?(univ_id) && univ_to_primary[univ_id] != primary_id
        duplicate_univ_ids << {
          'univ_id' => univ_id,
          'primary_ids' => [univ_to_primary[univ_id], primary_id]
        }
      else
        univ_to_primary[univ_id] = primary_id
      end
      
    elsif has_primary && !has_univ
      users_with_primary_only += 1
      orphaned_users << {
        'primary_id' => primary_id,
        'ldap' => user_identifiers['ldap'],
        'other_ids' => user_identifiers['other_ids']
      }
    elsif !has_primary && has_univ
      users_with_univ_only += 1
    else
      users_with_neither += 1
    end
    
    # Progress indicator
    puts "Processed #{i + 1}/#{users.length} users..." if ((i + 1) % 100).zero?
  end
  
  # Analysis results
  total_users = users.length
  migration_safety = {
    'safe_to_migrate' => true,
    'risk_level' => 'LOW',
    'issues' => []
  }
  
  # Check for issues
  if users_with_primary_only > 0
    migration_safety['safe_to_migrate'] = false
    migration_safety['risk_level'] = 'HIGH'
    migration_safety['issues'] << "#{users_with_primary_only} users would be orphaned (have Primary ID but no UNIV_ID)"
  end
  
  if duplicate_univ_ids.any?
    migration_safety['safe_to_migrate'] = false
    migration_safety['risk_level'] = 'HIGH'
    migration_safety['issues'] << "#{duplicate_univ_ids.length} UNIV_IDs map to multiple Primary IDs"
  end
  
  if users_with_univ_only > 0
    migration_safety['issues'] << "#{users_with_univ_only} users have UNIV_ID but no Primary ID (unusual but not blocking)"
  end
  
  if users_with_both < total_users * 0.95  # Less than 95% have both
    migration_safety['risk_level'] = 'MEDIUM'
    migration_safety['issues'] << 'Less than 95% of users have both identifiers'
  end
  
  # Sort univ_id_counts by count descending
  sorted_counts = univ_id_counts.sort_by { |_k, v| -v }.first(10).to_h
  
  {
    'total_users' => total_users,
    'users_with_both' => users_with_both,
    'users_with_primary_only' => users_with_primary_only,
    'users_with_univ_only' => users_with_univ_only,
    'users_with_neither' => users_with_neither,
    'duplicate_univ_ids' => duplicate_univ_ids,
    'orphaned_users' => orphaned_users,
    'sample_mappings' => sample_mappings,
    'migration_safety' => migration_safety,
    'primary_to_univ' => primary_to_univ.first(10).to_h,
    'univ_id_counts' => sorted_counts
  }
end

# Print detailed analysis report
#
# Args:
#   analysis (Hash): Analysis results from analyze_sis_matching_safety
def print_analysis_report(analysis)
  puts "\n#{'=' * 70}"
  puts 'SIS IMPORT MATCHING ANALYSIS REPORT'
  puts '=' * 70
  
  total = analysis['total_users']
  
  puts "\nUSER IDENTIFIER DISTRIBUTION:"
  puts format('%-30s %-10s %s', 'Category', 'Count', 'Percentage')
  puts '-' * 50
  puts format('%-30s %-10d %.1f%%', 'Users with both Primary & UNIV ID', analysis['users_with_both'], analysis['users_with_both'].to_f / total * 100)
  puts format('%-30s %-10d %.1f%%', 'Users with Primary ID only', analysis['users_with_primary_only'], analysis['users_with_primary_only'].to_f / total * 100)
  puts format('%-30s %-10d %.1f%%', 'Users with UNIV ID only', analysis['users_with_univ_only'], analysis['users_with_univ_only'].to_f / total * 100)
  puts format('%-30s %-10d %.1f%%', 'Users with neither', analysis['users_with_neither'], analysis['users_with_neither'].to_f / total * 100)
  
  puts "\nMIGRATION SAFETY ASSESSMENT:"
  puts '-' * 50
  safety = analysis['migration_safety']
  puts "Safe to migrate: #{safety['safe_to_migrate']}"
  puts "Risk level: #{safety['risk_level']}"
  
  if safety['issues'].any?
    puts "\nISSUES IDENTIFIED:"
    safety['issues'].each do |issue|
      puts "⚠️  #{issue}"
    end
  end
  
  if analysis['duplicate_univ_ids'].any?
    puts "\nDUPLICATE UNIV_ID CONFLICTS:"
    analysis['duplicate_univ_ids'].first(5).each do |dup|
      puts "   UNIV_ID '#{dup['univ_id']}' -> Primary IDs: #{dup['primary_ids']}"
    end
  end
  
  if analysis['orphaned_users'].any?
    puts "\nORPHANED USERS (Primary ID but no UNIV_ID): #{analysis['orphaned_users'].length} total"
    puts 'First 10 examples:'
    analysis['orphaned_users'].first(10).each do |user|
      ldap_display = user['ldap'] || 'None'
      other_count = user['other_ids'].length
      puts "   #{user['primary_id']} (LDAP: #{ldap_display}, Other IDs: #{other_count})"
    end
  end
  
  puts "\nSAMPLE ID MAPPINGS:"
  puts format('%-15s %-15s %-20s %s', 'Primary ID', 'UNIV ID', 'LDAP', 'Other IDs')
  puts '-' * 65
  analysis['sample_mappings'].each do |mapping|
    univ_display = mapping['univ_id'] || 'None'
    ldap_display = mapping['ldap'] || 'None'
    puts format('%-15s %-15s %-20s %d', mapping['primary_id'], univ_display, ldap_display, mapping['other_ids'])
  end
  
  puts "\nRECOMMENDATION:"
  puts '-' * 50
  if safety['safe_to_migrate']
    puts '✅ SAFE to switch SIS import matching from Primary ID to UNIV_ID'
    puts '   • All users have consistent identifier mapping'
    puts '   • No risk of creating duplicate users'
    puts '   • This will solve your barcode mismatch issues'
  else
    puts '❌ NOT SAFE to switch without addressing issues first'
    puts '   • Fix the issues identified above before migrating'
    puts '   • Consider data cleanup or alternative approaches'
  end
end

# Save detailed analysis to JSON file
#
# Args:
#   analysis (Hash): Analysis results to save
def save_detailed_report(analysis)
  File.write('sis_matching_analysis.json', JSON.pretty_generate(analysis))
  puts "\nDetailed analysis saved to: sis_matching_analysis.json"
end

# Main function
def main
  unless API_KEY
    puts 'Error: ALMA_API_KEY not found in environment variables'
    return
  end
  
  puts 'Starting SIS Import Matching Analysis...'
  puts 'This will analyze the safety of switching from Primary ID to UNIV_ID matching'
  
  # Fetch all users for complete analysis
  users = get_all_users  # No limit - get all users
  
  if users.empty?
    puts 'No users found or error fetching users'
    return
  end
  
  # Analyze matching safety
  analysis = analyze_sis_matching_safety(users)
  
  # Print report
  print_analysis_report(analysis)
  
  # Save detailed report
  save_detailed_report(analysis)
end

# Run main function if script is executed directly
main if __FILE__ == $PROGRAM_NAME
