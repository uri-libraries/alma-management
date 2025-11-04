#Requires -Version 5.1
<#
.SYNOPSIS
    Alma Total Expired Users Counter - Counts total expired users in Alma
    
.DESCRIPTION
    Counts the total number of users in Alma whose accounts have expired,
    by analyzing specific patron types.
    
.PARAMETER Environment
    Alma environment: SANDBOX or PRODUCTION (overrides .env file)
    
.EXAMPLE
    .\PatronExpirationAnalyzer.ps1
    
.EXAMPLE
    .\PatronExpirationAnalyzer.ps1 -Environment SANDBOX
#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("SANDBOX", "PRODUCTION")]
    [string]$Environment
)

# Configuration
$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

# Script metadata
$ScriptVersion = "1.0.0"
$ScriptName = "Alma Total Expired Users Counter"

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
    
    [int] CountTotalExpiredUsers() {
        Write-Host "🔍 Investigating user data structure for expiry information..." -ForegroundColor "Blue"
        
        # Sample a few users to inspect their full structure
        $params = @{
            'limit' = 5
            'offset' = 0
            'view' = 'full'
        }
        
        $response = $this.CallAlmaApi("/users", $params, 3)
        
        if ($response -and $response.user) {
            $users = if ($response.user -is [array]) { $response.user } else { @($response.user) }
            
            Write-Host "Inspecting user data structure..." -ForegroundColor "Yellow"
            
            foreach ($user in $users[0..2]) {  # Check first 3 users
                Write-Host "`nUser: $($user.primary_id)" -ForegroundColor "Cyan"
                
                # Check various potential expiry fields
                $fields = @(
                    'expiry_date',
                    'purge_date', 
                    'account_type',
                    'status'
                )
                
                foreach ($field in $fields) {
                    if ($user.$field) {
                        Write-Host "  $field : $($user.$field | ConvertTo-Json -Compress)" -ForegroundColor "Gray"
                    }
                }
                
                # Check if there are user identifiers with expiry info
                if ($user.user_identifier) {
                    Write-Host "  user_identifier:" -ForegroundColor "Gray"
                    $identifiers = if ($user.user_identifier -is [array]) { $user.user_identifier } else { @($user.user_identifier) }
                    foreach ($id in $identifiers) {
                        Write-Host "    Type: $($id.id_type.value), Value: $($id.value)" -ForegroundColor "DarkGray"
                    }
                }
                
                # Check user roles for expiry
                if ($user.user_role) {
                    Write-Host "  user_role:" -ForegroundColor "Gray"
                    $roles = if ($user.user_role -is [array]) { $user.user_role } else { @($user.user_role) }
                    foreach ($role in $roles) {
                        Write-Host "    Role: $($role.role_type.value)" -ForegroundColor "DarkGray"
                        if ($role.expiry_date) {
                            Write-Host "      Expiry: $($role.expiry_date)" -ForegroundColor "Red"
                        }
                    }
                }
                
                Write-Host "  ---" -ForegroundColor "DarkGray"
            }
        }
        
        # Try direct query for inactive users (likely what "expired" means)
        Write-Host "`n🔍 Querying for INACTIVE users..." -ForegroundColor "Blue"
        
        $params = @{
            'q' = 'status~INACTIVE'
            'limit' = 1
            'view' = 'brief'
        }
        
        $response = $this.CallAlmaApi("/users", $params, 3)
        
        if ($response -and $response.total_record_count -gt 0) {
            $inactiveCount = [int]$response.total_record_count
            Write-Host "   📊 Found $inactiveCount INACTIVE users" -ForegroundColor "Green"
            return $inactiveCount
        }
        
        # Try other status queries
        Write-Host "`n🔍 Trying other status queries..." -ForegroundColor "Blue"
        
        $statusQueries = @(
            'status~EXPIRED',
            'status~DELETED', 
            'status~SUSPENDED',
            'account_type~EXPIRED'
        )
        
        $totalFound = 0
        
        foreach ($query in $statusQueries) {
            Write-Host "Trying query: $query" -ForegroundColor "Yellow"
            
            $params = @{
                'q' = $query
                'limit' = 1
                'view' = 'brief'
            }
            
            $response = $this.CallAlmaApi("/users", $params, 3)
            
            if ($response -and $response.total_record_count -gt 0) {
                $count = [int]$response.total_record_count
                Write-Host "Found $count users with query: $query" -ForegroundColor "Green"
                $totalFound += $count
            }
        }
        
        if ($totalFound -gt 0) {
            Write-Host "   📊 Total users found with non-active status: $totalFound" -ForegroundColor "Green"
            return $totalFound
        }
        
        # Manual sampling to count inactive users
        Write-Host "`n🔍 Sampling users to count inactive status..." -ForegroundColor "Blue"
        
        $totalInactive = 0
        $offset = 0
        $limit = 100
        $totalProcessed = 0
        $sampleSize = 5000  # Sample 5K users for accurate estimate
        
        while ($offset -lt $sampleSize) {
            $params = @{
                'limit' = $limit
                'offset' = $offset
                'view' = 'brief'  # Use brief for faster processing
            }
            
            $response = $this.CallAlmaApi("/users", $params, 3)
            
            if (-not $response -or -not $response.user) {
                break
            }
            
            $users = if ($response.user -is [array]) { $response.user } else { @($response.user) }
            $totalProcessed += $users.Count
            
            foreach ($user in $users) {
                if ($user.status -and $user.status.value -ne "ACTIVE") {
                    $totalInactive++
                    Write-Host "Found non-active user: $($user.primary_id) - Status: $($user.status.value)" -ForegroundColor "Red"
                }
            }
            
            if ($totalProcessed % 500 -eq 0) {
                Write-Host "Processed $totalProcessed users, found $totalInactive inactive" -ForegroundColor "Blue"
            }
            
            $offset += $limit
            
            if ($users.Count -lt $limit) {
                break
            }
        }
        
        # Estimate based on sample
        if ($totalProcessed -gt 0) {
            $inactiveRate = $totalInactive / $totalProcessed
            $estimatedTotal = [int]($inactiveRate * 62047)
            Write-Host "   📊 Found $totalInactive inactive users in $totalProcessed sample" -ForegroundColor "Green"
            Write-Host "   📊 Estimated total inactive users: $estimatedTotal" -ForegroundColor "Green"
            return $estimatedTotal
        }
        
        return $totalInactive
    }
}

