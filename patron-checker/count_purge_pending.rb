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

def count_users_in_group(group_name, sample_size: 100)
  puts "Fetching sample of #{sample_size} users to check actual group membership..."
  
  url = URI("#{BASE_URL}/almaws/v1/users")
  url.query = URI.encode_www_form({
    user_group: group_name,
    limit: sample_size,
    offset: 0
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
      
      puts "Checking actual user_group field for #{users.length} users..."
      
      actual_count = 0
      users.each_with_index do |user, idx|
        user_details = get_user_details(user['primary_id'])
        if user_details
          user_group_value = user_details.dig('user_group', 'value')
          if user_group_value == group_name
            actual_count += 1
          end
        end
        
        print "\rChecked #{idx + 1}/#{users.length} users..." if (idx + 1) % 10 == 0
        sleep(0.1) # Rate limiting
      end
      
      puts "\n\nOut of #{users.length} users returned by API:"
      puts "  - Actually in '#{group_name}': #{actual_count}"
      puts "  - In other groups: #{users.length - actual_count}"
      
      return actual_count
    else
      puts "Error: #{response.code} - #{response.body}"
      return nil
    end
  rescue StandardError => e
    puts "Exception: #{e.message}"
    return nil
  end
end

unless API_KEY && !API_KEY.empty?
  puts 'Error: ALMA_API_KEY not found in environment variables'
  exit 1
end

puts '=' * 60
puts 'ALMA USER GROUP COUNT'
puts '=' * 60

group_name = 'PurgePending'
puts "\nTesting group filter for: #{group_name}..."

count = count_users_in_group(group_name, sample_size: 100)

if count && count > 0
  puts "\n⚠️  The API's user_group filter appears broken."
  puts "Only #{count} out of 100 sampled users are actually in '#{group_name}'"
  puts "\n💡 To get accurate total, would need to check all users in your system."
elsif count == 0
  puts "\n⚠️  None of the returned users are actually in '#{group_name}'"
  puts "The API user_group parameter is not filtering correctly."
else
  puts "\n❌ Failed to verify group membership"
end

puts '=' * 60
