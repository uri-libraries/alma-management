#Requires -Version 5.1
<#
.SYNOPSIS
    Alma Patron Type Analyzer - PowerShell Edition
    
.DESCRIPTION
    Analyzes Alma patron types to identify SIS-managed vs manually-managed types
    for cleanup and streamlining purposes.
    
.PARAMETER Command
    The operation to perform: analyze, list, or help
    
.PARAMETER OutputFile
    Path to save CSV output (optional)
    
.PARAMETER PatronType
    Specific patron type code to analyze (optional)
    
.PARAMETER SampleSize
    Number of sample users to fetch for detailed analysis (default: 5)
    
.PARAMETER Environment
    Alma environment: SANDBOX or PRODUCTION (overrides .env file)
    
.EXAMPLE
    .\AlmaPatronTypeAnalyzer.ps1 -Command analyze
    
.EXAMPLE
    .\AlmaPatronTypeAnalyzer.ps1 -Command analyze -OutputFile "patron_analysis.csv"
    
.EXAMPLE
    .\AlmaPatronTypeAnalyzer.ps1 -Command list
#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("analyze", "list", "help")]
    [string]$Command = "analyze",
    
    [Parameter(Mandatory=$false)]
    [string]$OutputFile,
    
    [Parameter(Mandatory=$false)]
    [string]$PatronType,
    
    [Parameter(Mandatory=$false)]
    [ValidateRange(1, 50)]
    [int]$SampleSize = 5,
    
    [Parameter(Mandatory=$false)]
    [ValidateSet("SANDBOX", "PRODUCTION")]
    [string]$Environment
)

# Configuration
$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

# Script metadata
$ScriptVersion = "1.0.0"
$ScriptName = "Alma Patron Type Analyzer"

# Color scheme
$Colors = @{
    Header = "Cyan"
    Success = "Green" 
    Warning = "Yellow"
    Error = "Red"
    Info = "Blue"
    Separator = "DarkGray"
}

#region Helper Functions

function Write-Header {
    param([string]$Title, [string]$Color = "Cyan")
    
    $separator = "═" * 80
    Write-Host $separator -ForegroundColor $Color
    Write-Host "  $Title".PadRight(78) -ForegroundColor $Color
    Write-Host $separator -ForegroundColor $Color
}

function Write-Section {
    param([string]$Title, [string]$Color = "Yellow")
    
    Write-Host "`n$Title" -ForegroundColor $Color
    Write-Host ("─" * $Title.Length) -ForegroundColor "DarkGray"
}

function Import-DotEnv {
    param([string]$Path = ".env")
    
    # Determine which .env file to use
    if ($Environment) {
        if ($Environment -eq "SANDBOX") {
            $Path = ".env.sandbox"
        } else {
            $Path = ".env"
        }
    } else {
        # Check for ALMA_ENV environment variable
        $envVar = [Environment]::GetEnvironmentVariable("ALMA_ENV")
        if ($envVar -eq "SANDBOX") {
            $Path = ".env.sandbox"
        } else {
            $Path = ".env"
        }
    }
    
    Write-Verbose "Loading environment from: $Path"
    
    if (Test-Path $Path) {
        Get-Content $Path | ForEach-Object {
            if ($_ -match '^([^#][^=]+)=(.*)$') {
                $key = $matches[1].Trim()
                $value = $matches[2].Trim()
                
                # Remove quotes if present
                if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") {
                    $value = $matches[1]
                }
                
                [Environment]::SetEnvironmentVariable($key, $value, "Process")
                Write-Verbose "Set $key = $value"
            }
        }
        Write-Host "✅ Environment loaded from $Path" -ForegroundColor "Green"
    } else {
        Write-Warning "Environment file not found: $Path"
    }
}

