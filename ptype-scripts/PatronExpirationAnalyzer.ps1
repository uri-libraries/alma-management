#Requires -Version 5.1
<#
.SYNOPSIS
    Alma Patron Expiration Analyzer - Analyzes expiration rates by patron type
    
.DESCRIPTION
    Analyzes specific patron types to determine what percentage of users 
    in each type have expired accounts.
    
.PARAMETER PatronTypes
    Array of patron type codes to analyze (default: predefined list)
    
.PARAMETER OutputFile
    Path to save CSV output (optional)
    
.PARAMETER SampleSize
    Maximum number of users to analyze per patron type (default: 1000)
    
.PARAMETER Environment
    Alma environment: SANDBOX or PRODUCTION (overrides .env file)
    
.EXAMPLE
    .\PatronExpirationAnalyzer.ps1
    
.EXAMPLE
    .\PatronExpirationAnalyzer.ps1 -OutputFile "expiration_analysis.csv"
    
.EXAMPLE
    .\PatronExpirationAnalyzer.ps1 -PatronTypes @("HELINUndergraduate", "VisitingFaculty") -SampleSize 500
#>

param(
    [Parameter(Mandatory=$false)]
    [string[]]$PatronTypes = @("HELINUndergraduate", "VisitingFaculty", "Internal", "InternationalSchola", "AdHoc", "HighSchool"),
    
    [Parameter(Mandatory=$false)]
    [string]$OutputFile,
    
    [Parameter(Mandatory=$false)]
    [ValidateRange(10, 5000)]
    [int]$SampleSize = 1000,
    
    [Parameter(Mandatory=$false)]
    [ValidateSet("SANDBOX", "PRODUCTION")]
    [string]$Environment
)

# Configuration
$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

# Script metadata
$ScriptVersion = "1.0.0"
$ScriptName = "Alma Patron Expiration Analyzer"

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

class AlmaExpirationAnalyzer {
    [string]$ApiKey
    [string]$BaseUrl
    [hashtable]$Headers
    [int]$RequestCount = 0
    [datetime]$StartTime
    
    AlmaExpirationAnalyzer([hashtable]$Config) {
        $this.ApiKey = $Config.ApiKey
        $this.BaseUrl = $Config.BaseUrl
        $this.StartTime = Get-Date
        
        $this.Headers = @{
            'Accept' = 'application/json'
            'Authorization' = "apikey $($this.ApiKey)"
            'User-Agent' = "PowerShell-PatronExpirationAnalyzer/1.0"
        }
    }
    
