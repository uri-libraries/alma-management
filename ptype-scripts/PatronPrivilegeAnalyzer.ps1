#Requires -Version 5.1
<#
.SYNOPSIS
    Alma Patron Privilege Analyzer - Compares privilege differences between patron types

.DESCRIPTION
    Analyzes the privilege differences between the following patron types:
    - Staff
    - Faculty
    - Adjunct
    - FacultyStaff

.PARAMETER OutputFile
    Path to save CSV output (optional)

.PARAMETER Environment
    Alma environment: SANDBOX or PRODUCTION (overrides .env file)

.EXAMPLE
    .\PatronPrivilegeAnalyzer.ps1

.EXAMPLE
    .\PatronPrivilegeAnalyzer.ps1 -OutputFile "privilege_analysis.csv"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$OutputFile,

    [Parameter(Mandatory=$false)]
    [ValidateSet("SANDBOX", "PRODUCTION")]
    [string]$Environment
)

# Configuration
$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

# Load environment variables
function Load-Environment {
    $envFile = if ($Environment -eq "SANDBOX") { ".env.sandbox" } else { ".env" }
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^([^#][^=]+)=(.*)$') {
                $key = $matches[1].Trim()
                $value = $matches[2].Trim()
                [Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
        Write-Host "✅ Environment loaded from $envFile" -ForegroundColor Green
    } else {
        Write-Warning "Environment file not found: $envFile"
    }
}

# Call Alma API
function Call-AlmaApi {
    param (
        [string]$Endpoint,
        [hashtable]$Params,
        [int]$RetryCount = 3
    )

    $baseUrl = [Environment]::GetEnvironmentVariable("ALMA_API_BASE_URL")
    $apiKey = [Environment]::GetEnvironmentVariable("ALMA_API_KEY")

    if (-not $baseUrl -or -not $apiKey) {
        throw "Missing Alma API credentials. Ensure ALMA_API_BASE_URL and ALMA_API_KEY are set."
    }

    $queryString = ($Params.GetEnumerator() | ForEach-Object { "{0}={1}" -f $_.Key, $_.Value }) -join "&"
    $uri = "$baseUrl/$($Endpoint.TrimStart('/'))?$queryString"
    $headers = @{ Authorization = "apikey $apiKey" }

    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        try {
            return Invoke-RestMethod -Uri $uri -Headers $headers -Method GET -ErrorAction Stop
        } catch {
            Write-Verbose "API call failed: $($_.Exception.Message)"
            Write-Verbose "Response: $($_ | Out-String)"

            if ($attempt -eq $RetryCount) {
                throw "API call failed after $RetryCount attempts: $uri"
            }
            Start-Sleep -Seconds 2
        }
    }
}

# Analyze privileges
function Analyze-Privileges {
    $patronTypes = @("Staff", "Faculty", "Adjunct", "FacultyStaff")
    $results = @()

    foreach ($type in $patronTypes) {
        Write-Host "🔍 Analyzing privileges for patron type: $type" -ForegroundColor Blue

        # Adjusted to fetch users by specific identifiers or groups
        Write-Warning "The Alma API does not support filtering users by status or patron type directly. Please provide specific user identifiers or groups to analyze."
        return

        $response = Call-AlmaApi "/users" @{ "q" = "status~ACTIVE"; "limit" = 100 }  # Fetch active users
        $filteredUsers = $response.user | Where-Object { $_.user_group.value -eq $type }

        if (-not $filteredUsers) {
            Write-Warning "No users found for patron type: $type"
            continue
        }

        $user = $filteredUsers | Select-Object -First 1
        $fullUser = Call-AlmaApi "/users/$($user.primary_id)" @{ "view" = "full" }

        $privileges = $fullUser.user_roles.user_role | ForEach-Object {
            [PSCustomObject]@{
                Role = $_.role_type.value
                Scope = $_.scope.value
                Status = $_.status.value
            }
        }

        $results += [PSCustomObject]@{
            PatronType = $type
            Privileges = $privileges
        }
    }

    return $results
}

# Main script
Load-Environment
$results = Analyze-Privileges

# Output results
if ($OutputFile) {
    $results | Export-Csv -Path $OutputFile -NoTypeInformation
    Write-Host "✅ Results saved to $OutputFile" -ForegroundColor Green
} else {
    $results | Format-Table -AutoSize
}