function Test-AlmaCredentials {
    $apiKey = [Environment]::GetEnvironmentVariable("ALMA_API_KEY")
    $baseUrl = [Environment]::GetEnvironmentVariable("ALMA_API_BASE_URL")
    
    if (-not $apiKey) {
        throw "ALMA_API_KEY not found in environment variables"
    }
    
    if (-not $baseUrl) {
        throw "ALMA_API_BASE_URL not found in environment variables"
    }
    
    Write-Host "✅ API credentials found" -ForegroundColor "Green"
    Write-Host "   Base URL: $baseUrl" -ForegroundColor "Blue"
    Write-Host "   API Key: $($apiKey.Substring(0, [Math]::Min(8, $apiKey.Length)))..." -ForegroundColor "Blue"
    
    return @{
        ApiKey = $apiKey
        BaseUrl = $baseUrl
    }
}

#endregion

#region Alma API Class

class AlmaPatronAnalyzer {
    [string]$ApiKey
    [string]$BaseUrl
    [hashtable]$Headers
    [int]$RequestCount = 0
    [datetime]$StartTime
    
    AlmaPatronAnalyzer([hashtable]$Config) {
        $this.ApiKey = $Config.ApiKey
        $this.BaseUrl = $Config.BaseUrl
        $this.StartTime = Get-Date
        
        $this.Headers = @{
            'Accept' = 'application/json'
            'Authorization' = "apikey $($this.ApiKey)"
            'User-Agent' = "PowerShell-AlmaPatronAnalyzer/1.0"
        }
    }
    
    [object] CallAlmaApi([string]$Endpoint, [hashtable]$Params = @{}, [int]$RetryCount = 3) {
        $uri = "$($this.BaseUrl)/almaws/v1$Endpoint"
        $this.RequestCount++
        
        Write-Verbose "API Call #$($this.RequestCount): $Endpoint"
        
        $attempt = 0
        while ($attempt -lt $RetryCount) {
            try {
                $attempt++
                
                # Add query parameters to URI if provided
                if ($Params.Count -gt 0) {
                    $queryString = ($Params.GetEnumerator() | ForEach-Object { 
                        "$($_.Key)=$([System.Web.HttpUtility]::UrlEncode($_.Value))" 
                    }) -join "&"
                    $uri = "$uri`?$queryString"
                }
                
                $response = Invoke-RestMethod -Uri $uri -Headers $this.Headers -Method Get -TimeoutSec 30
                
                # Rate limiting - be gentle with the API
                Start-Sleep -Milliseconds 250
                
                Write-Verbose "API Success: $Endpoint"
                return $response
            }
            catch {
                $statusCode = $null
                if ($_.Exception.Response) {
                    $statusCode = $_.Exception.Response.StatusCode.value__
                }
                
                Write-Verbose "API Error (attempt $attempt/$RetryCount): $Endpoint - $($_.Exception.Message)"
                
                # Handle rate limiting
                if ($statusCode -eq 429) {
                    $waitTime = [Math]::Pow(2, $attempt) * 1000  # Exponential backoff
                    Write-Warning "Rate limited. Waiting $waitTime ms before retry..."
                    Start-Sleep -Milliseconds $waitTime
                    continue
                }
                
                # Handle server errors with retry
                if ($statusCode -ge 500 -and $attempt -lt $RetryCount) {
                    Write-Warning "Server error ($statusCode). Retrying in 2 seconds..."
                    Start-Sleep -Seconds 2
                    continue
                }
                
                # Don't retry client errors (400-499)
                if ($statusCode -ge 400 -and $statusCode -lt 500) {
                    Write-Warning "Client error for $Endpoint : $($_.Exception.Message)"
                    return $null
                }
                
                # Final attempt failed
                if ($attempt -eq $RetryCount) {
                    Write-Warning "API call failed after $RetryCount attempts: $Endpoint - $($_.Exception.Message)"
                    return $null
                }
            }
        }
        
        return $null
    }
    
