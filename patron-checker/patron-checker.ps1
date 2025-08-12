# Load environment variables
$envPath = Join-Path $PSScriptRoot ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match "^([^#=]+)=(.*)$") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim('"').Trim("'")
            [System.Environment]::SetEnvironmentVariable($name, $value)
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}
$ALMA_API_KEY = $env:ALMA_API_KEY
$ALMA_API_BASE_URL = $env:ALMA_API_BASE_URL

function Call-AlmaApi {
    param(
        [string]$Endpoint,
        [hashtable]$Params = @{},
        [switch]$SuppressErrors
    )
    $baseUrl = "$ALMA_API_BASE_URL/almaws/v1$Endpoint"
    $headers = @{
        "Accept" = "application/json"
        "Authorization" = "apikey $ALMA_API_KEY"
    }
    $Params["apikey"] = $ALMA_API_KEY
    
    # Build query string
    $queryString = ""
    if ($Params.Count -gt 0) {
        $queryString = ($Params.GetEnumerator() | ForEach-Object { "{0}={1}" -f [uri]::EscapeDataString($_.Key), [uri]::EscapeDataString($_.Value) }) -join "&"
    }
    
    # Construct final URL
    if ($queryString) {
        $url = "$baseUrl" + "?" + "$queryString"
    } else {
        $url = $baseUrl
    }
    
    try {
        $response = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -ContentType "application/json" -ErrorAction Stop
        return $response
    } catch {
        if (-not $SuppressErrors) {
            Write-Host "API error: $($_.Exception.Message)"
        }
        return $null
    }
}

function Get-UserByBarcode {
    param([string]$Barcode)
    Write-Host "`n--- Searching for user with barcode: $Barcode ---"
    $user = Call-AlmaApi "/users/$Barcode"
    if (-not $user) {
        $user = Call-AlmaApi "/users/$Barcode" @{user_id_type="BARCODE"}
    }
    return $user
}

function Search-UsersByName {
    param([string]$FirstName, [string]$LastName)
    Write-Host "`n--- Searching for users with name: $FirstName $LastName ---"
    $params = @{q="last_name~$LastName AND first_name~$FirstName"; limit=10}
    $data = Call-AlmaApi "/users" $params
    if (-not $data.user) {
        Write-Host "No users found."
        return $null
    }
    $users = $data.user
    if ($users.Count -eq 1) {
        Write-Host "Found 1 user."
        $selected_user = $users[0]
    } elseif ($users.Count -gt 1) {
        Write-Host "Found $($users.Count) users:"
        for ($i=0; $i -lt $users.Count; $i++) {
            $u = $users[$i]
            Write-Host "$($i+1). $($u.first_name) $($u.last_name) (ID: $($u.primary_id))"
        }
        while ($true) {
            $choice = Read-Host "Select user (1-$($users.Count)) or 'cancel'"
            if ($choice -eq "cancel") { return $null }
            if ($choice -match '^\d+$' -and $choice -ge 1 -and $choice -le $users.Count) {
                $selected_user = $users[$choice-1]
                break
            }
        }
    }
    
    # Get full user details using primary_id
    $user_id = $selected_user.primary_id
    if ($user_id) {
        Write-Host "Getting full details for user: $user_id"
        $full_user_data = Call-AlmaApi "/users/$user_id"
        return $full_user_data
    } else {
        Write-Host "Could not get primary_id for selected user"
        return $selected_user
    }
}

function Search-UsersByEmail {
    param([string]$Email)
    Write-Host "`n--- Searching for users with email: $Email ---"
    $params = @{q="email~$Email"; limit=10}
    $data = Call-AlmaApi "/users" $params
    if (-not $data.user) {
        Write-Host "No users found."
        return $null
    }
    $users = $data.user
    if ($users.Count -eq 1) {
        Write-Host "Found 1 user."
        $selected_user = $users[0]
    } elseif ($users.Count -gt 1) {
        Write-Host "Found $($users.Count) users:"
        for ($i=0; $i -lt $users.Count; $i++) {
            $u = $users[$i]
            Write-Host "$($i+1). $($u.first_name) $($u.last_name) (ID: $($u.primary_id))"
        }
        while ($true) {
            $choice = Read-Host "Select user (1-$($users.Count)) or 'cancel'"
            if ($choice -eq "cancel") { return $null }
            if ($choice -match '^\d+$' -and $choice -ge 1 -and $choice -le $users.Count) {
                $selected_user = $users[$choice-1]
                break
            }
        }
    }
    
    # Get full user details using primary_id
    $user_id = $selected_user.primary_id
    if ($user_id) {
        Write-Host "Getting full details for user: $user_id"
        $full_user_data = Call-AlmaApi "/users/$user_id"
        return $full_user_data
    } else {
        Write-Host "Could not get primary_id for selected user"
        return $selected_user
    }
}

