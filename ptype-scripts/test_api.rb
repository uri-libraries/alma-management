require 'net/http'
require 'uri'
require 'json'
require 'openssl'

load_dotenv = lambda do
  File.readlines('.env').each do |line|
    next if line.strip.empty? || line.strip.start_with?('#')
    if (match = line.match(/^([^=\s]+)=(.*)$/))
      key = match[1].strip
      value = match[2].strip.gsub(/\A["']|["']\z/, '')
      ENV[key] = value
    end
  end
end

load_dotenv.call

API_KEY = ENV['ALMA_API_KEY']
BASE_URL = ENV['ALMA_API_BASE_URL']

uri = URI("#{BASE_URL}/almaws/v1/users?q=user_group~Undergraduate&limit=1&apikey=#{API_KEY}")
http = Net::HTTP.new(uri.hostname, uri.port)
http.use_ssl = true
http.verify_mode = OpenSSL::SSL::VERIFY_NONE

response = http.get(uri.request_uri, { 'Accept' => 'application/json' })
puts "Status: #{response.code}"
puts "Body: #{response.body[0..500]}"
