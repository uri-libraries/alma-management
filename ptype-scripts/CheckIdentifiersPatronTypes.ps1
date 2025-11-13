#Requires -Version 5.1
<#
.SYNOPSIS
    Check Patron Types for Users in identifiers-synced.csv
    
.DESCRIPTION
    Reads primary identifiers from identifiers-synced.csv and checks the patron type
    for each user in Alma, generating a detailed report.
    
.PARAMETER InputFile
    Path to CSV file containing primary identifiers (default: identifiers-synced.csv)
    
.PARAMETER OutputFile
    Path to save results CSV (optional, default: auto-generated with timestamp)
    
.PARAMETER Environment
    Alma environment: SANDBOX or PRODUCTION (overrides .env file)
    
.PARAMETER BatchSize
    Number of users to process before saving progress (default: 50)
    
.EXAMPLE
    .\CheckIdentifiersPatronTypes.ps1
    
.EXAMPLE
    .\CheckIdentifiersPatronTypes.ps1 -InputFile "identifiers-synced.csv" -OutputFile "patron_types_results.csv"
    
.EXAMPLE
    .\CheckIdentifiersPatronTypes.ps1 -Environment SANDBOX
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$InputFile = "identifiers-synced.csv",
    
    [Parameter(Mandatory=$false)]
    [string]$OutputFile,
    
    [Parameter(Mandatory=$false)]
    [ValidateSet("SANDBOX", "PRODUCTION")]
    [string]$Environment,
    
    [Parameter(Mandatory=$false)]
    [ValidateRange(10, 500)]
    [int]$BatchSize = 50
)

# Configuration
$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

# Script metadata
$ScriptVersion = "1.0.0"
$ScriptName = "Check Identifiers Patron Types"

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

class AlmaUserChecker {
    [string]$ApiKey
    [string]$BaseUrl
    [hashtable]$Headers
    [int]$RequestCount = 0
    [int]$SuccessCount = 0
    [int]$NotFoundCount = 0
    [int]$ErrorCount = 0
    [datetime]$StartTime
    
    AlmaUserChecker([hashtable]$Config) {
        $this.ApiKey = $Config.ApiKey
        $this.BaseUrl = $Config.BaseUrl
        $this.StartTime = Get-Date
        
        $this.Headers = @{
            'Accept' = 'application/json'
            'Authorization' = "apikey $($this.ApiKey)"
            'User-Agent' = "PowerShell-AlmaUserChecker/1.0"
        }
    }
    
    [object] GetUser([string]$PrimaryId) {
        return $this.GetUser($PrimaryId, 3)
    }
    
    [object] GetUser([string]$PrimaryId, [int]$RetryCount) {
        $endpoint = "/almaws/v1/users/$PrimaryId"
        $uri = "$($this.BaseUrl)$endpoint"
        $this.RequestCount++
        
        Write-Verbose "API Call #$($this.RequestCount): $endpoint"
        
        $attempt = 0
        while ($attempt -lt $RetryCount) {
            try {
                $attempt++
                
                $response = Invoke-RestMethod -Uri $uri -Headers $this.Headers -Method Get -TimeoutSec 30
                
                # Rate limiting - be gentle with the API
                Start-Sleep -Milliseconds 200
                
                Write-Verbose "API Success: Found user $PrimaryId"
                $this.SuccessCount++
                return $response
            }
            catch {
                $statusCode = $null
                if ($_.Exception.Response) {
                    $statusCode = $_.Exception.Response.StatusCode.value__
                }
                
                Write-Verbose "API Error (attempt $attempt/$RetryCount): $endpoint - Status: $statusCode"
                
                # Handle 404 - user not found
                if ($statusCode -eq 404) {
                    Write-Verbose "User not found: $PrimaryId"
                    $this.NotFoundCount++
                    return $null
                }
                
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
                
                # Final attempt failed or client error
                if ($attempt -eq $RetryCount) {
                    Write-Warning "API call failed after $RetryCount attempts: $PrimaryId - $($_.Exception.Message)"
                    $this.ErrorCount++
                    return $null
                }
            }
        }
        
        $this.ErrorCount++
        return $null
    }
    
