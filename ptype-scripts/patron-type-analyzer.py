#!/usr/bin/env python3
"""
Alma Patron Type Analyzer

This script retrieves all patron types from Alma and provides detailed analysis including:
1. List of all patron types with descriptions
2. Identification of patron types created by SIS jobs or automatic imports
3. Count of patrons in each patron group
4. Analysis of patron type usage patterns

Author: Generated for alma-management project
"""

import requests
import json
import os
import csv
import time
from datetime import datetime
from dotenv import load_dotenv
from typing import List, Dict, Optional, Any
import argparse

# Load environment variables
load_dotenv()

# Configuration
ALMA_API_KEY = os.getenv('ALMA_API_KEY')
ALMA_API_BASE_URL = os.getenv('ALMA_API_BASE_URL')

class AlmaPatronTypeAnalyzer:
    def __init__(self, api_key: str = None, base_url: str = None):
        """Initialize the Patron Type Analyzer with API credentials."""
        self.api_key = api_key or ALMA_API_KEY
        self.base_url = base_url or ALMA_API_BASE_URL
        
        if not self.api_key or not self.base_url:
            raise ValueError("API credentials not found. Please set ALMA_API_KEY and ALMA_API_BASE_URL")
        
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'Authorization': f'apikey {self.api_key}'
        })
        
        # Rate limiting
        self.request_delay = 0.2  # Delay between API requests (in seconds)
        
    def call_alma_api(self, endpoint: str, params: dict = None, 
                     suppress_errors: bool = False) -> Optional[Dict[str, Any]]:
        """
        Makes a GET request to the Alma API.
        
        Args:
            endpoint: API endpoint (e.g., "/users")
            params: Query parameters
            suppress_errors: Whether to suppress error output
            
        Returns:
            JSON response or None if error
        """
        url = f"{self.base_url}/almaws/v1{endpoint}"
        
        if params is None:
            params = {}
        params['apikey'] = self.api_key
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            # Add delay for rate limiting
            time.sleep(self.request_delay)
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            if not suppress_errors:
                print(f"API Error for {endpoint}: {e}")
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    print(f"Response: {e.response.text}")
            return None
    
    def get_all_patron_types(self) -> List[Dict[str, Any]]:
        """
        Retrieve all available patron types from Alma.
        
        Returns:
            List of patron type dictionaries with enhanced information
        """
        print("Fetching all patron types from Alma...")
        
        response = self.call_alma_api("/conf/user-groups")
        
        if not response or 'user_group' not in response:
            print("❌ Failed to retrieve patron types")
            return []
        
        patron_types = response['user_group']
        print(f"✅ Found {len(patron_types)} patron types")
        
        return patron_types
    
    def get_patron_count_for_type(self, patron_type_code: str) -> int:
        """
        Get the count of patrons for a specific patron type.
        
        Args:
            patron_type_code: The patron type code to count
            
        Returns:
            Number of patrons with this type
        """
        params = {
            'q': f'user_group~{patron_type_code}',
            'limit': 1  # We only need the count, not the actual users
        }
        
        response = self.call_alma_api("/users", params=params, suppress_errors=True)
        
        if response and 'total_record_count' in response:
            return response['total_record_count']
        
        return 0
    
    def identify_sis_patron_types(self, patron_types: List[Dict]) -> Dict[str, Any]:
        """
        Identify patron types that are likely created by SIS jobs or automatic imports.
        
        This uses heuristics based on common naming patterns and descriptions.
        
        Args:
            patron_types: List of patron type dictionaries
            
        Returns:
            Dictionary categorizing patron types
        """
        print("Analyzing patron types for SIS/automatic import indicators...")
        
        # Common patterns that indicate SIS/automatic creation
        sis_indicators = [
            'student', 'undergraduate', 'graduate', 'faculty', 'staff', 'employee',
            'ug_', 'grad_', 'phd_', 'ms_', 'ma_', 'bs_', 'ba_',
            'full_time', 'part_time', 'ft_', 'pt_',
            'active', 'inactive', 'continuing', 'new',
            'freshman', 'sophomore', 'junior', 'senior',
            'adjunct', 'tenure', 'emeritus'
        ]
        
        # Patterns that indicate manual/special purpose types
        manual_indicators = [
            'guest', 'visitor', 'temp', 'external', 'community',
            'special', 'courtesy', 'honorary', 'emeritus',
            'ill', 'interlibrary', 'reciprocal', 'consortial'
        ]
        
        categorized = {
            'likely_sis': [],
            'likely_manual': [],
            'uncertain': [],
            'empty': [],
            'analysis': {}
        }
        
        for pt in patron_types:
            code = pt.get('value', '').lower()
            desc = pt.get('desc', '').lower()
            combined_text = f"{code} {desc}"
            
            # Check for SIS indicators
            sis_score = sum(1 for indicator in sis_indicators if indicator in combined_text)
            manual_score = sum(1 for indicator in manual_indicators if indicator in combined_text)
            
            # Get patron count
            patron_count = self.get_patron_count_for_type(pt.get('value', ''))
            
            pt_info = {
                'code': pt.get('value', ''),
                'description': pt.get('desc', ''),
                'patron_count': patron_count,
                'sis_score': sis_score,
                'manual_score': manual_score
            }
            
            # Categorize based on scores and patterns
            if patron_count == 0:
                categorized['empty'].append(pt_info)
            elif sis_score > manual_score and sis_score > 0:
                categorized['likely_sis'].append(pt_info)
            elif manual_score > sis_score and manual_score > 0:
                categorized['likely_manual'].append(pt_info)
            else:
                categorized['uncertain'].append(pt_info)
        
        # Sort each category by patron count (descending)
        for category in ['likely_sis', 'likely_manual', 'uncertain', 'empty']:
            categorized[category].sort(key=lambda x: x['patron_count'], reverse=True)
        
        return categorized
    
    def generate_comprehensive_report(self, output_file: str = None) -> str:
        """
        Generate a comprehensive report of all patron types with analysis.
        
        Args:
            output_file: Optional CSV file to save detailed data
            
        Returns:
            String representation of the report
        """
        print("🔍 Generating comprehensive patron type analysis...")
        
        # Get all patron types
        patron_types = self.get_all_patron_types()
        
        if not patron_types:
            return "❌ Failed to retrieve patron types"
        
        # Analyze and categorize patron types
        categorized = self.identify_sis_patron_types(patron_types)
        
        # Calculate totals
        total_patrons = sum(pt['patron_count'] for category in 
                          ['likely_sis', 'likely_manual', 'uncertain', 'empty'] 
                          for pt in categorized[category])
        
        total_sis_patrons = sum(pt['patron_count'] for pt in categorized['likely_sis'])
        total_manual_patrons = sum(pt['patron_count'] for pt in categorized['likely_manual'])
        total_uncertain_patrons = sum(pt['patron_count'] for pt in categorized['uncertain'])
        
        # Generate report
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        report_lines = [
            "═" * 80,
            "                    ALMA PATRON TYPE ANALYSIS REPORT",
            "═" * 80,
            f"Generated: {timestamp}",
            f"Total Patron Types: {len(patron_types)}",
            f"Total Patrons: {total_patrons:,}",
            "═" * 80,
            "",
            "📊 SUMMARY BY CATEGORY",
            "─" * 40,
            f"Likely SIS/Automatic:     {len(categorized['likely_sis']):2d} types, {total_sis_patrons:6,d} patrons ({total_sis_patrons/total_patrons*100 if total_patrons > 0 else 0:.1f}%)",
            f"Likely Manual/Special:    {len(categorized['likely_manual']):2d} types, {total_manual_patrons:6,d} patrons ({total_manual_patrons/total_patrons*100 if total_patrons > 0 else 0:.1f}%)",
            f"Uncertain Classification: {len(categorized['uncertain']):2d} types, {total_uncertain_patrons:6,d} patrons ({total_uncertain_patrons/total_patrons*100 if total_patrons > 0 else 0:.1f}%)",
            f"Empty (No Patrons):       {len(categorized['empty']):2d} types, {0:6,d} patrons (0.0%)",
            "",
        ]
        
        # Add detailed sections
        sections = [
            ("🎓 LIKELY SIS/AUTOMATIC PATRON TYPES", categorized['likely_sis']),
            ("👤 LIKELY MANUAL/SPECIAL PATRON TYPES", categorized['likely_manual']),
            ("❓ UNCERTAIN CLASSIFICATION", categorized['uncertain']),
            ("🚫 EMPTY PATRON TYPES", categorized['empty'])
        ]
        
        for section_title, section_data in sections:
            if section_data:
                report_lines.extend([
                    section_title,
                    "─" * 80,
                    f"{'Code':<20} | {'Count':<8} | {'Description':<45}",
                    "─" * 80
                ])
                
                for pt in section_data:
                    code = pt['code'][:19]  # Truncate long codes
                    count = f"{pt['patron_count']:,}"
                    desc = pt['description'][:44]  # Truncate long descriptions
                    report_lines.append(f"{code:<20} | {count:<8} | {desc:<45}")
                
                report_lines.append("")
        
        # Add recommendations
        report_lines.extend([
            "💡 RECOMMENDATIONS",
            "─" * 40,
        ])
        
        if categorized['empty']:
            report_lines.append(f"• Consider removing {len(categorized['empty'])} unused patron types")
        
        small_types = [pt for category in categorized.values() 
                      for pt in category if 0 < pt['patron_count'] < 10]
        if small_types:
            report_lines.append(f"• Review {len(small_types)} patron types with very few users (<10)")
        
        large_types = [pt for category in categorized.values() 
                      for pt in category if pt['patron_count'] > 1000]
        if large_types:
            report_lines.append(f"• Monitor {len(large_types)} large patron types (>1000 users) for potential subdivision")
        
        if categorized['uncertain']:
            report_lines.append(f"• Review {len(categorized['uncertain'])} uncertain patron types for proper classification")
        
        report_lines.extend([
            "",
            "Note: SIS/Automatic classification is based on naming patterns and may require manual review.",
            "═" * 80
        ])
        
        report_string = "\n".join(report_lines)
        
        # Save detailed data to CSV if requested
        if output_file:
            csv_data = []
            for category_name, category_data in [
                ('Likely SIS/Automatic', categorized['likely_sis']),
                ('Likely Manual/Special', categorized['likely_manual']),
                ('Uncertain', categorized['uncertain']),
                ('Empty', categorized['empty'])
            ]:
                for pt in category_data:
                    csv_data.append({
                        'Category': category_name,
                        'Code': pt['code'],
                        'Description': pt['description'],
                        'Patron Count': pt['patron_count'],
                        'SIS Score': pt['sis_score'],
                        'Manual Score': pt['manual_score']
                    })
            
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                if csv_data:
                    writer = csv.DictWriter(f, fieldnames=csv_data[0].keys())
                    writer.writeheader()
                    writer.writerows(csv_data)
            
            print(f"📄 Detailed data saved to: {output_file}")
        
        return report_string
    
    def get_patron_details_by_type(self, patron_type_code: str, sample_size: int = 5) -> Dict[str, Any]:
        """
        Get sample patron details for a specific patron type.
        
        Args:
            patron_type_code: The patron type code to analyze
            sample_size: Number of sample patrons to retrieve
            
        Returns:
            Dictionary with patron type analysis and sample users
        """
        print(f"🔍 Analyzing patron type: {patron_type_code}")
        
        # Get basic count
        total_count = self.get_patron_count_for_type(patron_type_code)
        
        if total_count == 0:
            return {
                'code': patron_type_code,
                'total_count': 0,
                'sample_users': [],
                'analysis': 'No patrons found with this type'
            }
        
        # Get sample users
        params = {
            'q': f'user_group~{patron_type_code}',
            'limit': min(sample_size, total_count)
        }
        
        response = self.call_alma_api("/users", params=params)
        sample_users = []
        
        if response and 'user' in response:
            for user in response['user']:
                contact_info = user.get('contact_info', {})
                email_list = contact_info.get('email', [])
                email = email_list[0].get('email_address', '') if email_list else ''
                
                sample_users.append({
                    'primary_id': user.get('primary_id', ''),
                    'first_name': user.get('first_name', ''),
                    'last_name': user.get('last_name', ''),
                    'email': email,
                    'status': user.get('status', {}).get('value', ''),
                    'created_date': user.get('created_date', '')
                })
        
        return {
            'code': patron_type_code,
            'total_count': total_count,
            'sample_users': sample_users,
            'analysis': f'Found {total_count} patrons, showing {len(sample_users)} samples'
        }