    [array] GetAllPatronTypes() {
        Write-Host "🔍 Fetching all patron types from Alma..." -ForegroundColor "Blue"
        
        $response = $this.CallAlmaApi("/conf/code-tables/UserGroups", @{}, 3)
        
        if (-not $response -or -not $response.row) {
            throw "Failed to retrieve patron types from Alma API"
        }
        
        $patronTypes = @()
        $rows = $response.row
        
        # Handle both single item and array responses
        if ($rows -is [array]) {
            foreach ($row in $rows) {
                $patronTypes += @{
                    Code = $row.code
                    Description = $row.description
                    Enabled = $row.enabled
                }
            }
        } else {
            $patronTypes += @{
                Code = $rows.code
                Description = $rows.description  
                Enabled = $rows.enabled
            }
        }
        
        Write-Host "✅ Retrieved $($patronTypes.Count) patron types" -ForegroundColor "Green"
        return $patronTypes
    }
    
    [hashtable] GetPatronCountAndSamples([string]$PatronTypeCode, [int]$SampleSize = 5) {
        Write-Verbose "Getting patron count for type: $PatronTypeCode"
        
        # First, get the total count
        $countParams = @{
            'q' = "user_group~$PatronTypeCode"
            'limit' = 1
        }
        
        $countResponse = $this.CallAlmaApi("/users", $countParams, 3)
        
        $result = @{
            Count = 0
            Samples = @()
            LastActivity = $null
            HasActiveUsers = $false
        }
        
        if (-not $countResponse) {
            return $result
        }
        
        $result.Count = [int]$countResponse.total_record_count
        
        # If there are users, get samples for analysis
        if ($result.Count -gt 0 -and $SampleSize -gt 0) {
            $sampleParams = @{
                'q' = "user_group~$PatronTypeCode"
                'limit' = [Math]::Min($SampleSize, $result.Count)
                'offset' = 0
            }
            
            $sampleResponse = $this.CallAlmaApi("/users", $sampleParams, 3)
            
            if ($sampleResponse -and $sampleResponse.user) {
                $users = if ($sampleResponse.user -is [array]) { $sampleResponse.user } else { @($sampleResponse.user) }
                
                foreach ($user in $users) {
                    $lastModified = $null
                    if ($user.last_modified_date) {
                        try {
                            $lastModified = [DateTime]::Parse($user.last_modified_date)
                        } catch {
                            Write-Verbose "Could not parse date: $($user.last_modified_date)"
                        }
                    }
                    
                    $isActive = $user.status.value -eq "ACTIVE"
                    if ($isActive) {
                        $result.HasActiveUsers = $true
                    }
                    
                    # Track most recent activity
                    if ($lastModified -and (-not $result.LastActivity -or $lastModified -gt $result.LastActivity)) {
                        $result.LastActivity = $lastModified
                    }
                    
                    $result.Samples += @{
                        PrimaryId = $user.primary_id
                        Status = $user.status.value
                        LastModified = $lastModified
                        ExternalId = $user.external_id
                        CreatedBy = $user.created_by
                    }
                }
            }
        }
        
        return $result
    }
    
