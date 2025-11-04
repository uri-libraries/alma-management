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

    $queryString = if ($Params) {
        ($Params.GetEnumerator() | ForEach-Object { "{0}={1}" -f $_.Key, $_.Value }) -join "&"
    } else {
        ""
    }
    $uri = "$baseUrl/almaws/v1/$($Endpoint.TrimStart('/'))?$queryString"

    # Ensure proper parameters for loan policies
    if ($Endpoint -eq "/conf/loan-policies" -and -not $Params.ContainsKey("user_group")) {
        Write-Warning "Missing required parameter 'user_group' for loan policies API."
        return $null
    }

    $headers = @{ Authorization = "apikey $apiKey" }

    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        try {
            return Invoke-RestMethod -Uri $uri -Headers $headers -Method GET -ErrorAction Stop
        } catch {
            Write-Verbose "API call failed: $($_.Exception.Message)"
            Write-Verbose "Response: $($_ | Out-String)"
            Write-Verbose "User ID: $userId, Endpoint: /users/$userId?view=full"
            Write-Verbose "Full API Response: $($_ | Out-String)"
            Write-Verbose "Attempted URL: $uri"

            if ($attempt -eq $RetryCount) {
                throw "API call failed after $RetryCount attempts: $uri"
            }
            Start-Sleep -Seconds 2
        }
    }
}

# Enhanced Get-LoanPolicies function to accept dynamic parameters
function Get-LoanPolicies {
    param (
        [hashtable]$Params
    )

    Write-Host "🔍 Fetching loan policies with parameters: $($Params | ConvertTo-Json -Depth 10)" -ForegroundColor Blue

    $policies = Call-AlmaApi "/conf/loan-policies" $Params

    if (-not $policies) {
        Write-Warning "Could not retrieve loan policies with provided parameters."
        return $null
    }

    return $policies
}

# Enhanced privilege comparison with detailed differences
function Compare-Privileges {
    param (
        [array]$UserDetails
    )

    $comparisonResults = @()

    foreach ($type in $UserDetails.Keys) {
        $roles = $UserDetails[$type].user_role
        $loanPolicies = Get-LoanPolicies -Params @{ "user_group" = $UserDetails[$type].user_group }

        $comparisonResults += [PSCustomObject]@{
            PatronType = $type
            Roles = ($roles | ForEach-Object { $_.role_type }) -join ", "
            LoanPolicies = if ($loanPolicies) {
                ($loanPolicies | ForEach-Object { $_.name }) -join ", "
            } else {
                "None"
            }
        }
    }

    # Compare roles, privileges, and policies
    Write-Host "🔍 Comparing roles, privileges, and policies..." -ForegroundColor Blue
    foreach ($result in $comparisonResults) {
        Write-Host "Patron Type: $($result.PatronType)" -ForegroundColor Green
        Write-Host "Roles: $($result.Roles)" -ForegroundColor Yellow
        Write-Host "Loan Policies: $($result.LoanPolicies)" -ForegroundColor Cyan
    }

    # Export to CSV
    $comparisonResults | Export-Csv -Path "./privilege_comparison.csv" -NoTypeInformation
    Write-Host "✅ Comparison results exported to privilege_comparison.csv" -ForegroundColor Green
}

# Corrected Analyze-Privileges function to properly access response content
function Analyze-Privileges {
    $userIdentifiers = @{
        Faculty = "21222005633826"
        Staff = "21222005729855"
        FacultyStaff = "21222001475602"
        Adjunct = "21222006466770"
    }
    $userDetails = @{}

    foreach ($type in $userIdentifiers.Keys) {
        Write-Host "🔍 Analyzing privileges for patron type: $type" -ForegroundColor Blue

        $userId = $userIdentifiers[$type]
        try {
            $response = Invoke-WebRequest -Uri "$([Environment]::GetEnvironmentVariable('ALMA_API_BASE_URL'))/almaws/v1/users/$userId?view=full" -Headers @{ Authorization = "apikey $([Environment]::GetEnvironmentVariable('ALMA_API_KEY'))" } -Method GET -ErrorAction Stop
            $rawResponse = $response.Content | ConvertFrom-Json
            Write-Host "Raw API Response for ${type}:" -ForegroundColor Cyan
            Write-Host ($rawResponse | ConvertTo-Json -Depth 10)
        } catch {
            Write-Warning "Failed to fetch user details for user ID: $userId. Error: $($_.Exception.Message)"

            # Log detailed response for HTTP errors
            if ($_.Exception.Response -and $_.Exception.Response.Content) {
                try {
                    $responseBody = $_.Exception.Response.Content.ReadAsStringAsync().Result
                    Write-Host "Response Body for HTTP Error:" -ForegroundColor Yellow
                    Write-Host $responseBody
                } catch {
                    Write-Warning "Failed to read response body. Error: $($_.Exception.Message)"
                }
            }

            continue
        }

        $fullUser = $rawResponse
        if (-not $fullUser) {
            Write-Warning "Could not retrieve details for user ID: $userId"
            continue
        }

        $userDetails[$type] = $fullUser

        # Inspect user group field
        $userGroup = $fullUser.user_group
        if (-not $userGroup) {
            Write-Warning "User group not found for user ID: $userId. Skipping loan policy retrieval."
            continue
        }

        # Fetch loan policies with user group
        $params = @{ "user_group" = $userGroup }
        if (-not $params.ContainsKey("library")) {
            $params["library"] = "MAIN"  # Default library
        }
        if (-not $params.ContainsKey("circ_desk")) {
            $params["circ_desk"] = "DEFAULT_CIRC"  # Default circulation desk
        }

        try {
            $loanPolicies = Get-LoanPolicies -Params $params

            if (-not $loanPolicies) {
                Write-Warning "API call failed for user group: ${userGroup}. Check permissions or parameters."
            } else {
                Write-Host "Loan Policies for ${type}: $(${loanPolicies | ConvertTo-Json -Depth 10})" -ForegroundColor Cyan
            }
        } catch {
            Write-Host "Error occurred during API call for user group: ${userGroup}" -ForegroundColor Red
            Write-Host "Error Details: $($_ | Out-String)" -ForegroundColor Yellow
        }
    }

    Compare-Privileges -UserDetails $userDetails
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