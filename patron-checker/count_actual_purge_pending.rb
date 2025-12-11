#!/usr/bin/env ruby
# frozen_string_literal: true

require 'net/http'
require 'json'
require 'uri'
require 'dotenv'

# Load environment
if File.exist?('.env')
  Dotenv.load('.env')
elsif File.exist?('../.env')
  Dotenv.load('../.env')
else
  puts 'Error: .env file not found'
  exit 1
end

API_KEY = ENV['ALMA_API_KEY']
BASE_URL = ENV['ALMA_API_BASE_URL'] || 'https://api-na.hosted.exlibrisgroup.com'

def get_user_details(user_id)
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
      nil
    end
  rescue StandardError
    nil
  end
end

def get_all_user_ids
  all_ids = []
  offset = 0
  limit = 100
  
  loop do
    url = URI("#{BASE_URL}/almaws/v1/users")
    url.query = URI.encode_www_form({
      limit: limit,
      offset: offset
    })
    
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
        data = JSON.parse(response.body)
        users = data['user'] || []
        break if users.empty?
        
        users.each { |u| all_ids << u['primary_id'] if u['primary_id'] }
        
        total = data['total_record_count'] || 0
        puts "Fetched #{all_ids.length}/#{total} user IDs..."
        
        break if all_ids.length >= total
        offset += limit
        sleep(0.2)
      else
        puts "Error fetching users: #{response.code}"
        break
      end
    rescue StandardError => e
      puts "Exception: #{e.message}"
      break
    end
  end
  
  all_ids
end

unless API_KEY && !API_KEY.empty?
  puts 'Error: ALMA_API_KEY not found in environment variables'
  exit 1
end

puts '=' * 60
puts 'COUNT USERS IN PURGEPENDING GROUP (FROM ALMA)'
puts '=' * 60

puts "\nStep 1: Fetching all user IDs from Alma..."
ids = get_all_user_ids

puts "\nStep 2: Checking each user's actual group membership..."
puts "Total users to check: #{ids.length}\n"

purge_pending_count = 0
purge_pending_ids = []

ids.each_with_index do |user_id, idx|
  print "\rProcessed #{idx + 1}/#{ids.length} users (found #{purge_pending_count} in PurgePending)..." if (idx + 1) % 100 == 0
  
  sleep(0.1) # Rate limiting
  
  user = get_user_details(user_id)
  
  if user
    group_value = user.dig('user_group', 'value')
    
    if group_value == 'PurgePending'
      purge_pending_count += 1
      purge_pending_ids << user_id
    end
  end
end

puts "\n\n" + '=' * 60
puts 'RESULTS'
puts '=' * 60
puts "Total users in Alma: #{ids.length}"
puts "✅ Users actually in 'PurgePending': #{purge_pending_count}"

# Save the list
if purge_pending_count > 0
  File.write('actual_purge_pending_users.txt', purge_pending_ids.join("\n"))
  puts "\n📄 PurgePending user IDs saved to: actual_purge_pending_users.txt"
end

puts "\n" + '=' * 60