    [hashtable] AnalyzePatronTypes() {
        Write-Header "Alma Patron Type Analyzer - Analysis Report" "Cyan"
        Write-Host "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor "Blue"
        Write-Host ""
        
        $patronTypes = $this.GetAllPatronTypes()
        
        Write-Section "🎯 Analyzing patron types for classification..." "Blue"
        
        # Classification keywords
        $sisIndicators = @(
            'student', 'undergraduate', 'graduate', 'faculty', 'staff', 'employee', 
            'ug_', 'grad_', 'phd_', 'ms_', 'ma_', 'bs_', 'ba_', 'dpt_', 'md_',
            'full_time', 'part_time', 'ft_', 'pt_', 'fulltime', 'parttime',
            'active', 'inactive', 'continuing', 'new', 'current',
            'freshman', 'sophomore', 'junior', 'senior', 'first_year',
            'adjunct', 'tenure', 'clinical', 'research', 'postdoc',
            'alumni', 'alumnus', 'alumna', 'former'
        )
        
        $manualIndicators = @(
            'guest', 'visitor', 'temp', 'temporary', 'external', 'community', 
            'special', 'courtesy', 'honorary', 'emeritus', 'retired',
            'ill', 'interlibrary', 'reciprocal', 'consortial', 'consortium',
            'walk_in', 'walkin', 'public', 'patron', 'card_only',
            'fee', 'paid', 'sponsored', 'volunteer', 'intern',
            'contractor', 'vendor', 'consultant'
        )
        
        $categorized = @{
            LikelySIS = @()
            LikelyManual = @()
            Uncertain = @()
            Empty = @()
            Disabled = @()
        }
        
        $totalPatrons = 0
        $counter = 0
        
        foreach ($pt in $patronTypes) {
            $counter++
            $percentComplete = ($counter / $patronTypes.Count) * 100
            Write-Progress -Activity "Analyzing patron types" -Status "Processing: $($pt.Code)" -PercentComplete $percentComplete
            
            # Check if patron type is enabled
            if ($pt.Enabled -eq "false") {
                $ptInfo = @{
                    Code = $pt.Code
                    Description = $pt.Description
                    PatronCount = 0
                    SISScore = 0
                    ManualScore = 0
                    Enabled = $false
                    Samples = @()
                    LastActivity = $null
                    HasActiveUsers = $false
                }
                $categorized.Disabled += $ptInfo
                continue
            }
            
            # Analyze patron type name and description for classification
            $combinedText = "$($pt.Code) $($pt.Description)".ToLower()
            
            $sisScore = ($sisIndicators | Where-Object { $combinedText -like "*$_*" }).Count
            $manualScore = ($manualIndicators | Where-Object { $combinedText -like "*$_*" }).Count
            
            # Get patron count and samples
            $patronData = $this.GetPatronCountAndSamples($pt.Code, 5)  # Fixed sample size
            $totalPatrons += $patronData.Count
            
            $ptInfo = @{
                Code = $pt.Code
                Description = $pt.Description
                PatronCount = $patronData.Count
                SISScore = $sisScore
                ManualScore = $manualScore
                Enabled = $true
                Samples = $patronData.Samples
                LastActivity = $patronData.LastActivity
                HasActiveUsers = $patronData.HasActiveUsers
            }
            
            # Categorize based on patron count and scoring
            if ($patronData.Count -eq 0) {
                $categorized.Empty += $ptInfo
            }
            elseif ($sisScore -gt $manualScore -and $sisScore -gt 0) {
                $categorized.LikelySIS += $ptInfo
            }
            elseif ($manualScore -gt $sisScore -and $manualScore -gt 0) {
                $categorized.LikelyManual += $ptInfo
            }
            else {
                $categorized.Uncertain += $ptInfo
            }
        }
        
        Write-Progress -Activity "Analyzing patron types" -Completed
        
        # Sort categories by patron count (descending)
        $categoryKeys = @($categorized.Keys)
        foreach ($category in $categoryKeys) {
            $categorized[$category] = $categorized[$category] | Sort-Object PatronCount -Descending
        }
        
        # Add summary statistics
        $categorized.Summary = @{
            TotalPatronTypes = $patronTypes.Count
            TotalPatrons = $totalPatrons
            ProcessingTime = (Get-Date) - $this.StartTime
            ApiCalls = $this.RequestCount
        }
        
        return $categorized
    }
}

#endregion

#region Display Functions

