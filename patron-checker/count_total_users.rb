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

unless API_KEY && !API_KEY.empty?
  puts 'Error: ALMA_API_KEY not found in environment variables'
  exit 1
end

puts '=' * 60
puts 'TOTAL USERS IN ALMA'
puts '=' * 60

url = URI("#{BASE_URL}/almaws/v1/users")
url.query = URI.encode_www_form({
  limit: 1,
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
    total = data['total_record_count'] || 0
    
    puts "\n✅ Total users in Alma: #{total.to_s.reverse.gsub(/(\d{3})(?=\d)/, '\\1,').reverse}"
  else
    puts "\n❌ Error: #{response.code} - #{response.body}"
  end
rescue StandardError => e
  puts "\n❌ Exception: #{e.message}"
end

puts '=' * 60