function Display-UserInfo {
    param($User)
    if (-not $User) { return }
    
    $user_id = $User.primary_id
    if (-not $user_id) {
        Write-Host "No primary ID."
        return
    }
    $full_name = "$($User.first_name) $($User.last_name)"
    
    # Safely get email
    $email = "N/A"
    if ($User.contact_info -and $User.contact_info.email -and $User.contact_info.email.Count -gt 0) {
        $email = $User.contact_info.email[0].email_address
    }
    
    # Safely get patron group
    $patron_group = "N/A"
    if ($User.user_group -and $User.user_group.desc) {
        $patron_group = $User.user_group.desc
    }
    
    Write-Host "`nUser: $full_name (ID: $user_id)"
    Write-Host "  Email: $email"
    Write-Host "  Patron Group: $patron_group"

    # Loans
    $loans = Call-AlmaApi "/users/$user_id/loans"
    $current_loans = 0
    $overdue_loans = 0
    if ($loans -and $loans.item_loan) {
        foreach ($loan in $loans.item_loan) {
            $current_loans++
            if ($loan.due_date) {
                try {
                    $due = [datetime]::Parse($loan.due_date)
                    if ((Get-Date) -gt $due) { $overdue_loans++ }
                } catch {
                    # Skip loans with unparseable dates
                }
            }
        }
    }
    Write-Host "`nLoans: $current_loans, Overdue: $overdue_loans"

    # Fines
    $fees = Call-AlmaApi "/users/$user_id/fees"
    $total_fines = 0
    if ($fees -and $fees.fee) {
        foreach ($fee in $fees.fee) {
            if ($fee.status -and $fee.status.value -eq "ACTIVE") {
                $total_fines += [float]$fee.amount
            }
        }
    }
    Write-Host "`nActive Fines: $($total_fines.ToString("F2"))"

    # Blocks
    Write-Host "`nBlocks:"
    $blocks = $User.user_block
    if ($blocks) {
        $active = $blocks | Where-Object { $_.block_status -eq "ACTIVE" }
        if ($active) {
            foreach ($block in $active) {
                $blockType = if ($block.block_type -and $block.block_type.desc) { $block.block_type.desc } else { "N/A" }
                $blockDesc = if ($block.block_description -and $block.block_description.desc) { $block.block_description.desc } else { "N/A" }
                Write-Host "  Type: $blockType"
                Write-Host "  Description: $blockDesc"
                Write-Host "  Created: $($block.created_date)"
                Write-Host "  Note: $($block.note)"
            }
        } else {
            Write-Host "  No active blocks."
        }
    } else {
        Write-Host "  No blocks."
    }
}

# Main menu
if (-not $ALMA_API_KEY -or -not $ALMA_API_BASE_URL) {
    Write-Host "ERROR: Set ALMA_API_KEY and ALMA_API_BASE_URL environment variables."
    exit 1
}

Write-Host "Welcome to the Alma User Information Script!"
while ($true) {
    Write-Host "`n==============================="
    Write-Host "1. Barcode"
    Write-Host "2. Name (First and Last)"
    Write-Host "3. Email Address"
    Write-Host "4. Quit"
    $choice = Read-Host "Enter your choice (1-4)"
    switch ($choice) {
        "1" {
            $barcode = Read-Host "Enter the barcode"
            if ($barcode) {
                $user = Get-UserByBarcode $barcode
                if ($user) { Display-UserInfo $user }
                else { Write-Host "User not found." }
            }
        }
        "2" {
            $first = Read-Host "Enter the first name"
            $last = Read-Host "Enter the last name"
            if ($first -and $last) {
                $user = Search-UsersByName $first $last
                if ($user) { Display-UserInfo $user }
            }
        }
        "3" {
            $email = Read-Host "Enter the email address"
            if ($email) {
                $user = Search-UsersByEmail $email
                if ($user) { Display-UserInfo $user }
            }
        }
        "4" { exit }
        default { Write-Host "Invalid choice." }
    }
}
Write-Host "`nGoodbye!"