function Show-PatronTypeAnalysis {
    param(
        [hashtable]$Categorized,
        [string]$OutputFile
    )
    
    $summary = $Categorized.Summary
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    
    Write-Section "📊 ANALYSIS SUMMARY" "Cyan"
    
    Write-Host "Generated: $timestamp"
    Write-Host "Total Patron Types: $($summary.TotalPatronTypes.ToString('N0'))"
    Write-Host "Total Patrons: $($summary.TotalPatrons.ToString('N0'))"
    Write-Host "Processing Time: $($summary.ProcessingTime.ToString('mm\:ss'))"
    Write-Host "API Calls Made: $($summary.ApiCalls.ToString('N0'))"
    Write-Host ""
    
    # Category summary with percentages
    $sisTotal = ($Categorized.LikelySIS | Measure-Object -Property PatronCount -Sum).Sum
    $manualTotal = ($Categorized.LikelyManual | Measure-Object -Property PatronCount -Sum).Sum
    $uncertainTotal = ($Categorized.Uncertain | Measure-Object -Property PatronCount -Sum).Sum
    
    $sisPercent = if ($summary.TotalPatrons -gt 0) { ($sisTotal / $summary.TotalPatrons * 100) } else { 0 }
    $manualPercent = if ($summary.TotalPatrons -gt 0) { ($manualTotal / $summary.TotalPatrons * 100) } else { 0 }
    $uncertainPercent = if ($summary.TotalPatrons -gt 0) { ($uncertainTotal / $summary.TotalPatrons * 100) } else { 0 }
    
    Write-Host "CATEGORY BREAKDOWN:" -ForegroundColor "Blue"
    Write-Host "─" * 50 -ForegroundColor "DarkGray"
    Write-Host ("Likely SIS/Automatic:".PadRight(25) + 
              "$($Categorized.LikelySIS.Count.ToString().PadLeft(3)) types, " + 
              "$($sisTotal.ToString('N0').PadLeft(7)) patrons " +
              "($($sisPercent.ToString('F1'))%)") -ForegroundColor "Green"
              
    Write-Host ("Likely Manual/Special:".PadRight(25) + 
              "$($Categorized.LikelyManual.Count.ToString().PadLeft(3)) types, " + 
              "$($manualTotal.ToString('N0').PadLeft(7)) patrons " +
              "($($manualPercent.ToString('F1'))%)") -ForegroundColor "Blue"
              
    Write-Host ("Uncertain Classification:".PadRight(25) + 
              "$($Categorized.Uncertain.Count.ToString().PadLeft(3)) types, " + 
              "$($uncertainTotal.ToString('N0').PadLeft(7)) patrons " +
              "($($uncertainPercent.ToString('F1'))%)") -ForegroundColor "Yellow"
              
    Write-Host ("Empty (No Patrons):".PadRight(25) + 
              "$($Categorized.Empty.Count.ToString().PadLeft(3)) types, " + 
              "$('0'.PadLeft(7)) patrons (0.0%)") -ForegroundColor "Red"
              
    Write-Host ("Disabled:".PadRight(25) + 
              "$($Categorized.Disabled.Count.ToString().PadLeft(3)) types, " + 
              "$('0'.PadLeft(7)) patrons (0.0%)") -ForegroundColor "DarkGray"
    
    # Detailed sections
    $sections = @(
        @{ Title = "🎓 LIKELY SIS/AUTOMATIC PATRON TYPES"; Key = "LikelySIS"; Color = "Green" }
        @{ Title = "👤 LIKELY MANUAL/SPECIAL PATRON TYPES"; Key = "LikelyManual"; Color = "Blue" }
        @{ Title = "❓ UNCERTAIN CLASSIFICATION"; Key = "Uncertain"; Color = "Yellow" }
        @{ Title = "🚫 EMPTY PATRON TYPES (Candidates for Removal)"; Key = "Empty"; Color = "Red" }
        @{ Title = "💤 DISABLED PATRON TYPES"; Key = "Disabled"; Color = "DarkGray" }
    )
    
    foreach ($section in $sections) {
        $data = $Categorized[$section.Key]
        if ($data.Count -gt 0) {
            Write-Section $section.Title $section.Color
            
            # Table header
            $headerFormat = "{0,-20} | {1,8} | {2,6} | {3,-35} | {4,-12}"
            Write-Host ($headerFormat -f "Code", "Count", "Active", "Description", "Last Activity") -ForegroundColor "DarkGray"
            Write-Host ("─" * 90) -ForegroundColor "DarkGray"
            
            # Table rows
            foreach ($pt in $data) {
                $code = $pt.Code.Substring(0, [Math]::Min(19, $pt.Code.Length))
                $count = $pt.PatronCount.ToString('N0')
                $activeStatus = if ($pt.HasActiveUsers) { "Yes" } else { "No" }
                $desc = $pt.Description.Substring(0, [Math]::Min(34, $pt.Description.Length))
                $lastActivity = if ($pt.LastActivity) { $pt.LastActivity.ToString("yyyy-MM-dd") } else { "Unknown" }
                
                $rowColor = switch ($section.Key) {
                    "Empty" { "Red" }
                    "Disabled" { "DarkGray" }
                    default { "White" }
                }
                
                Write-Host ($headerFormat -f $code, $count, $activeStatus, $desc, $lastActivity) -ForegroundColor $rowColor
            }
            
            # Section recommendations
            switch ($section.Key) {
                "LikelySIS" {
                    Write-Host "`n💡 Recommendation: These types are likely managed by your SIS integration" -ForegroundColor "Blue"
                    Write-Host "   - Review for consolidation opportunities" -ForegroundColor "Blue"
                    Write-Host "   - Ensure SIS mapping is correct" -ForegroundColor "Blue"
                }
                "LikelyManual" {
                    Write-Host "`n💡 Recommendation: These types likely require manual management" -ForegroundColor "Blue"
                    Write-Host "   - Document creation/approval processes" -ForegroundColor "Blue"
                    Write-Host "   - Consider expiration dates for temporary access" -ForegroundColor "Blue"
                }
                "Empty" {
                    Write-Host "`n⚠️  Cleanup Opportunity: Consider removing unused patron types" -ForegroundColor "Yellow"
                    Write-Host "   - Verify they're not referenced in policies or workflows" -ForegroundColor "Yellow"
                    Write-Host "   - Check if they're part of historical data requirements" -ForegroundColor "Yellow"
                }
                "Disabled" {
                    Write-Host "`n📋 Note: These patron types are disabled in Alma" -ForegroundColor "Blue"
                    Write-Host "   - Consider removing if permanently unused" -ForegroundColor "Blue"
                }
            }
        }
    }
    
    # Export detailed data to CSV if requested
    if ($OutputFile) {
        Export-DetailedAnalysis -Categorized $Categorized -OutputFile $OutputFile
    }
    
    # Final recommendations
    Write-Section "🎯 STREAMLINING RECOMMENDATIONS" "Cyan"
    
    $emptyCount = $Categorized.Empty.Count
    $disabledCount = $Categorized.Disabled.Count
    $uncertainCount = $Categorized.Uncertain.Count
    
    Write-Host "1. IMMEDIATE CLEANUP OPPORTUNITIES:" -ForegroundColor "Green"
    Write-Host "   • $emptyCount empty patron types can likely be removed" -ForegroundColor "Blue"
    Write-Host "   • $disabledCount disabled patron types should be reviewed for removal" -ForegroundColor "Blue"
    Write-Host ""
    
    Write-Host "2. CLASSIFICATION REVIEW NEEDED:" -ForegroundColor "Yellow"
    Write-Host "   • $uncertainCount patron types need manual classification" -ForegroundColor "Blue"
    Write-Host "   • Review uncertain types for consolidation opportunities" -ForegroundColor "Blue"
    Write-Host ""
    
    Write-Host "3. SIS INTEGRATION REVIEW:" -ForegroundColor "Blue"
    Write-Host "   • Verify SIS-managed types align with your student/employee data" -ForegroundColor "Blue"
    Write-Host "   • Consider consolidating similar automatic patron types" -ForegroundColor "Blue"
}