    [hashtable] GetStatistics() {
        return @{
            TotalRequests = $this.RequestCount
            Successful = $this.SuccessCount
            NotFound = $this.NotFoundCount
            Errors = $this.ErrorCount
            ElapsedTime = (Get-Date) - $this.StartTime
        }
    }
}

#endregion

#region Main Processing Functions

function Import-IdentifierList {
    param([string]$FilePath)
    
    Write-Section "📂 Loading Identifiers from CSV" "Blue"
    
    if (-not (Test-Path $FilePath)) {
        throw "Input file not found: $FilePath"
    }
    
    try {
        $csvData = Import-Csv -Path $FilePath
        
        # Get the column name (should be "Primary identifier")
        $columnName = $csvData[0].PSObject.Properties.Name | Select-Object -First 1
        
        if (-not $columnName) {
            throw "CSV file appears to be empty or malformed"
        }
        
        $identifiers = $csvData | ForEach-Object { $_.$columnName } | Where-Object { $_ -and $_.Trim() }
        
        Write-Host "✅ Loaded $($identifiers.Count) identifiers from: $FilePath" -ForegroundColor "Green"
        Write-Host "   Column name: $columnName" -ForegroundColor "Blue"
        
        if ($identifiers.Count -eq 0) {
            throw "No valid identifiers found in CSV file"
        }
        
        return $identifiers
    }
    catch {
        throw "Error reading CSV file: $($_.Exception.Message)"
    }
}