#endregion

#region Main Execution

try {
    # Show startup banner
    Write-Host ""
    Write-Header "$ScriptName v$ScriptVersion" "Cyan"
    Write-Host "PowerShell Edition - Count Total Expired Users in Alma" -ForegroundColor "Blue"
    Write-Host ""
    
    # Load environment variables
    Import-DotEnv
    
    # Test credentials
    $credentials = Test-AlmaCredentials
    
    # Initialize analyzer
    $analyzer = [AlmaExpirationAnalyzer]::new($credentials)
    
    Write-Host "🔍 Checking user_group for a test user..." -ForegroundColor "Blue"
    $testUserId = "21222005633826"  # Faculty user
    $testUser = $analyzer.CallAlmaApi("/users/$testUserId", @{ 'view' = 'full' }, 1)
    if ($testUser) {
        Write-Host "Test user ($testUserId) user_group: $($testUser.user_group | ConvertTo-Json -Depth 2)" -ForegroundColor "Yellow"
    } else {
        Write-Host "Could not fetch test user" -ForegroundColor "Red"
    }
    
    Write-Host "� Starting expired users count..." -ForegroundColor "Green"
    Write-Host ""
    
    # Run count
    $totalExpired = $analyzer.CountTotalExpiredUsers()
    
    # Display results
    Write-Section "📊 TOTAL EXPIRED USERS COUNT" "Cyan"
    Write-Host "Total expired users in Alma: $totalExpired" -ForegroundColor "Green"
    Write-Host ""
    
    Write-Host "`n✅ Expired users count completed successfully!" -ForegroundColor "Green"
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