    [object] CallAlmaApi([string]$Endpoint, [hashtable]$Params, [int]$RetryCount) {
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
                Start-Sleep -Milliseconds 300
                
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
    
    [hashtable] AnalyzePatronTypeExpiration([string]$PatronTypeCode, [int]$MaxUsers) {
        Write-Host "🔍 Analyzing patron type: $PatronTypeCode" -ForegroundColor "Blue"
        
        # Get users for this patron type with full details
        $params = @{
            'q' = "user_group~$PatronTypeCode"
            'limit' = $MaxUsers
            'offset' = 0
            'expand' = 'none'
            'view' = 'full'
        }
        
        $response = $this.CallAlmaApi("/users", $params, 3)
        
        $result = @{
            PatronType = $PatronTypeCode
            TotalFound = 0
            TotalAnalyzed = 0
            ExpiredCount = 0
            ActiveCount = 0
            ExpirationRate = 0.0
            Users = @()
            Error = $null
        }
        
        if (-not $response) {
            $result.Error = "Failed to retrieve users for patron type $PatronTypeCode"
            return $result
        }
        
        $result.TotalFound = [int]$response.total_record_count
        
        if ($response.user) {
            $users = if ($response.user -is [array]) { $response.user } else { @($response.user) }
            $result.TotalAnalyzed = $users.Count
            
            $currentDate = Get-Date
            
            foreach ($user in $users) {
                # Get full user details to access creation date and other fields
                Write-Verbose "Fetching full details for user: $($user.primary_id)"
                $fullUser = $this.CallAlmaApi("/users/$($user.primary_id)", @{'view' = 'full'; 'expand' = 'none'}, 2)
                
                if (-not $fullUser) {
                    Write-Warning "Could not retrieve full details for user $($user.primary_id)"
                    continue
                }
                
                $isExpired = $false
                $expiryDate = $null
                $daysSinceExpiry = $null
                
                # Parse expiry date from full user record
                if ($fullUser.expiry_date) {
                    try {
                        $expiryDate = [DateTime]::Parse($fullUser.expiry_date)
                        $isExpired = $expiryDate -lt $currentDate
                        
                        if ($isExpired) {
                            $daysSinceExpiry = ($currentDate - $expiryDate).Days
                        }
                    }
                    catch {
                        Write-Verbose "Could not parse expiry date for user $($fullUser.primary_id): $($fullUser.expiry_date)"
                    }
                }
                
                # Count expired vs active
                if ($isExpired) {
                    $result.ExpiredCount++
                } else {
                    $result.ActiveCount++
                }
                
                # Parse creation date from full user record
                $createdDate = $null
                $daysSinceCreation = $null
                
                if ($fullUser.created_date) {
                    try {
                        $createdDate = [DateTime]::Parse($fullUser.created_date)
                        $daysSinceCreation = ($currentDate - $createdDate).Days
                        Write-Verbose "Successfully parsed creation date for $($fullUser.primary_id): $createdDate ($daysSinceCreation days ago)"
                    }
                    catch {
                        Write-Verbose "Could not parse creation date for user $($fullUser.primary_id): $($fullUser.created_date)"
                    }
                } else {
                    Write-Verbose "No created_date property found for user $($fullUser.primary_id)"
                }
                
                # Store user details for analysis (using full user record)
                $result.Users += @{
                    PrimaryId = $fullUser.primary_id
                    Status = $fullUser.status.value
                    ExpiryDate = $expiryDate
                    IsExpired = $isExpired
                    DaysSinceExpiry = $daysSinceExpiry
                    CreatedDate = $createdDate
                    DaysSinceCreation = $daysSinceCreation
                    CreatedBy = $fullUser.created_by
                    FirstName = $fullUser.first_name
                    LastName = $fullUser.last_name
                    UserGroup = $fullUser.user_group.value
                }
            }
            
            # Calculate expiration rate
            if ($result.TotalAnalyzed -gt 0) {
                $result.ExpirationRate = ($result.ExpiredCount / $result.TotalAnalyzed) * 100
            }
        }
        
        Write-Host "   📊 Results: $($result.TotalAnalyzed) users analyzed, $($result.ExpiredCount) expired ($($result.ExpirationRate.ToString('F1'))%)" -ForegroundColor "Green"
        
        return $result
    }
    
    [hashtable] AnalyzeMultiplePatronTypes([string[]]$PatronTypes, [int]$MaxUsersPerType) {
        Write-Header "Alma Patron Expiration Analyzer - Analysis Report" "Cyan"
        Write-Host "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor "Blue"
        Write-Host "Analyzing $($PatronTypes.Count) patron types with up to $MaxUsersPerType users each" -ForegroundColor "Blue"
        Write-Host ""
        
        $results = @()
        $totalUsers = 0
        $totalExpired = 0
        
        $counter = 0
        foreach ($patronType in $PatronTypes) {
            $counter++
            $percentComplete = ($counter / $PatronTypes.Count) * 100
            Write-Progress -Activity "Analyzing patron type expiration rates" -Status "Processing: $patronType" -PercentComplete $percentComplete
            
            $typeResult = $this.AnalyzePatronTypeExpiration($patronType, $MaxUsersPerType)
            $results += $typeResult
            
            $totalUsers += $typeResult.TotalAnalyzed
            $totalExpired += $typeResult.ExpiredCount
        }
        
        Write-Progress -Activity "Analyzing patron type expiration rates" -Completed
        
        # Calculate overall statistics
        $overallExpirationRate = if ($totalUsers -gt 0) { ($totalExpired / $totalUsers) * 100 } else { 0.0 }
        
        return @{
            Results = $results
            Summary = @{
                TotalPatronTypes = $PatronTypes.Count
                TotalUsersAnalyzed = $totalUsers
                TotalExpiredUsers = $totalExpired
                OverallExpirationRate = $overallExpirationRate
                ProcessingTime = (Get-Date) - $this.StartTime
                ApiCalls = $this.RequestCount
            }
        }
    }
}

#endregion

#region Display Functions

function Show-ExpirationAnalysis {
    param(
        [hashtable]$Analysis,
        [string]$OutputFile
    )
    
    $summary = $Analysis.Summary
    $results = $Analysis.Results
    
    Write-Section "📊 EXPIRATION ANALYSIS SUMMARY" "Cyan"
    
    Write-Host "Analysis completed: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "Patron types analyzed: $($summary.TotalPatronTypes)"
    Write-Host "Total users analyzed: $($summary.TotalUsersAnalyzed.ToString('N0'))"
    Write-Host "Total expired users: $($summary.TotalExpiredUsers.ToString('N0'))"
    Write-Host "Overall expiration rate: $($summary.OverallExpirationRate.ToString('F1'))%"
    Write-Host "Processing time: $($summary.ProcessingTime.ToString('mm\:ss'))"
    Write-Host "API calls made: $($summary.ApiCalls.ToString('N0'))"
    Write-Host ""
    
    # Detailed results by patron type
    Write-Section "🎯 EXPIRATION RATES BY PATRON TYPE" "Yellow"
    
    # Sort results by expiration rate (highest first)
    $sortedResults = $results | Where-Object { -not $_.Error } | Sort-Object ExpirationRate -Descending
    
    # Table header
    $headerFormat = "{0,-20} | {1,8} | {2,8} | {3,8} | {4,10} | {5,12} | {6,-15}"
    Write-Host ($headerFormat -f "Patron Type", "Total", "Analyzed", "Expired", "Rate %", "Avg Age", "Status") -ForegroundColor "DarkGray"
    Write-Host ("─" * 100) -ForegroundColor "DarkGray"
    
    # Table rows
    foreach ($result in $sortedResults) {
        $patronType = $result.PatronType.Substring(0, [Math]::Min(19, $result.PatronType.Length))
        $total = $result.TotalFound.ToString('N0')
        $analyzed = $result.TotalAnalyzed.ToString('N0')
        $expired = $result.ExpiredCount.ToString('N0')
        $rate = $result.ExpirationRate.ToString('F1')
        
        # Calculate average age of accounts (days since creation)
        $usersWithCreationDate = $result.Users | Where-Object { $_.DaysSinceCreation -ne $null }
        $avgAge = if ($usersWithCreationDate.Count -gt 0) {
            $totalDays = ($usersWithCreationDate | Measure-Object -Property DaysSinceCreation -Sum).Sum
            $avgDays = $totalDays / $usersWithCreationDate.Count
            if ($avgDays -gt 365) {
                "$([Math]::Round($avgDays / 365, 1))y"
            } else {
                "$([Math]::Round($avgDays))d"
            }
        } else {
            "Unknown"
        }
        
        # Color coding based on expiration rate
        $rowColor = if ($result.ExpirationRate -gt 50) { 
            "Red"           # High expiration rate
        } elseif ($result.ExpirationRate -gt 25) { 
            "Yellow"        # Medium expiration rate
        } elseif ($result.ExpirationRate -gt 0) { 
            "Green"         # Low expiration rate
        } else { 
            "Cyan"          # No expired users
        }
        
        $status = if ($result.ExpirationRate -gt 50) { 
            "HIGH EXPIRY"
        } elseif ($result.ExpirationRate -gt 25) { 
            "MEDIUM EXPIRY"
        } elseif ($result.ExpirationRate -gt 0) { 
            "LOW EXPIRY"
        } else { 
            "ALL ACTIVE"
        }
        
        Write-Host ($headerFormat -f $patronType, $total, $analyzed, $expired, $rate, $avgAge, $status) -ForegroundColor $rowColor
    }
    
    # Show errors if any
    $errorResults = $results | Where-Object { $_.Error }
    if ($errorResults) {
        Write-Section "⚠️ ANALYSIS ERRORS" "Red"
        foreach ($errorResult in $errorResults) {
            Write-Host "❌ $($errorResult.PatronType): $($errorResult.Error)" -ForegroundColor "Red"
        }
    }
    
    # Recommendations
    Write-Section "💡 RECOMMENDATIONS" "Cyan"
    
    $highExpiryTypes = $sortedResults | Where-Object { $_.ExpirationRate -gt 50 }
    $mediumExpiryTypes = $sortedResults | Where-Object { $_.ExpirationRate -gt 25 -and $_.ExpirationRate -le 50 }
    $activeTypes = $sortedResults | Where-Object { $_.ExpirationRate -eq 0 }
    
    if ($highExpiryTypes) {
        Write-Host "🔴 HIGH EXPIRATION RATE PATRON TYPES:" -ForegroundColor "Red"
        foreach ($type in $highExpiryTypes) {
            Write-Host "   • $($type.PatronType) - $($type.ExpirationRate.ToString('F1'))% expired" -ForegroundColor "Red"
        }
        Write-Host "   → Consider cleanup or review expiration policies" -ForegroundColor "Blue"
        Write-Host ""
    }
    
    if ($mediumExpiryTypes) {
        Write-Host "🟡 MEDIUM EXPIRATION RATE PATRON TYPES:" -ForegroundColor "Yellow"
        foreach ($type in $mediumExpiryTypes) {
            Write-Host "   • $($type.PatronType) - $($type.ExpirationRate.ToString('F1'))% expired" -ForegroundColor "Yellow"
        }
        Write-Host "   → Monitor and consider proactive renewal processes" -ForegroundColor "Blue"
        Write-Host ""
    }
    
    if ($activeTypes) {
        Write-Host "🟢 PATRON TYPES WITH NO EXPIRED USERS:" -ForegroundColor "Green"
        foreach ($type in $activeTypes) {
            Write-Host "   • $($type.PatronType) - All $($type.TotalAnalyzed) users active" -ForegroundColor "Green"
        }
        Write-Host "   → Well-managed patron types with current expiration policies" -ForegroundColor "Blue"
    }
    
    # Export to CSV if requested
    if ($OutputFile) {
        Export-ExpirationAnalysis -Analysis $Analysis -OutputFile $OutputFile
    }
}

function Export-ExpirationAnalysis {
    param(
        [hashtable]$Analysis,
        [string]$OutputFile
    )
    
    Write-Host "`n📄 Exporting expiration analysis to CSV..." -ForegroundColor "Blue"
    
    try {
        $csvData = @()
        
        foreach ($result in $Analysis.Results) {
            if (-not $result.Error) {
                # Summary row for each patron type
                $csvData += [PSCustomObject]@{
                    PatronType = $result.PatronType
                    TotalFound = $result.TotalFound
                    TotalAnalyzed = $result.TotalAnalyzed
                    ExpiredCount = $result.ExpiredCount
                    ActiveCount = $result.ActiveCount
                    ExpirationRate = [math]::Round($result.ExpirationRate, 2)
                    Status = if ($result.ExpirationRate -gt 50) { "HIGH_EXPIRY" } 
                             elseif ($result.ExpirationRate -gt 25) { "MEDIUM_EXPIRY" } 
                             elseif ($result.ExpirationRate -gt 0) { "LOW_EXPIRY" } 
                             else { "ALL_ACTIVE" }
                    Error = ""
                }
            } else {
                $csvData += [PSCustomObject]@{
                    PatronType = $result.PatronType
                    TotalFound = 0
                    TotalAnalyzed = 0
                    ExpiredCount = 0
                    ActiveCount = 0
                    ExpirationRate = 0
                    Status = "ERROR"
                    Error = $result.Error
                }
            }
        }
        
        $csvData | Export-Csv -Path $OutputFile -NoTypeInformation -Encoding UTF8
        Write-Host "✅ Analysis exported to: $OutputFile" -ForegroundColor "Green"
        Write-Host "   Records: $($csvData.Count)" -ForegroundColor "Blue"
        
        # Also create detailed user export if requested
        $detailedFile = $OutputFile -replace '\.csv$', '_detailed.csv'
        
        $userCsvData = @()
        foreach ($result in $Analysis.Results) {
            if (-not $result.Error -and $result.Users.Count -gt 0) {
                foreach ($user in $result.Users) {
                    $userCsvData += [PSCustomObject]@{
                        PatronType = $result.PatronType
                        PrimaryId = $user.PrimaryId
                        FirstName = $user.FirstName
                        LastName = $user.LastName
                        Status = $user.Status
                        ExpiryDate = if ($user.ExpiryDate) { $user.ExpiryDate.ToString("yyyy-MM-dd") } else { "" }
                        IsExpired = $user.IsExpired
                        DaysSinceExpiry = if ($user.DaysSinceExpiry) { $user.DaysSinceExpiry } else { "" }
                    }
                }
            }
        }
        
        if ($userCsvData.Count -gt 0) {
            $userCsvData | Export-Csv -Path $detailedFile -NoTypeInformation -Encoding UTF8
            Write-Host "✅ Detailed user data exported to: $detailedFile" -ForegroundColor "Green"
            Write-Host "   User records: $($userCsvData.Count)" -ForegroundColor "Blue"
        }
    }
    catch {
        Write-Host "❌ Failed to export CSV: $($_.Exception.Message)" -ForegroundColor "Red"
    }
}

#endregion

#region Main Execution

try {
    # Show startup banner
    Write-Host ""
    Write-Header "$ScriptName v$ScriptVersion" "Cyan"
    Write-Host "PowerShell Edition - Analyze Patron Expiration Rates by Type" -ForegroundColor "Blue"
    Write-Host ""
    
    # Load environment variables
    Import-DotEnv
    
    # Test credentials
    $credentials = Test-AlmaCredentials
    
    # Initialize analyzer
    $analyzer = [AlmaExpirationAnalyzer]::new($credentials)
    
    Write-Host "🚀 Starting expiration analysis..." -ForegroundColor "Green"
    Write-Host "Patron types to analyze: $($PatronTypes -join ', ')" -ForegroundColor "Blue"
    Write-Host "Max users per type: $SampleSize" -ForegroundColor "Blue"
    Write-Host ""
    
    # Run analysis
    $analysis = $analyzer.AnalyzeMultiplePatronTypes($PatronTypes, $SampleSize)
    
    # Display results
    Show-ExpirationAnalysis -Analysis $analysis -OutputFile $OutputFile
    
    Write-Host "`n✅ Expiration analysis completed successfully!" -ForegroundColor "Green"
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