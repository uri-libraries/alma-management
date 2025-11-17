#!/usr/bin/env ruby
require 'optparse'
require 'net/http'
require 'json'
require 'uri'
require 'csv'
require 'time'
require 'openssl'

SCRIPT_VERSION = '1.0.0'
SCRIPT_NAME = 'Patron Group Identifier Gatherer'

DEFAULT_GROUPS = [
  'AdHoc',
  'HELINUndergraduate',
  'Internal',
  'Visiting Faculty',
  'HighSchool'
].freeze

class EnvironmentError < StandardError; end

def print_header
  separator = '═' * 80
  puts separator
  puts "  #{SCRIPT_NAME}".ljust(78)
  puts separator
  puts "Version #{SCRIPT_VERSION}\n"
end

def print_section(title)
  puts "\n#{title}"
  puts '─' * title.length
end

def resolve_group_code(group)
  return group if group.nil? || group.strip.empty?

  normalized = group.strip
  explicit_map = {
    'Visiting Faculty' => 'VisitingFaculty',
    'High School' => 'HighSchool'
  }

  return explicit_map[normalized] if explicit_map.key?(normalized)

  return normalized.delete(' ') if normalized.match?('\s')

  normalized
end

def load_env_file(path)
  unless File.exist?(path)
    raise EnvironmentError, "Environment file not found: #{path}"
  end

  File.readlines(path).each do |line|
    next if line.strip.empty? || line.strip.start_with?('#')

    if (match = line.match(/^([^=\s]+)=(.*)$/))
      key = match[1].strip
      value = match[2].strip
      value = value.gsub(/\A["']|["']\z/, '')
      ENV[key] = value
    end
  end

  puts "Loaded environment configuration from #{File.basename(path)}"
end

def determine_env_file(option)
  return '.env.sandbox' if option == 'SANDBOX'
  return '.env' if option == 'PRODUCTION'

  env_setting = ENV['ALMA_ENV']&.upcase
  env_setting == 'SANDBOX' ? '.env.sandbox' : '.env'
end

def build_config(options)
  env_file = determine_env_file(options[:environment])
  env_path = File.expand_path(env_file, __dir__)
  load_env_file(env_path)

  api_key = ENV['ALMA_API_KEY']
  base_url = ENV['ALMA_API_BASE_URL']

  raise EnvironmentError, 'ALMA_API_KEY not set in the environment' if api_key.nil? || api_key.strip.empty?
  raise EnvironmentError, 'ALMA_API_BASE_URL not set in the environment' if base_url.nil? || base_url.strip.empty?

  {
    api_key: api_key.strip,
    base_url: base_url.strip.chomp('/'),
    headers: {
      'Accept' => 'application/json',
      'Authorization' => "apikey #{api_key.strip}",
      'User-Agent' => "Ruby-#{SCRIPT_NAME}/#{SCRIPT_VERSION}"
    }
  }
end

def build_request_uri(base_url, endpoint, params = nil)
  endpoint_path = endpoint.start_with?('/') ? endpoint : "/#{endpoint}"
  combined = "#{base_url}/almaws/v1#{endpoint_path}"
  combined = combined.gsub(%r{(?<!:)/{2,}}, '/')
  uri = URI(combined)
  uri.query = URI.encode_www_form(params) if params && !params.empty?
  uri
end

def call_alma_api(endpoint, params, config)
  max_attempts = 3
  attempt = 0
  response = nil

  begin
    attempt += 1
    uri = build_request_uri(config[:base_url], endpoint, params)
    request = Net::HTTP::Get.new(uri)
    config[:headers].each { |key, value| request[key] = value }

    http = Net::HTTP.new(uri.hostname, uri.port)
    http.use_ssl = uri.scheme == 'https'
    configure_ssl(http)
    http.read_timeout = 60
    response = http.start do |started|
      started.request(request)
    end

    case response.code.to_i
    when 200..399
      sleep 0.25
      return JSON.parse(response.body || '{}')
    when 429
      raise "Request throttled (429)"
    else
      raise "Alma API request failed: #{response.code} #{response.message}"
    end
  rescue => e
    if attempt < max_attempts && (response_code = response&.code&.to_i)
      if response_code == 429
        sleep(2**attempt * 0.5)
        retry
      elsif response_code >= 500
        sleep 1 + attempt
        retry
      end
    end
    raise
  end
end

def configure_ssl(http)
  ca_file = ENV['SSL_CERT_FILE'] || ENV['CURL_CA_BUNDLE']
  ca_path = ENV['SSL_CERT_DIR']
  http.ca_file = ca_file if ca_file && !ca_file.strip.empty?
  http.ca_path = ca_path if ca_path && !ca_path.strip.empty?

  if ENV['ALMA_SSL_ALLOW_INSECURE']&.match?(/\A(1|true|yes)\z/i)
    http.verify_mode = OpenSSL::SSL::VERIFY_NONE
  else
    http.verify_mode = OpenSSL::SSL::VERIFY_PEER
  end
end

def fetch_users_by_group(group_code, config)
  print_section("Querying group: #{group_code}")
  results = []
  limit = 100
  offset = 0

  loop do
  print "  → Fetching offset #{offset}\r"
  STDOUT.flush
    query_value = if group_code.match?('\s')
      escaped = group_code.gsub('"', '\\"')
      %(user_group~"#{escaped}")
    else
      "user_group~#{group_code}"
    end

    params = {
      'q' => query_value,
      'limit' => limit,
      'offset' => offset,
      'view' => 'brief',
      'expand' => 'none',
      'status' => 'ALL',
      'format' => 'json'
    }

    response = call_alma_api('/users', params, config)
    users = extract_users(response)
    break if users.empty?

    results.concat(users)
    offset += limit

    total = extract_total(response)
    break if total == 0 && users.size < limit
    break if total > 0 && offset >= total
  end

  puts "\nFetched #{results.size} patrons for group #{group_code}"
  results
end

def extract_users(response)
  if response['user']
    Array(response['user'])
  elsif response.dig('users', 'user')
    Array(response['users']['user'])
  else
    []
  end
end

def extract_total(response)
  if response['total_record_count']
    response['total_record_count'].to_i
  elsif response['total-record-count']
    response['total-record-count'].to_i
  else
    0
  end
end

def select_primary_identifier(user)
  return user['primary_id'] if user['primary_id']
  return user['primary-id'] if user['primary-id']

  identifier_nodes = Array(user.dig('identifiers', 'identifier')).flatten.compact
  return nil if identifier_nodes.empty?

  primary = identifier_nodes.find do |identifier|
    type_value = identifier.dig('type', 'value')
    id_type_value = identifier.dig('id_type', 'value')
    value = identifier['value']
    next false unless value
    %w[PRIMARY 01].include?(type_value) || %w[PRIMARY 01].include?(id_type_value)
  end

  candidate = primary || identifier_nodes.first
  candidate['value'] if candidate
end

def status_value(user)
  status = user['status']
  if status.is_a?(Hash)
    status['value'] || status['@value']
  else
    status
  end
end

print_header
options = {}
OptionParser.new do |opts|
  opts.banner = "Usage: #{File.basename($PROGRAM_NAME)} [options]"
  opts.on('-e ENVIRONMENT', '--environment ENVIRONMENT', ['SANDBOX', 'PRODUCTION'], 'SANDBOX or PRODUCTION') do |env|
    options[:environment] = env
  end
  opts.on('-h', '--help', 'Show this help message') do
    puts opts
    exit
  end
end.parse!

begin
  config = build_config(options)
rescue EnvironmentError => e
  warn e.message
  exit 1
end

rows = []
DEFAULT_GROUPS.each do |group|
  resolved = resolve_group_code(group)
  puts "Resolving group '#{group}' to '#{resolved}'" if resolved != group
  users = fetch_users_by_group(resolved, config)

  users.each do |user|
    primary_id = select_primary_identifier(user)
    rows << {
      PatronGroup: group,
      PrimaryId: primary_id,
      FullName: user['full_name'],
      FirstName: user['first_name'],
      LastName: user['last_name'],
      PreferredName: user['preferred_name'],
      Status: status_value(user)
    }
  end
end

if rows.empty?
  warn "No patron identifiers were retrieved. Please verify the patron groups and API filters."
  exit 1
end

timestamp = Time.now.strftime('%Y%m%d_%H%M%S')
output_file = File.join(__dir__, "PatronIdentifiers_#{timestamp}.csv")
CSV.open(output_file, 'w', write_headers: true, headers: rows.first.keys.map(&:to_s)) do |csv|
  rows.sort_by { |row| [row[:PatronGroup], row[:PrimaryId] || ''] }.each do |row|
    csv << row.values
  end
end
puts "\n✅ Identifiers exported to #{output_file}"
