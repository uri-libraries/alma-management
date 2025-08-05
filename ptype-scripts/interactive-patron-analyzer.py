#!/usr/bin/env python3
"""
Interactive Alma Patron Type Analyzer

Simple interactive interface for analyzing patron types in Alma.
Run this script and follow the prompts for an easy-to-use experience.
"""

import os
import sys
from datetime import datetime

# Import the analyzer
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("patron_type_analyzer", "patron-type-analyzer.py")
    analyzer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analyzer_module)
    AlmaPatronTypeAnalyzer = analyzer_module.AlmaPatronTypeAnalyzer
except Exception as e:
    print(f"❌ Error: Could not import patron-type-analyzer.py")
    print(f"Details: {e}")
    print("Make sure the script is in the same directory.")
    sys.exit(1)

def print_header():
    """Print a nice header."""
    print("\n" + "═" * 70)
    print("          🎓 ALMA PATRON TYPE ANALYZER 🎓")
    print("═" * 70)
    print(f"          {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 70)

def print_menu():
    """Print the main menu."""
    print("\n📋 Available Options:")
    print("1. 📊 Run comprehensive analysis (recommended)")
    print("2. 📝 List all patron types with counts")
    print("3. 🔍 Inspect specific patron type")
    print("4. 💾 Export all data to CSV")
    print("5. ❓ Help")
    print("6. 🚪 Exit")
    print("─" * 50)

def get_input(prompt, required=True):
    """Get user input with validation."""
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value
        print("This field is required. Please enter a value.")

def confirm(message):
    """Ask for confirmation."""
    while True:
        response = input(f"{message} (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no', '']:
            return False
        print("Please enter 'y' for yes or 'n' for no.")

def run_comprehensive_analysis(analyzer):
    """Run the comprehensive analysis."""
    print("\n🔍 Running comprehensive patron type analysis...")
    print("This will:")
    print("• Retrieve all patron types from Alma")
    print("• Count patrons in each type")
    print("• Identify SIS vs manual patron types")
    print("• Generate recommendations")
    print()
    
    save_csv = confirm("Save detailed data to CSV file?")
    output_file = None
    
    if save_csv:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"patron_type_analysis_{timestamp}.csv"
        filename = get_input(f"Enter filename (default: {default_name}): ", required=False)
        output_file = filename if filename else default_name
    
    print("\n⏳ Analyzing... (this may take a few minutes)")
    
    try:
        report = analyzer.generate_comprehensive_report(output_file)
        print("\n" + report)
        
        if output_file:
            print(f"\n✅ Detailed data saved to: {output_file}")
            
    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")

def list_patron_types(analyzer):
    """List all patron types with counts."""
    print("\n📝 Retrieving all patron types...")
    
    try:
        patron_types = analyzer.get_all_patron_types()
        
        if not patron_types:
            print("❌ Failed to retrieve patron types.")
            return
        
        print(f"\n✅ Found {len(patron_types)} patron types:")
        print("─" * 70)
        print(f"{'Code':<20} | {'Count':<10} | {'Description'}")
        print("─" * 70)
        
        # Get counts and sort by count (descending)
        patron_data = []
        for pt in patron_types:
            code = pt.get('value', '')
            desc = pt.get('desc', '')
            print(f"⏳ Counting patrons for {code}...")
            count = analyzer.get_patron_count_for_type(code)
            patron_data.append((code, count, desc))
        
        # Sort by count (descending)
        patron_data.sort(key=lambda x: x[1], reverse=True)
        
        print(f"\n{'Code':<20} | {'Count':<10} | {'Description'}")
        print("─" * 70)
        
        total_patrons = 0
        for code, count, desc in patron_data:
            print(f"{code:<20} | {count:<10,} | {desc}")
            total_patrons += count
        
        print("─" * 70)
        print(f"{'TOTAL':<20} | {total_patrons:<10,} | patrons across all types")
        
    except Exception as e:
        print(f"❌ Error: {e}")

def inspect_patron_type(analyzer):
    """Inspect a specific patron type."""
    print("\n🔍 Inspect specific patron type")
    
    # First show available types (just codes)
    try:
        patron_types = analyzer.get_all_patron_types()
        if patron_types:
            print("\nAvailable patron type codes:")
            codes = [pt.get('value', '') for pt in patron_types if pt.get('value')]
            # Show in columns
            for i in range(0, len(codes), 4):
                row = codes[i:i+4]
                print("  " + "  ".join(f"{code:<15}" for code in row))
    except:
        pass
    
    code = get_input("\nEnter patron type code to inspect: ").upper()
    samples = get_input("Number of sample users to show (default: 5): ", required=False)
    sample_count = int(samples) if samples.isdigit() else 5
    
    print(f"\n⏳ Analyzing patron type: {code}")
    
    try:
        details = analyzer.get_patron_details_by_type(code, sample_count)
        
        print(f"\n🔍 PATRON TYPE DETAILS: {details['code']}")
        print("═" * 60)
        print(f"📊 Total Patrons: {details['total_count']:,}")
        print(f"📝 Analysis: {details['analysis']}")
        
        if details['sample_users']:
            print(f"\n👥 Sample Users (showing {len(details['sample_users'])}):")
            print("─" * 60)
            for i, user in enumerate(details['sample_users'], 1):
                name = f"{user['first_name']} {user['last_name']}"
                print(f"{i}. {name} ({user['primary_id']})")
                print(f"   📧 {user['email']}")
                print(f"   📋 Status: {user['status']}")
                print(f"   📅 Created: {user['created_date']}")
                print()
        
    except Exception as e:
        print(f"❌ Error inspecting patron type: {e}")

def export_data(analyzer):
    """Export all data to CSV."""
    print("\n💾 Export all patron type data")
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    default_name = f"alma_patron_types_{timestamp}.csv"
    filename = get_input(f"Enter output filename (default: {default_name}): ", required=False)
    output_file = filename if filename else default_name
    
    print(f"\n⏳ Exporting data to {output_file}...")
    
    try:
        analyzer.generate_comprehensive_report(output_file)
        print(f"✅ Export completed: {output_file}")
        
    except Exception as e:
        print(f"❌ Error during export: {e}")

def show_help():
    """Show help information."""
    print("\n❓ HELP - Alma Patron Type Analyzer")
    print("═" * 50)
    print("""
This tool helps you analyze patron types in your Alma instance:

🔍 COMPREHENSIVE ANALYSIS (Option 1):
   • Best starting point - gives you the full picture
   • Shows all patron types with counts
   • Identifies which types are likely from SIS feeds
   • Provides recommendations for cleanup
   • Can save detailed data to CSV

📝 LIST ALL TYPES (Option 2):
   • Quick overview of all patron types
   • Shows patron counts for each type
   • Sorted by usage (most used first)

🔍 INSPECT SPECIFIC TYPE (Option 3):
   • Deep dive into one patron type
   • Shows sample users from that type
   • Useful for understanding what a type contains

💾 EXPORT DATA (Option 4):
   • Saves all analysis data to CSV file
   • Good for further analysis in Excel/other tools

PREREQUISITES:
• You need a .env file with your Alma API credentials:
  ALMA_API_KEY=your_api_key
  ALMA_API_BASE_URL=https://api-na.hosted.exlibrisgroup.com
  
• Your API key needs Users API and Configuration API read access

TIPS:
• Start with the comprehensive analysis (#1)
• The tool respects Alma's rate limits automatically
• Large institutions may take several minutes for full analysis
• SIS identification is based on naming patterns (manual review recommended)
""")

def main():
    """Main interactive loop."""
    try:
        print_header()
        print("Welcome! This tool analyzes patron types in your Alma instance.")
        print("It will show you which types contain patrons and help identify")
        print("which ones are created by SIS jobs vs. manual processes.")
        
        # Test API connection
        print("\n⏳ Testing Alma API connection...")
        analyzer = AlmaPatronTypeAnalyzer()
        
        # Quick test
        test_response = analyzer.call_alma_api("/conf/user-groups", suppress_errors=True)
        if not test_response:
            print("❌ Failed to connect to Alma API. Please check your credentials.")
            print("Make sure you have a .env file with ALMA_API_KEY and ALMA_API_BASE_URL")
            return
        
        print("✅ Successfully connected to Alma API!")
        
        while True:
            print_menu()
            choice = get_input("Select an option (1-6): ")
            
            if choice == '1':
                run_comprehensive_analysis(analyzer)
            elif choice == '2':
                list_patron_types(analyzer)
            elif choice == '3':
                inspect_patron_type(analyzer)
            elif choice == '4':
                export_data(analyzer)
            elif choice == '5':
                show_help()
            elif choice == '6':
                print("\n👋 Thank you for using the Alma Patron Type Analyzer!")
                break
            else:
                print("❌ Invalid choice. Please select 1-6.")
            
            if choice in ['1', '2', '3', '4']:
                input("\n⏸️  Press Enter to continue...")
    
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        print("Please check your configuration and try again.")

if __name__ == "__main__":
    main()