function Export-DetailedAnalysis {
    param(
        [hashtable]$Categorized,
        [string]$OutputFile
    )
    
    Write-Host "`n📄 Exporting detailed analysis to CSV..." -ForegroundColor "Blue"
    
    $csvData = @()
    $categories = @('LikelySIS', 'LikelyManual', 'Uncertain', 'Empty', 'Disabled')
    
    foreach ($category in $categories) {
        foreach ($pt in $Categorized[$category]) {
            $sampleInfo = ""
            if ($pt.Samples.Count -gt 0) {
                $sampleSources = $pt.Samples | ForEach-Object { $_.CreatedBy } | Where-Object { $_ } | Sort-Object | Get-Unique
                $sampleInfo = ($sampleSources -join "; ")
            }
            
            $csvData += [PSCustomObject]@{
                Category = $category
                Code = $pt.Code
                Description = $pt.Description
                PatronCount = $pt.PatronCount
                HasActiveUsers = $pt.HasActiveUsers
                LastActivity = if ($pt.LastActivity) { $pt.LastActivity.ToString("yyyy-MM-dd") } else { "" }
                SISScore = $pt.SISScore
                ManualScore = $pt.ManualScore
                Enabled = $pt.Enabled
                SampleSources = $sampleInfo
                Recommendation = switch ($category) {
                    "Empty" { "Consider for removal" }
                    "Disabled" { "Review for removal" }
                    "LikelySIS" { "Verify SIS mapping" }
                    "LikelyManual" { "Document processes" }
                    "Uncertain" { "Manual classification needed" }
                }
            }
        }
    }
    
    try {
        $csvData | Export-Csv -Path $OutputFile -NoTypeInformation -Encoding UTF8
        Write-Host "✅ Analysis exported to: $OutputFile" -ForegroundColor "Green"
        Write-Host "   Records: $($csvData.Count)" -ForegroundColor "Blue"
    }
    catch {
        Write-Host "❌ Failed to export CSV: $($_.Exception.Message)" -ForegroundColor "Red"
    }
}

