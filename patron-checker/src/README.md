# Patron Checker `src` Scripts

This folder contains operational scripts for Alma user lifecycle workflows, including expiration review, deactivation, purge-date management, and group validation. Most scripts call Alma REST endpoints and read API settings from `.env` (or `.env.sandbox` where supported). Several scripts read local input files in the working directory and write timestamped outputs for audit/review. 

## `add_purge_dates.py`
`add_purge_dates.py` reads `blank-purge-date.csv` and extracts each `Primary ID` to update through the Alma Users API. For each user, it fetches the current record, sets `purge_date`, and sends the full record back with a `PUT` request. The script is currently configured to apply a fixed purge date (`2025-11-30Z`) to every listed user. It prints progress and a success/failure summary so you can confirm how many updates were applied.

## `check_purge_pending.py`
`check_purge_pending.py` reads IDs from `deactivated-all.txt` and looks up each user in Alma. It filters users into those in `PurgePending`/`DEL` versus other groups, then evaluates whether each relevant account is expired. Results are categorized as expired, not yet expired, no expiry date, or failed lookup. It writes a consolidated output file, `purge_pending_analysis.csv`, for reporting and follow-up.

## `deactivate-users.py`
`deactivate-users.py` performs bulk account deactivation by setting user status to `INACTIVE` for IDs listed in `deactivate.txt`. It supports environment selection via `--sandbox` and loads either `.env.sandbox` or `.env` so you can choose whether this runs in Alma Sandbox or Alma prod. It will attempt to normalize data by removing problematic fields, filtering invalid phone types, and deduplicating identifiers to reduce API errors. It saves success, skipped, failure, and summary report files with timestamps so the run can be audited or resumed.

## `expiration-checker.py`
`expiration-checker.py` is an interactive scanner that asks for environment and a cutoff date, then finds users whose expiration is on or before that cutoff. It paginates through Alma users, parses multiple possible expiration date formats, and captures key identity/contact fields for matching records. Matching users are exported to both timestamped CSV and JSON output files. A quick-scan limiter (`QUICK_SCAN_LIMIT`) is built in for partial test runs and can be disabled for full scans.

## `list_user_groups.py`
`list_user_groups.py` retrieves the configured Alma user groups from the configuration API endpoint and prints them in a simple table. It displays each group code alongside its description so you can quickly verify available patron categories. This script is read-only and intended as a lightweight reference/check utility. It requires `ALMA_API_KEY` and `ALMA_API_BASE_URL` in environment configuration.

## `process_facstaff.py`
`process_facstaff.py` reads `fac-staff.csv`, then enriches each `Primary ID` by fetching first name, last name, and preferred email from Alma. It combines those fields with existing CSV values (`Patron Type`, `Purge Date`) into a review-ready output. The script writes the merged results to `facstaffreview.csv`. It also prints periodic progress updates and warnings when individual user lookups fail.

## `purge_date_report.py`
`purge_date_report.py` reads IDs from `deactivated-all.txt` and fetches each user record to collect purge date and patron group information. It writes one row per ID to `purge_date_report.csv` with `Primary ID`, `Purge Date`, and `Patron Type`. During execution, it tracks counts for users with and without a purge date and reports those totals at the end. This makes it useful for post-deactivation cleanup and identifying missing purge metadata.

## `verify_purge_pending.py`
`verify_purge_pending.py` pulls all users currently in the `PurgePending` group and verifies whether their expiration dates have already passed. It classifies each user as expired, not yet expired, missing expiration, or failed fetch, then prints a final compliance-style summary. To support large runs, it persists checkpoint data in `verify_purge_progress.json` and can resume from the last processed index. The script is helpful for validating whether `PurgePending` membership aligns with expiration policy before downstream actions.