def main():
    """Main function to run the patron type analyzer."""
    parser = argparse.ArgumentParser(description='Alma Patron Type Analyzer')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Full analysis command
    analysis_parser = subparsers.add_parser('analyze', help='Run comprehensive patron type analysis')
    analysis_parser.add_argument('--output', '-o', help='Output CSV file for detailed data')
    
    # List patron types command
    list_parser = subparsers.add_parser('list', help='List all patron types with counts')
    
    # Inspect specific patron type
    inspect_parser = subparsers.add_parser('inspect', help='Inspect specific patron type')
    inspect_parser.add_argument('patron_type', help='Patron type code to inspect')
    inspect_parser.add_argument('--samples', '-s', type=int, default=5, help='Number of sample users to show')
    
    # Export all data
    export_parser = subparsers.add_parser('export', help='Export all patron type data to CSV')
    export_parser.add_argument('output_file', help='Output CSV file')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        analyzer = AlmaPatronTypeAnalyzer()
        
        if args.command == 'analyze':
            report = analyzer.generate_comprehensive_report(args.output)
            print(report)
            
        elif args.command == 'list':
            patron_types = analyzer.get_all_patron_types()
            if patron_types:
                print(f"\n{'Code':<20} | {'Count':<8} | {'Description'}")
                print("─" * 60)
                for pt in patron_types:
                    code = pt.get('value', '')
                    desc = pt.get('desc', '')
                    count = analyzer.get_patron_count_for_type(code)
                    print(f"{code:<20} | {count:<8,} | {desc}")
            
        elif args.command == 'inspect':
            details = analyzer.get_patron_details_by_type(args.patron_type, args.samples)
            
            print(f"\n🔍 PATRON TYPE DETAILS: {details['code']}")
            print("═" * 60)
            print(f"Total Patrons: {details['total_count']:,}")
            print(f"Analysis: {details['analysis']}")
            
            if details['sample_users']:
                print(f"\nSample Users (showing {len(details['sample_users'])}):")
                print("─" * 60)
                for user in details['sample_users']:
                    name = f"{user['first_name']} {user['last_name']}"
                    print(f"• {name} ({user['primary_id']}) - {user['email']}")
                    print(f"  Status: {user['status']}, Created: {user['created_date']}")
            
        elif args.command == 'export':
            print("Exporting all patron type data...")
            report = analyzer.generate_comprehensive_report(args.output_file)
            print("✅ Export completed!")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