function Show-PatronTypeList {
    param([AlmaPatronAnalyzer]$Analyzer)
    
    Write-Header "Alma Patron Types - Simple List" "Cyan"
    
    $patronTypes = $Analyzer.GetAllPatronTypes()
    
    # Table header
    $headerFormat = "{0,-25} | {1,8} | {2,-7} | {3,-40}"
    Write-Host ($headerFormat -f "Code", "Count", "Enabled", "Description") -ForegroundColor "Blue"
    Write-Host ("─" * 90) -ForegroundColor "DarkGray"
    
    $totalCount = 0
    $enabledCount = 0
    
    foreach ($pt in ($patronTypes | Sort-Object Code)) {
        $patronData = $Analyzer.GetPatronCountAndSamples($pt.Code, 0)
        $count = $patronData.Count
        $totalCount += $count
        
        if ($pt.Enabled -ne "false") {
            $enabledCount++
        }
        
        $code = $pt.Code.Substring(0, [Math]::Min(24, $pt.Code.Length))
        $desc = $pt.Description.Substring(0, [Math]::Min(39, $pt.Description.Length))
        $enabled = if ($pt.Enabled -eq "false") { "No" } else { "Yes" }
        
        $rowColor = if ($pt.Enabled -eq "false") { "DarkGray" } elseif ($count -eq 0) { "Yellow" } else { "White" }
        
        Write-Host ($headerFormat -f $code, $count.ToString('N0'), $enabled, $desc) -ForegroundColor $rowColor
    }
    
    Write-Host ("─" * 90) -ForegroundColor "DarkGray"
    Write-Host "Total Patron Types: $($patronTypes.Count) (Enabled: $enabledCount)" -ForegroundColor "Blue"
    Write-Host "Total Patrons: $($totalCount.ToString('N0'))" -ForegroundColor "Blue"
}