function Process-UserIdentifiers {
    param(
        [AlmaUserChecker]$Checker,
        [array]$Identifiers,
        [string]$OutputFile,
        [int]$BatchSize
    )
    
    Write-Section "🔍 Processing User Identifiers" "Blue"
    
    $results = @()
    $totalUsers = $identifiers.Count
    $counter = 0
    $lastSaveCounter = 0
    
    foreach ($identifier in $identifiers) {
        $counter++
        $percentComplete = ($counter / $totalUsers) * 100
        
        Write-Progress -Activity "Checking patron types" `
            -Status "Processing: $identifier ($counter of $totalUsers)" `
            -PercentComplete $percentComplete `
            -CurrentOperation "Success: $($Checker.SuccessCount) | Not Found: $($Checker.NotFoundCount) | Errors: $($Checker.ErrorCount)"
        
        # Clean the identifier
        $cleanId = $identifier.Trim()
        
        if ([string]::IsNullOrWhiteSpace($cleanId)) {
            Write-Verbose "Skipping empty identifier at row $counter"
            continue
        }
        
        # Get user from Alma
        $user = $Checker.GetUser([string]$cleanId)
        
        if ($user) {
            # Extract relevant information
            $result = [PSCustomObject]@{
                PrimaryIdentifier = $cleanId
                PatronType = $user.user_group.value
                PatronTypeDescription = $user.user_group.desc
                Status = $user.status.value
                FirstName = $user.first_name
                LastName = $user.last_name
                ExternalId = $user.external_id
                Email = if ($user.contact_info.email) { ($user.contact_info.email | Select-Object -First 1).email_address } else { "" }
                ExpirationDate = $user.expiry_date
                CreatedDate = $user.created_date
                LastModified = $user.last_modified_date
                AccountType = $user.account_type.value
                CampusCode = if ($user.campus_code) { $user.campus_code.value } else { "" }
                Found = "Yes"
                ErrorMessage = ""
            }
        } else {
            # User not found or error
            $result = [PSCustomObject]@{
                PrimaryIdentifier = $cleanId
                PatronType = ""
                PatronTypeDescription = ""
                Status = ""
                FirstName = ""
                LastName = ""
                ExternalId = ""
                Email = ""
                ExpirationDate = ""
                CreatedDate = ""
                LastModified = ""
                AccountType = ""
                CampusCode = ""
                Found = "No"
                ErrorMessage = "User not found or API error"
            }
        }
        
        $results += $result
        
        # Save progress at regular intervals
        if (($counter - $lastSaveCounter) -ge $BatchSize -and $OutputFile) {
            Write-Verbose "Saving progress batch at $counter records..."
            try {
                $results | Export-Csv -Path $OutputFile -NoTypeInformation -Encoding UTF8 -Force
                $lastSaveCounter = $counter
            }
            catch {
                Write-Warning "Failed to save progress: $($_.Exception.Message)"
            }
        }
    }
    
    Write-Progress -Activity "Checking patron types" -Completed
    
    return $results
}

function Show-Summary {
    param(
        [array]$Results,
        [hashtable]$Statistics
    )
    
    Write-Section "📊 PROCESSING SUMMARY" "Cyan"
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    
    Write-Host "Completed: $timestamp" -ForegroundColor "Blue"
    Write-Host "Total Identifiers: $($Results.Count.ToString('N0'))" -ForegroundColor "Blue"
    Write-Host "Processing Time: $($Statistics.ElapsedTime.ToString('hh\:mm\:ss'))" -ForegroundColor "Blue"
    Write-Host "API Calls Made: $($Statistics.TotalRequests.ToString('N0'))" -ForegroundColor "Blue"
    Write-Host ""
    
    # Success rate
    $foundCount = ($Results | Where-Object { $_.Found -eq "Yes" }).Count
    $notFoundCount = ($Results | Where-Object { $_.Found -eq "No" }).Count
    $successRate = if ($Results.Count -gt 0) { ($foundCount / $Results.Count * 100) } else { 0 }
    
    Write-Host "RESULTS:" -ForegroundColor "Blue"
    Write-Host "─" * 50 -ForegroundColor "DarkGray"
    Write-Host ("  Users Found:".PadRight(25) + "$($foundCount.ToString('N0').PadLeft(10)) ($($successRate.ToString('F1'))%)") -ForegroundColor "Green"
    Write-Host ("  Users Not Found:".PadRight(25) + "$($notFoundCount.ToString('N0').PadLeft(10))") -ForegroundColor "Red"
    Write-Host ""
    
    # Patron type breakdown
    if ($foundCount -gt 0) {
        Write-Section "📋 PATRON TYPE BREAKDOWN" "Blue"
        
        $patronTypeGroups = $Results | Where-Object { $_.Found -eq "Yes" } | Group-Object PatronType | Sort-Object Count -Descending
        
        $headerFormat = "{0,-25} | {1,10} | {2,8}"
        Write-Host ($headerFormat -f "Patron Type", "Count", "Percent") -ForegroundColor "DarkGray"
        Write-Host ("─" * 50) -ForegroundColor "DarkGray"
        
        foreach ($group in $patronTypeGroups) {
            $percent = ($group.Count / $foundCount * 100)
            $ptCode = if ($group.Name) { $group.Name } else { "(No Type)" }
            Write-Host ($headerFormat -f $ptCode, $group.Count.ToString('N0'), "$($percent.ToString('F1'))%") -ForegroundColor "White"
        }
        
        Write-Host ""
        
        # Status breakdown
        Write-Section "📊 STATUS BREAKDOWN" "Blue"
        
        $statusGroups = $Results | Where-Object { $_.Found -eq "Yes" } | Group-Object Status | Sort-Object Count -Descending
        
        foreach ($group in $statusGroups) {
            $percent = ($group.Count / $foundCount * 100)
            $statusName = if ($group.Name) { $group.Name } else { "(No Status)" }
            Write-Host ($headerFormat -f $statusName, $group.Count.ToString('N0'), "$($percent.ToString('F1'))%") -ForegroundColor "White"
        }
    }
    
    # Show sample of not found identifiers if any
    if ($notFoundCount -gt 0) {
        Write-Section "⚠️  NOT FOUND IDENTIFIERS (Sample)" "Yellow"
        
        $notFoundSample = $Results | Where-Object { $_.Found -eq "No" } | Select-Object -First 10
        
        foreach ($sample in $notFoundSample) {
            Write-Host "  • $($sample.PrimaryIdentifier)" -ForegroundColor "Yellow"
        }
        
        if ($notFoundCount -gt 10) {
            Write-Host "  ... and $($notFoundCount - 10) more" -ForegroundColor "Yellow"
        }
    }
}

function Export-Results {
    param(
        [array]$Results,
        [string]$OutputFile
    )
    
    Write-Section "💾 Exporting Results" "Blue"
    
    try {
        $Results | Export-Csv -Path $OutputFile -NoTypeInformation -Encoding UTF8 -Force
        Write-Host "✅ Results exported to: $OutputFile" -ForegroundColor "Green"
        Write-Host "   Total records: $($Results.Count)" -ForegroundColor "Blue"
        
        # Show file size
        $fileInfo = Get-Item $OutputFile
        $fileSizeKB = [Math]::Round($fileInfo.Length / 1KB, 2)
        Write-Host "   File size: $fileSizeKB KB" -ForegroundColor "Blue"
    }
    catch {
        Write-Host "❌ Failed to export CSV: $($_.Exception.Message)" -ForegroundColor "Red"
        throw
    }
}

#endregion

#region Main Execution

try {
    # Show startup banner
    Write-Host ""
    Write-Header "Check Identifiers Patron Types v1.0.0" "Cyan"
    Write-Host "Checks patron types for users in identifiers-synced.csv" -ForegroundColor "Blue"
    Write-Host ""
    
    # Load environment variables
    Import-DotEnv
    
    # Test credentials
    $credentials = Test-AlmaCredentials
    
    # Resolve input file path
    if (-not [System.IO.Path]::IsPathRooted($InputFile)) {
        $InputFile = Join-Path $PSScriptRoot $InputFile
    }
    
    # Generate output file name if not specified
    if (-not $OutputFile) {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $OutputFile = Join-Path $PSScriptRoot "patron_types_check_$timestamp.csv"
    } elseif (-not [System.IO.Path]::IsPathRooted($OutputFile)) {
        $OutputFile = Join-Path $PSScriptRoot $OutputFile
    }
    
    Write-Host "📁 Input file: $InputFile" -ForegroundColor "Blue"
    Write-Host "📁 Output file: $OutputFile" -ForegroundColor "Blue"
    Write-Host ""
    
    # Import identifiers
    $identifiers = Import-IdentifierList -FilePath $InputFile
    
    # Initialize checker
    $checker = [AlmaUserChecker]::new($credentials)
    
    Write-Host "🚀 Starting processing..." -ForegroundColor "Green"
    Write-Host "   Total identifiers to process: $($identifiers.Count)" -ForegroundColor "Blue"
    Write-Host "   Batch save interval: Every $BatchSize users" -ForegroundColor "Blue"
    Write-Host ""
    
    # Process all identifiers
    $results = Process-UserIdentifiers -Checker $checker -Identifiers $identifiers -OutputFile $OutputFile -BatchSize $BatchSize
    
    # Get statistics
    $stats = $checker.GetStatistics()
    
    # Final save
    Export-Results -Results $results -OutputFile $OutputFile
    
    # Show summary
    Show-Summary -Results $results -Statistics $stats
    
    Write-Host "`n✅ Processing completed successfully!" -ForegroundColor "Green"
    Write-Host "Results saved to: $OutputFile" -ForegroundColor "Blue"
}
catch {
    Write-Host "`n❌ Error: $($_.Exception.Message)" -ForegroundColor "Red"
    Write-Host "Stack trace: $($_.ScriptStackTrace)" -ForegroundColor "DarkGray"
    exit 1
}
finally {
    # Cleanup
    Write-Progress -Activity "Processing" -Completed
}

#endregion
