#!/usr/bin/env ruby
# frozen_string_literal: true

require 'net/http'
require 'uri'
require 'json'
require 'csv'
require 'optparse'
require 'time'
require 'openssl'

SCRIPT_NAME = 'Alma Patron Type Analyzer'
VERSION = '1.0.0'

# Load environment variables manually (to avoid dotenv dependency)
def load_env_file(path = '.env')
  return unless File.exist?(path)

  File.readlines(path).each do |line|
    next if line.strip.empty? || line.strip.start_with?('#')

    if (match = line.match(/^([^=\s]+)=(.*)$/))
      key = match[1].strip
      value = match[2].strip.gsub(/\A["']|["']\z/, '')
      ENV[key] = value
    end
  end
end

load_env_file

API_KEY = ENV['ALMA_API_KEY']
BASE_URL = ENV['ALMA_API_BASE_URL']&.chomp('/')

unless API_KEY && BASE_URL
  warn 'Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in .env'
  exit 1
end

class AlmaPatronTypeAnalyzer
  HEADERS = {
    'Authorization' => "apikey #{API_KEY}",
    'Accept' => 'application/json',
    'User-Agent' => "Ruby-#{SCRIPT_NAME}/#{VERSION}"
  }.freeze

  REQUEST_DELAY = 0.2

  def initialize
    @base_url = BASE_URL
    @api_key = API_KEY
  end

  def configure_ssl(http)
    # Disable SSL verification to avoid certificate issues
    http.verify_mode = OpenSSL::SSL::VERIFY_NONE
  end

  def call_alma_api(endpoint, params = {}, suppress_errors: false)
    # Build params with apikey
    query_params = params.merge(apikey: @api_key)
    
    # Construct URI - ensure endpoint starts with /
    endpoint = "/#{endpoint}" unless endpoint.start_with?('/')
    full_path = "#{@base_url}/almaws/v1#{endpoint}"
    uri = URI(full_path)
    uri.query = URI.encode_www_form(query_params)
    
    puts "DEBUG: #{uri}" if ENV['DEBUG']

    http = Net::HTTP.new(uri.hostname, uri.port)
    http.use_ssl = uri.scheme == 'https'
    configure_ssl(http)
    http.read_timeout = 60

    response = http.start do |connection|
      request = Net::HTTP::Get.new(uri)
      HEADERS.each { |key, value| request[key] = value }
      connection.request(request)
    end

    sleep REQUEST_DELAY

    case response.code.to_i
    when 200..399
      JSON.parse(response.body || '{}')
    else
      unless suppress_errors
        warn "API Error for #{endpoint}: #{response.code} #{response.message}"
        warn "Response: #{response.body[0..200]}" if response.body && ENV['DEBUG']
      end
      nil
    end
  rescue => e
    unless suppress_errors
      warn "API Error for #{endpoint}: #{e.message}"
      warn e.backtrace.first if ENV['DEBUG']
    end
    nil
  end

  def get_all_patron_types
    puts 'Loading patron types from types.csv...'
    
    patron_types = []
    
    begin
      CSV.foreach('types.csv', headers: true, encoding: 'utf-8') do |row|
        patron_types << {
          'value' => row['Code'] || '',
          'desc' => row['Description'] || ''
        }
      end
    rescue Errno::ENOENT
      warn '❌ types.csv not found in this directory'
      return []
    rescue => e
      warn "❌ Error reading types.csv: #{e.message}"
      return []
    end

    puts "✅ Found #{patron_types.size} patron types"
    patron_types
  end

  def get_patron_count_for_type(patron_type_code)
    params = { q: "user_group~#{patron_type_code}", limit: 1 }
    response = call_alma_api('/users', params, suppress_errors: false)

    if response.nil?
      warn "  ⚠️  No response for #{patron_type_code}" if ENV['DEBUG']
      return 0
    end

    count = response.dig('total_record_count') || 0
    puts "  #{patron_type_code}: #{count} patrons" if ENV['DEBUG']
    count
  end

  def identify_sis_patron_types(patron_types)
    puts 'Analyzing patron types for SIS/automatic import indicators...'

    sis_indicators = %w[
      student undergraduate graduate faculty staff employee
      ug_ grad_ phd_ ms_ ma_ bs_ ba_
      full_time part_time ft_ pt_
      active inactive continuing new
      freshman sophomore junior senior
      adjunct tenure emeritus
    ]

    manual_indicators = %w[
      guest visitor temp external community
      special courtesy honorary emeritus
      ill interlibrary reciprocal consortial
    ]

    categorized = {
      'likely_sis' => [],
      'likely_manual' => [],
      'uncertain' => [],
      'empty' => []
    }

    patron_types.each do |pt|
      code = pt['value'].downcase
      desc = pt['desc'].downcase
      combined_text = "#{code} #{desc}"

      sis_score = sis_indicators.count { |indicator| combined_text.include?(indicator) }
      manual_score = manual_indicators.count { |indicator| combined_text.include?(indicator) }

      patron_count = get_patron_count_for_type(pt['value'])

      pt_info = {
        'code' => pt['value'],
        'description' => pt['desc'],
        'patron_count' => patron_count,
        'sis_score' => sis_score,
        'manual_score' => manual_score
      }

      if patron_count.zero?
        categorized['empty'] << pt_info
      elsif sis_score > manual_score && sis_score.positive?
        categorized['likely_sis'] << pt_info
      elsif manual_score > sis_score && manual_score.positive?
        categorized['likely_manual'] << pt_info
      else
        categorized['uncertain'] << pt_info
      end
    end

    categorized.each_value { |list| list.sort_by! { |pt| -pt['patron_count'] } }
    categorized
  end

  def generate_comprehensive_report(output_file = nil)
    puts '🔍 Generating comprehensive patron type analysis...'

    patron_types = get_all_patron_types
    return '❌ Failed to retrieve patron types' if patron_types.empty?

    categorized = identify_sis_patron_types(patron_types)

    total_patrons = categorized.values.flatten.sum { |pt| pt['patron_count'] }
    total_sis = categorized['likely_sis'].sum { |pt| pt['patron_count'] }
    total_manual = categorized['likely_manual'].sum { |pt| pt['patron_count'] }
    total_uncertain = categorized['uncertain'].sum { |pt| pt['patron_count'] }

    timestamp = Time.now.strftime('%Y-%m-%d %H:%M:%S')

    report = []
    report << '=' * 80
    report << '                    ALMA PATRON TYPE ANALYSIS REPORT'.center(80)
    report << '=' * 80
    report << "Generated: #{timestamp}"
    report << "Total Patron Types: #{patron_types.size}"
    report << "Total Patrons: #{total_patrons.to_s.reverse.gsub(/(\d{3})(?=\d)/, '\\1,').reverse}"
    report << '=' * 80
    report << ''
    report << '📊 SUMMARY BY CATEGORY'
    report << '─' * 40

    pct = ->(count) { total_patrons.zero? ? 0.0 : (count.to_f / total_patrons * 100) }
    report << format('Likely SIS/Automatic:     %2d types, %6s patrons (%.1f%%)',
                     categorized['likely_sis'].size,
                     total_sis.to_s.reverse.gsub(/(\d{3})(?=\d)/, '\\1,').reverse,
                     pct.call(total_sis))
    report << format('Likely Manual/Special:    %2d types, %6s patrons (%.1f%%)',
                     categorized['likely_manual'].size,
                     total_manual.to_s.reverse.gsub(/(\d{3})(?=\d)/, '\\1,').reverse,
                     pct.call(total_manual))
    report << format('Uncertain Classification: %2d types, %6s patrons (%.1f%%)',
                     categorized['uncertain'].size,
                     total_uncertain.to_s.reverse.gsub(/(\d{3})(?=\d)/, '\\1,').reverse,
                     pct.call(total_uncertain))
    report << format('Empty (No Patrons):       %2d types, %6s patrons (0.0%%)',
                     categorized['empty'].size, '0')
    report << ''

    sections = [
      ['🎓 LIKELY SIS/AUTOMATIC PATRON TYPES', categorized['likely_sis']],
      ['👤 LIKELY MANUAL/SPECIAL PATRON TYPES', categorized['likely_manual']],
      ['❓ UNCERTAIN CLASSIFICATION', categorized['uncertain']],
      ['🚫 EMPTY PATRON TYPES', categorized['empty']]
    ]

    sections.each do |title, data|
      next if data.empty?

      report << title
      report << '─' * 80
      report << format('%-20s | %-8s | %-45s', 'Code', 'Count', 'Description')
      report << '─' * 80

      data.each do |pt|
        code = pt['code'][0, 19]
        count = pt['patron_count'].to_s.reverse.gsub(/(\d{3})(?=\d)/, '\\1,').reverse
        desc = pt['description'][0, 44]
        report << format('%-20s | %-8s | %-45s', code, count, desc)
      end

      report << ''
    end

    report << '💡 RECOMMENDATIONS'
    report << '─' * 40
    report << "• Consider removing #{categorized['empty'].size} unused patron types" unless categorized['empty'].empty?

    small_types = categorized.values.flatten.select { |pt| pt['patron_count'].between?(1, 9) }
    report << "• Review #{small_types.size} patron types with very few users (<10)" unless small_types.empty?

    large_types = categorized.values.flatten.select { |pt| pt['patron_count'] > 1000 }
    report << "• Monitor #{large_types.size} large patron types (>1000 users) for potential subdivision" unless large_types.empty?

    report << "• Review #{categorized['uncertain'].size} uncertain patron types for proper classification" unless categorized['uncertain'].empty?

    report << ''
    report << 'Note: SIS/Automatic classification is based on naming patterns and may require manual review.'
    report << '=' * 80

    if output_file
      csv_data = []
      [
        ['Likely SIS/Automatic', categorized['likely_sis']],
        ['Likely Manual/Special', categorized['likely_manual']],
        ['Uncertain', categorized['uncertain']],
        ['Empty', categorized['empty']]
      ].each do |category_name, data|
        data.each do |pt|
          csv_data << {
            'Category' => category_name,
            'Code' => pt['code'],
            'Description' => pt['description'],
            'Patron Count' => pt['patron_count'],
            'SIS Score' => pt['sis_score'],
            'Manual Score' => pt['manual_score']
          }
        end
      end

      CSV.open(output_file, 'w', write_headers: true, headers: csv_data.first.keys) do |csv|
        csv_data.each { |row| csv << row.values }
      end

      puts "📄 Detailed data saved to: #{output_file}"
    end

    report.join("\n")
  end

  def get_patron_details_by_type(patron_type_code, sample_size = 5)
    puts "🔍 Analyzing patron type: #{patron_type_code}"

    total_count = get_patron_count_for_type(patron_type_code)

    if total_count.zero?
      return {
        'code' => patron_type_code,
        'total_count' => 0,
        'sample_users' => [],
        'analysis' => 'No patrons found with this type'
      }
    end

    params = {
      q: "user_group~#{patron_type_code}",
      limit: [sample_size, total_count].min
    }

    response = call_alma_api('/users', params)
    sample_users = []

    if response && response['user']
      Array(response['user']).each do |user|
        email_list = user.dig('contact_info', 'email') || []
        email = email_list.first&.dig('email_address') || ''

        sample_users << {
          'primary_id' => user['primary_id'] || '',
          'first_name' => user['first_name'] || '',
          'last_name' => user['last_name'] || '',
          'email' => email,
          'status' => user.dig('status', 'value') || '',
          'created_date' => user['created_date'] || ''
        }
      end
    end

    {
      'code' => patron_type_code,
      'total_count' => total_count,
      'sample_users' => sample_users,
      'analysis' => "Found #{total_count} patrons, showing #{sample_users.size} samples"
    }
  end

  def list_patron_types
    patron_types = get_all_patron_types
    return if patron_types.empty?

    puts format("\n%-20s | %-8s | %s", 'Code', 'Count', 'Description')
    puts '─' * 60

    patron_types.each do |pt|
      code = pt['value']
      desc = pt['desc']
      count = get_patron_count_for_type(code)
      formatted_count = count.to_s.reverse.gsub(/(\d{3})(?=\d)/, '\\1,').reverse
      puts format('%-20s | %-8s | %s', code, formatted_count, desc)
    end
  end

  def inspect_patron_type(patron_type_code, sample_size)
    details = get_patron_details_by_type(patron_type_code, sample_size)

    puts "\n🔍 PATRON TYPE DETAILS: #{details['code']}"
    puts '=' * 60
    puts "Total Patrons: #{details['total_count'].to_s.reverse.gsub(/(\d{3})(?=\d)/, '\\1,').reverse}"
    puts "Analysis: #{details['analysis']}"

    if details['sample_users'].any?
      puts "\nSample Users (showing #{details['sample_users'].size}):"
      puts '─' * 60
      details['sample_users'].each do |user|
        name = "#{user['first_name']} #{user['last_name']}"
        puts "• #{name} (#{user['primary_id']}) - #{user['email']}"
        puts "  Status: #{user['status']}, Created: #{user['created_date']}"
      end
    end
  end
end

def main
  options = {}
  command = nil

  # Extract command before parsing options
  if ARGV.first && !ARGV.first.start_with?('-')
    command = ARGV.shift
  end

  parser = OptionParser.new do |opts|
    opts.banner = "Usage: #{File.basename($PROGRAM_NAME)} COMMAND [OPTIONS]"
    opts.separator ''
    opts.separator 'Commands:'
    opts.separator '  analyze              Run comprehensive patron type analysis'
    opts.separator '  list                 List all patron types with counts'
    opts.separator '  inspect TYPE         Inspect specific patron type'
    opts.separator '  export FILE          Export all patron type data to CSV'
    opts.separator ''
    opts.separator 'Options:'

    opts.on('-o', '--output FILE', 'Output CSV file (for analyze command)') do |file|
      options[:output] = file
    end

    opts.on('-s', '--samples N', Integer, 'Number of sample users (for inspect command, default: 5)') do |n|
      options[:samples] = n
    end

    opts.on('-h', '--help', 'Show this help message') do
      puts opts
      exit
    end
  end

  parser.parse!

  unless command
    puts parser
    exit 1
  end

  begin
    analyzer = AlmaPatronTypeAnalyzer.new

    case command
    when 'analyze'
      report = analyzer.generate_comprehensive_report(options[:output])
      puts report

    when 'list'
      analyzer.list_patron_types

    when 'inspect'
      patron_type = ARGV.shift
      unless patron_type
        warn 'Error: Please specify a patron type code'
        exit 1
      end
      analyzer.inspect_patron_type(patron_type, options[:samples] || 5)

    when 'export'
      output_file = ARGV.shift
      unless output_file
        warn 'Error: Please specify an output file'
        exit 1
      end
      puts 'Exporting all patron type data...'
      analyzer.generate_comprehensive_report(output_file)
      puts '✅ Export completed!'

    else
      warn "Unknown command: #{command}"
      puts parser
      exit 1
    end
  rescue => e
    warn "❌ Error: #{e.message}"
    exit 1
  end
end

main if $PROGRAM_NAME == __FILE__