function Show-Help {
    Write-Header "Alma Patron Type Analyzer v1.0.0 - Help" "Cyan"
    
    Write-Host @"
DESCRIPTION:
    Analyzes Alma patron types to identify SIS-managed vs manually-managed types
    for cleanup and streamlining purposes.

USAGE:
    .\AlmaPatronTypeAnalyzer.ps1 [PARAMETERS]

PARAMETERS:
    -Command <String>      Operation to perform: analyze, list, help (default: analyze)
    -OutputFile <String>   Path to save CSV output (optional)
    -PatronType <String>   Specific patron type code to analyze (future feature)
    -SampleSize <Int>      Number of sample users to fetch (1-50, default: 5)
    -Environment <String>  Override environment: SANDBOX or PRODUCTION

EXAMPLES:
    # Basic analysis
    .\AlmaPatronTypeAnalyzer.ps1

    # Analysis with CSV export
    .\AlmaPatronTypeAnalyzer.ps1 -Command analyze -OutputFile "patron_analysis.csv"

    # Simple list view
    .\AlmaPatronTypeAnalyzer.ps1 -Command list

    # Force sandbox environment
    .\AlmaPatronTypeAnalyzer.ps1 -Environment SANDBOX

    # Detailed analysis with larger samples
    .\AlmaPatronTypeAnalyzer.ps1 -SampleSize 10 -OutputFile "detailed_analysis.csv"

ENVIRONMENT SETUP:
    Create .env file with:
        ALMA_API_KEY=your_production_key
        ALMA_API_BASE_URL=https://api-na.hosted.exlibrisgroup.com

    Create .env.sandbox file with:
        ALMA_API_KEY=your_sandbox_key
        ALMA_API_BASE_URL=https://api-eu.hosted.exlibrisgroup.com

OUTPUT:
    The analysis categorizes patron types into:
    • Likely SIS/Automatic - Managed by student information systems
    • Likely Manual/Special - Require manual creation/management
    • Uncertain Classification - Need manual review
    • Empty - No current patrons (cleanup candidates)
    • Disabled - Currently disabled in Alma

"@ -ForegroundColor "Blue"
}

#endregion

#region Main Execution

try {
    # Show startup banner
    Write-Host ""
    Write-Header "Alma Patron Type Analyzer v1.0.0" "Cyan"
    Write-Host "PowerShell Edition - Alma Patron Type Analysis & Cleanup Tool" -ForegroundColor "Blue"
    Write-Host ""
    
    # Handle help command early
    if ($Command -eq "help") {
        Show-Help
        exit 0
    }
    
    # Load environment variables
    Import-DotEnv
    
    # Test credentials
    $credentials = Test-AlmaCredentials
    
    # Initialize analyzer
    $analyzer = [AlmaPatronAnalyzer]::new($credentials)
    
    Write-Host "🚀 Starting analysis..." -ForegroundColor "Green"
    Write-Host ""
    
    # Execute requested command
    switch ($Command.ToLower()) {
        "analyze" {
            $categorized = $analyzer.AnalyzePatronTypes()
            Show-PatronTypeAnalysis -Categorized $categorized -OutputFile $OutputFile
        }
        
        "list" {
            Show-PatronTypeList -Analyzer $analyzer
        }
        
        default {
            Write-Host "Unknown command: $Command" -ForegroundColor "Red"
            Write-Host "Use -Command help for usage information" -ForegroundColor "Blue"
            exit 1
        }
    }
    
    Write-Host "`n✅ Analysis completed successfully!" -ForegroundColor "Green"
    Write-Host "Total API calls made: $($analyzer.RequestCount)" -ForegroundColor "Blue"
    Write-Host "Total processing time: $((Get-Date) - $analyzer.StartTime | ForEach-Object { $_.ToString('mm\:ss') })" -ForegroundColor "Blue"
}
catch {
    Write-Host "`n❌ Error: $($_.Exception.Message)" -ForegroundColor "Red"
    Write-Host "Stack trace: $($_.ScriptStackTrace)" -ForegroundColor "DarkGray"
    exit 1
}
finally {
    # Cleanup
    Write-Progress -Activity "Analysis" -Completed
}

#endregion