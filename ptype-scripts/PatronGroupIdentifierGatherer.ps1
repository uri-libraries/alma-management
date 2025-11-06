#Requires -Version 5.1
<#
.SYNOPSIS
    Exports primary identifiers for specific patron groups in Alma.

.DESCRIPTION
    Queries the Alma Users API to retrieve the primary identifiers (and basic patron metadata)
    for the configured patron groups. Results are exported to a timestamped CSV file.

.PARAMETER Environment
    Alma environment selector: SANDBOX or PRODUCTION (overrides .env/.env.sandbox detection).

.EXAMPLE
    .\PatronGroupIdentifierGatherer.ps1

.EXAMPLE
    .\PatronGroupIdentifierGatherer.ps1 -Environment SANDBOX
#>

param(
    [Parameter(Mandatory = $false)]
    [ValidateSet("SANDBOX", "PRODUCTION")]
    [string]$Environment
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

$ScriptVersion = "2.0.2"
$ScriptName = "Patron Group Identifier Gatherer"

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

function Resolve-GroupCode {
    param([string]$Group)

    if (-not $Group) { return $Group }

    $normalized = $Group.Trim()

    $explicitMap = @{
        'Visiting Faculty' = 'VisitingFaculty'
        'High School'      = 'HighSchool'
    }

    if ($explicitMap.ContainsKey($normalized)) {
        return $explicitMap[$normalized]
    }

    if ($normalized -match '\s') {
        $collapsed = ($normalized -replace '\s+', '')
        return $collapsed
    }

    return $normalized
}

function Import-DotEnv {
    param([string]$Path = ".env")

    if ($Environment) {
        $Path = if ($Environment -eq "SANDBOX") { ".env.sandbox" } else { ".env" }
    } else {
        $envSetting = [Environment]::GetEnvironmentVariable("ALMA_ENV")
        if ($envSetting -and $envSetting.ToUpper() -eq "SANDBOX") {
            $Path = ".env.sandbox"
        }
    }

    $resolvedPath = Join-Path -Path $PSScriptRoot -ChildPath $Path
    if (-not (Test-Path $resolvedPath)) {
        throw "Environment file not found: $resolvedPath"
    }

    Get-Content $resolvedPath | ForEach-Object {
        if ($_ -match '^([^#][^=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()

            if ($value -match '^"(.*)"$') {
                $value = $matches[1]
            } elseif ($value -match "^'(.*)'$") {
                $value = $matches[1]
            }

            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }

    Write-Host "✅ Loaded environment configuration from $Path" -ForegroundColor Green
}

function Get-AlmaConfiguration {
    Import-DotEnv

    $apiKey = [Environment]::GetEnvironmentVariable("ALMA_API_KEY")
    $baseUrl = [Environment]::GetEnvironmentVariable("ALMA_API_BASE_URL")

    if (-not $apiKey) {
        throw "ALMA_API_KEY not found in environment variables"
    }

    if (-not $baseUrl) {
        throw "ALMA_API_BASE_URL not found in environment variables"
    }

    $trimmedBaseUrl = $baseUrl.TrimEnd('/')

    return @{
        ApiKey = $apiKey
        BaseUrl = $trimmedBaseUrl
        Headers = @{
            'Accept' = 'application/json'
            'Authorization' = "apikey $apiKey"
            'User-Agent' = "PowerShell-PatronGroupIdentifierGatherer/$ScriptVersion"
        }
    }
}

function Invoke-AlmaApi {
    param(
        [string]$Endpoint,
        [hashtable]$QueryParams,
        [hashtable]$Config,
        [int]$MaxRetries = 3
    )

    $endpointPath = if ($Endpoint.StartsWith("/")) { $Endpoint } else { "/$Endpoint" }

    $attempt = 0
    do {
        $attempt++

        $uriBuilder = [System.UriBuilder]::new($Config.BaseUrl)

        $basePath = $uriBuilder.Path
        if ([string]::IsNullOrWhiteSpace($basePath)) {
            $basePath = "/"
        }

        $endpointSuffix = if ($endpointPath.StartsWith("/")) { $endpointPath } else { "/$endpointPath" }
        $combinedPath = ($basePath.TrimEnd('/')) + "/almaws/v1$endpointSuffix"
        $combinedPath = $combinedPath -replace '/{2,}', '/'
        $uriBuilder.Path = $combinedPath

        if ($QueryParams -and $QueryParams.Count -gt 0) {
            $queryItems = foreach ($item in $QueryParams.GetEnumerator()) {
                $keyEncoded = [System.Uri]::EscapeDataString([string]$item.Key)
                $valueEncoded = [System.Uri]::EscapeDataString([string]$item.Value)
                "$keyEncoded=$valueEncoded"
            }
            $uriBuilder.Query = ($queryItems -join '&')
        } else {
            $uriBuilder.Query = $null
        }

        $requestUri = $uriBuilder.Uri.AbsoluteUri

        try {
            Write-Verbose "Calling $requestUri"
            $response = Invoke-RestMethod -Uri $requestUri -Headers $Config.Headers -Method Get -TimeoutSec 30
            Start-Sleep -Milliseconds 250
            return $response
        }
        catch {
            $statusCode = $_.Exception.Response?.StatusCode?.value__
            Write-Warning "Alma API call failed (attempt $attempt/$MaxRetries) for $Endpoint : $($_.Exception.Message)"

            if ($statusCode -eq 429 -and $attempt -lt $MaxRetries) {
                $backoff = [Math]::Pow(2, $attempt) * 500
                Start-Sleep -Milliseconds $backoff
                continue
            }

            if ($statusCode -ge 500 -and $attempt -lt $MaxRetries) {
                Start-Sleep -Seconds 2
                continue
            }

            throw
        }
    } while ($attempt -lt $MaxRetries)
}

function Get-PatronsByGroup {
    param(
        [string]$GroupCode,
        [hashtable]$Config
    )

    Write-Section -Title "Querying group: $GroupCode"

    $results = @()
    $limit = 100
    $offset = 0
    $moreResults = $true

    while ($moreResults) {
        Write-Host "  → Fetching offset $offset" -ForegroundColor DarkGray

        $escapedGroup = $GroupCode.Replace('"', '""')
        $groupQueryValue = if ($GroupCode -match '\s') {
            "user_group~`"$escapedGroup`""
        } else {
            "user_group~$escapedGroup"
        }

        $params = @{
            q      = $groupQueryValue
            limit  = $limit
            offset = $offset
            view   = 'brief'
            expand = 'none'
            status = 'ALL'
            format = 'json'
        }

        $response = Invoke-AlmaApi -Endpoint "/users" -QueryParams $params -Config $Config

        if (-not $response) {
            Write-Warning "No response returned for group $GroupCode"
            break
        }

        $usersNode = $null
        if ($response.PSObject.Properties.Name -contains 'user') {
            $usersNode = $response.user
        } elseif ($response.PSObject.Properties.Name -contains 'users' -and $response.users.PSObject.Properties.Name -contains 'user') {
            $usersNode = $response.users.user
        }

        $users = @()
        if ($usersNode) {
            $users = @($usersNode) | Where-Object { $_ }
        }

        if ($users.Count -eq 0) {
            Write-Host "No patrons returned for this page." -ForegroundColor Yellow
            break
        }

        $results += $users
        $offset += $limit

        $totalCount = 0
        if ($response.PSObject.Properties.Name -contains 'total_record_count') {
            [void][int]::TryParse([string]$response.total_record_count, [ref]$totalCount)
        } elseif ($response.PSObject.Properties.Name -contains 'total-record-count') {
            [void][int]::TryParse([string]$response."total-record-count", [ref]$totalCount)
        }

        if ($totalCount -gt 0) {
            $moreResults = $offset -lt $totalCount
        } else {
            $moreResults = ($users.Count -eq $limit)
        }
    }

    Write-Host "Fetched $($results.Count) patrons for group $GroupCode" -ForegroundColor Green
    return $results
}

function Select-PrimaryIdentifier {
    param([object]$User)

    if ($User.PSObject.Properties.Name -contains 'primary_id' -and $User.primary_id) {
        return [string]$User.primary_id
    }

    if ($User.PSObject.Properties.Name -contains 'primary-id' -and $User."primary-id") {
        return [string]$User."primary-id"
    }

    if ($User.PSObject.Properties.Name -contains 'identifiers') {
        $identifiersNode = $User.identifiers.identifier
        if (-not $identifiersNode -and $User.identifiers.PSObject.Properties.Name -contains 'identifier') {
            $identifiersNode = $User.identifiers.identifier
        }

        $identifierList = @($identifiersNode) | Where-Object { $_ }
        if ($identifierList.Count -gt 0) {
            $primary = $identifierList | Where-Object {
                ($_.id_type.value -eq 'PRIMARY') -or ($_.type?.value -eq 'PRIMARY') -or ($_.id_type.value -eq '01')
            } | Select-Object -First 1

            if ($primary) {
                return [string]$primary.value
            }

            return [string]$identifierList[0].value
        }
    }

    return $null
}

#endregion

#region Main Script

Write-Header -Title $ScriptName
Write-Host "Version $ScriptVersion" -ForegroundColor DarkGray

$patronGroups = @(
    'AdHoc',
    'HELINUndergraduate',
    'Internal',
    'Visiting Faculty',
    'HighSchool'
)

$almaConfig = Get-AlmaConfiguration

$allRows = @()

foreach ($group in $patronGroups) {
    $resolvedGroup = Resolve-GroupCode -Group $group

    if ($resolvedGroup -ne $group) {
        Write-Host "Resolving group '$group' to code '$resolvedGroup'" -ForegroundColor DarkGray
    }

    $users = Get-PatronsByGroup -GroupCode $resolvedGroup -Config $almaConfig

    foreach ($user in $users) {
        $primaryId = Select-PrimaryIdentifier -User $user
        $statusValue = $null

        if ($user.status -is [string]) {
            $statusValue = $user.status
        } elseif ($user.status.PSObject.Properties.Name -contains 'value') {
            $statusValue = $user.status.value
        }

        $row = [PSCustomObject]@{
            PatronGroup   = $group
            PrimaryId     = $primaryId
            FullName      = $user.full_name
            FirstName     = $user.first_name
            LastName      = $user.last_name
            PreferredName = $user.preferred_name
            Status        = $statusValue
        }

        $allRows += $row
    }
}

if ($allRows.Count -eq 0) {
    Write-Warning "No patron identifiers were retrieved. Please verify the patron groups and API filters."
} else {
    $outputFile = Join-Path -Path $PSScriptRoot -ChildPath ("PatronIdentifiers_{0}.csv" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
    $allRows | Sort-Object PatronGroup, PrimaryId | Export-Csv -Path $outputFile -NoTypeInformation
    Write-Host "✅ Identifiers exported to $outputFile" -ForegroundColor Green
}

#endregion