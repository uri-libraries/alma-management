# Alma Patron Type Analyzer

**⚠️ READ-ONLY TOOL: This script only reads data from Alma and makes NO changes to your system. It is completely safe to run.**

This tool helps you analyze and understand the patron types in your Alma instance. It provides comprehensive insights into:

- 📊 All patron types and their usage counts
- 🎓 Identification of SIS/automatic vs manual patron types  
- 👥 Detailed breakdowns of patron populations
- 💡 Recommendations for patron type cleanup

## Quick Start

### For Non-Technical Users (Recommended)

```bash
python interactive-patron-analyzer.py
```

This launches an easy-to-use interactive menu that guides you through all the analysis options.

### For Command Line Users

```bash
# Run comprehensive analysis
python patron-type-analyzer.py analyze

# List all patron types with counts
python patron-type-analyzer.py list

# Inspect a specific patron type
python patron-type-analyzer.py inspect UNDERGRADUATE

# Export all data to CSV
python patron-type-analyzer.py export patron_data.csv
```

## Prerequisites

1. **API Access**: You need an Alma API key with:
   - Users API - Read access
   - Configuration API - Read access

2. **Environment Setup**: Create a `.env` file with:
   ```
   ALMA_API_KEY=your_alma_api_key_here
   ALMA_API_BASE_URL=https://api-na.hosted.exlibrisgroup.com
   ```
   (Replace with your region's Alma API endpoint)

3. **Python Dependencies**:
   ```bash
   pip install requests python-dotenv
   ```

## What This Tool Analyzes

### 🎓 SIS/Automatic Patron Types
The tool identifies patron types likely created by Student Information Systems or automatic imports based on naming patterns like:
- Student-related: `UNDERGRADUATE`, `GRADUATE`, `UG_FRESH`, `GRAD_PHD`
- Employee-related: `FACULTY`, `STAFF`, `FACULTY_FT`, `STAFF_PT`
- Status-related: `ACTIVE`, `CONTINUING`, `NEW_STUDENT`

### 👤 Manual/Special Patron Types  
Identifies patron types likely created manually for special purposes:
- External users: `GUEST`, `VISITOR`, `COMMUNITY`
- Special access: `ILL`, `RECIPROCAL`, `CONSORTIAL`
- Temporary: `TEMP`, `COURTESY`, `HONORARY`

### 📊 Usage Statistics
For each patron type, shows:
- Total number of patrons
- Percentage of total patron population
- Sample patron records (for inspection)

### 💡 Recommendations
Provides suggestions for:
- Removing unused patron types (0 patrons)
- Consolidating underused types (<10 patrons)
- Reviewing uncertain classifications
- Managing very large patron populations

## Sample Output

```
═══════════════════════════════════════════════════════════════════════════════
                    ALMA PATRON TYPE ANALYSIS REPORT
═══════════════════════════════════════════════════════════════════════════════
Generated: 2025-08-05 14:30:15
Total Patron Types: 25
Total Patrons: 28,745

📊 SUMMARY BY CATEGORY
────────────────────────────────────────────────
Likely SIS/Automatic:     12 types,  26,234 patrons (91.3%)
Likely Manual/Special:     8 types,   2,156 patrons (7.5%)
Uncertain Classification:  3 types,     355 patrons (1.2%)
Empty (No Patrons):        2 types,       0 patrons (0.0%)

🎓 LIKELY SIS/AUTOMATIC PATRON TYPES
────────────────────────────────────────────────────────────────────────────────
Code                 | Count    | Description
────────────────────────────────────────────────────────────────────────────────
UNDERGRADUATE        | 15,234   | Undergraduate Students
GRADUATE             | 4,567    | Graduate Students  
FACULTY              | 3,456    | Faculty Members
STAFF                | 2,234    | Staff Members
...
```

## Understanding the Analysis

### Classification Logic
The tool uses keyword matching to categorize patron types:

- **SIS/Automatic indicators**: student, faculty, staff, undergraduate, graduate, active, etc.
- **Manual/Special indicators**: guest, visitor, external, temporary, special, etc.
- **Scoring system**: Higher scores in each category determine classification
- **Manual review recommended**: The tool provides a starting point, but human review is important

### Patron Counts
- Counts are retrieved in real-time from Alma
- Large institutions may take several minutes for complete analysis
- The tool includes rate limiting to respect Alma's API limits

## Use Cases

### 1. Patron Type Cleanup
Identify unused or underused patron types that can be removed or consolidated.

### 2. SIS Integration Review
Understand which patron types are populated by automated systems vs. manual processes.

### 3. Access Policy Planning
Get population statistics to inform access policies and resource planning.

### 4. Migration Planning
Before major system changes, understand your current patron type landscape.

### 5. Compliance Reporting
Generate reports showing patron type distributions for compliance or administrative purposes.

## Output Files

The tool can generate CSV files with detailed data including:
- Patron type codes and descriptions
- Classification categories (SIS vs Manual)
- Patron counts and percentages
- Analysis scores for review

## Troubleshooting

### Common Issues

**"API credentials not found"**
- Ensure your `.env` file exists in the same directory
- Check that API key and base URL are correct

**"Failed to retrieve patron types"**
- Verify your API key has Configuration API read access
- Check network connectivity to Alma

**"Analysis taking very long"**
- Normal for large institutions (>20,000 patrons)
- The tool includes progress indicators
- You can interrupt and resume if needed

**"Classification seems wrong"**
- The automatic classification is based on naming patterns
- Use the detailed CSV output to review and manually adjust classifications
- Classifications are suggestions, not definitive categorizations

### Performance Notes

- Initial run may take 5-15 minutes for large institutions
- Subsequent runs use some caching for faster performance
- Consider running during off-peak hours for large analyses

## API Permissions Required

Your Alma API key needs:
- **Users API - Read**: To count patrons and get sample records
- **Configuration API - Read**: To retrieve patron type definitions

**Note: This tool only uses READ operations - it never modifies any data in Alma.**

Contact your Alma administrator if you don't have these permissions.

## Integration with Existing Tools

This analyzer works alongside the existing patron-checker tools in this repository:
- Use this for high-level analysis and planning
- Use patron-checker for individual patron investigations
- Both tools share the same API configuration setup
