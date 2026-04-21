package main

import (
	"bufio"
	"crypto/tls"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	requestTimeout = 30 * time.Second
	pageLimit      = 50
	quickScanLimit = 1000 // set to 0 to disable
	debugSample    = false
)

type usersResponse struct {
	Users            []map[string]any `json:"user"`
	TotalRecordCount int              `json:"total_record_count"`
}

type expiredUserRow struct {
	PrimaryID      string `json:"primary_id"`
	FirstName      string `json:"first_name"`
	LastName       string `json:"last_name"`
	Email          string `json:"email"`
	PatronType     string `json:"patron_type"`
	ExpirationDate string `json:"expiration_date"`
}

func main() {
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println("ALMA EXPIRATION CHECKER (Go)")
	fmt.Println(strings.Repeat("=", 60))

	environment, err := selectEnvironment()
	if err != nil {
		fmt.Println("Error:", err)
		os.Exit(1)
	}

	apiKey := strings.TrimSpace(os.Getenv("ALMA_API_KEY"))
	baseURL := strings.TrimSpace(os.Getenv("ALMA_API_BASE_URL"))
	if apiKey == "" || baseURL == "" {
		fmt.Println("Error: ALMA_API_KEY and ALMA_API_BASE_URL must be set in the chosen .env")
		os.Exit(1)
	}

	cutoff := promptForDate()
	fmt.Printf("\nFinding users expired on or before %s...\n", cutoff.Format(time.RFC3339))

	rows, scanned, err := collectExpiredUsers(apiKey, baseURL, cutoff, quickScanLimit)
	if err != nil {
		fmt.Println("Error:", err)
		os.Exit(1)
	}

	fmt.Printf("\nScanned %d users; found %d expired users\n", scanned, len(rows))

	if len(rows) > 0 {
		csvFile, err := saveCSV(rows, environment)
		if err != nil {
			fmt.Println("Error saving CSV:", err)
			os.Exit(1)
		}

		jsonFile, err := saveJSON(rows, environment)
		if err != nil {
			fmt.Println("Error saving JSON:", err)
			os.Exit(1)
		}

		fmt.Printf("\nSaved CSV: %s\n", csvFile)
		fmt.Printf("Saved JSON: %s\n", jsonFile)
	} else {
		fmt.Println("\nNo expired users found for that cutoff date.")
	}

	fmt.Println("\nDone!")
}

func selectEnvironment() (string, error) {
	scanner := bufio.NewScanner(os.Stdin)
	fmt.Println("\nSelect environment:")
	fmt.Println("1. Production")
	fmt.Println("2. Sandbox")

	for {
		fmt.Print("\nEnter choice (1 or 2): ")
		if !scanner.Scan() {
			return "", fmt.Errorf("failed to read input")
		}
		choice := strings.TrimSpace(scanner.Text())

		switch choice {
		case "1":
			path, err := findEnvFile(".env")
			if err != nil {
				return "", err
			}
			if err := loadDotEnv(path); err != nil {
				return "", err
			}
			fmt.Println("Loaded Production environment")
			return "production", nil
		case "2":
			path, err := findEnvFile(".env.sandbox")
			if err != nil {
				return "", err
			}
			if err := loadDotEnv(path); err != nil {
				return "", err
			}
			fmt.Println("Loaded Sandbox environment")
			return "sandbox", nil
		default:
			fmt.Println("Invalid choice. Please enter 1 or 2.")
		}
	}
}

func promptForDate() time.Time {
	scanner := bufio.NewScanner(os.Stdin)
	for {
		fmt.Print("\nEnter cutoff date (YYYY-MM-DD) for users expired on or before that date: ")
		if !scanner.Scan() {
			fmt.Println("Input cancelled.")
			os.Exit(1)
		}
		s := strings.TrimSpace(scanner.Text())
		d, err := time.Parse("2006-01-02", s)
		if err != nil {
			fmt.Println("Invalid date format. Use YYYY-MM-DD.")
			continue
		}
		return time.Date(d.Year(), d.Month(), d.Day(), 23, 59, 59, 0, time.Local)
	}
}

func findEnvFile(name string) (string, error) {
	searchDirs := []string{".", "..", "../..", "../../.."}
	for _, dir := range searchDirs {
		candidate := filepath.Clean(filepath.Join(dir, name))
		if _, err := os.Stat(candidate); err == nil {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("%s file not found", name)
}

func loadDotEnv(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "export ") {
			line = strings.TrimSpace(strings.TrimPrefix(line, "export "))
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])
		value = strings.Trim(value, `"'`)
		if key != "" {
			_ = os.Setenv(key, value)
		}
	}
	return scanner.Err()
}

func collectExpiredUsers(apiKey, baseURL string, cutoff time.Time, maxProcessed int) ([]expiredUserRow, int, error) {
	results := make([]expiredUserRow, 0)
	count := 0
	offset := 0
	client := newHTTPClient()

	if maxProcessed > 0 {
		fmt.Printf("Quick-scan limiter active: will stop after %d users\n", maxProcessed)
	}

	for {
		fmt.Printf("Fetching users: offset=%d limit=%d\n", offset, pageLimit)
		data, err := fetchUsersPage(client, apiKey, baseURL, offset, pageLimit)
		if err != nil {
			return results, count, err
		}

		fmt.Printf("  Received %d users\n", len(data.Users))
		if len(data.Users) == 0 {
			break
		}

		for _, user := range data.Users {
			count++
			if debugSample && count == 1 {
				b, _ := json.MarshalIndent(user, "", "  ")
				fmt.Println("\n--- Debug: sample user (first returned) ---")
				fmt.Println(string(b))
			}
			if maxProcessed > 0 && count > maxProcessed {
				fmt.Printf("Reached scanning limit (%d) - stopping early\n", maxProcessed)
				return results, count - 1, nil
			}

			primaryID := firstString(user, "primary_id", "primaryId", "primary")
			firstName := firstString(user, "first_name", "firstName")
			lastName := firstString(user, "last_name", "lastName")
			expiration := extractUserExpiration(user)
			email := extractEmailFromContact(user["contact_info"])
			patronType := extractPatronType(user["user_group"])

			if expiration != nil && !expiration.After(cutoff) {
				results = append(results, expiredUserRow{
					PrimaryID:      primaryID,
					FirstName:      firstName,
					LastName:       lastName,
					Email:          email,
					PatronType:     patronType,
					ExpirationDate: expiration.Format(time.RFC3339),
				})
			}
		}

		offset += pageLimit
		if data.TotalRecordCount > 0 && offset >= data.TotalRecordCount {
			break
		}
		if len(data.Users) < pageLimit {
			break
		}

		time.Sleep(200 * time.Millisecond)
	}

	return results, count, nil
}

func newHTTPClient() *http.Client {
	transport := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	return &http.Client{
		Timeout:   requestTimeout,
		Transport: transport,
	}
}

func fetchUsersPage(client *http.Client, apiKey, baseURL string, offset, limit int) (*usersResponse, error) {
	endpoint, err := url.Parse(strings.TrimRight(baseURL, "/") + "/almaws/v1/users")
	if err != nil {
		return nil, err
	}

	q := endpoint.Query()
	q.Set("limit", strconv.Itoa(limit))
	q.Set("offset", strconv.Itoa(offset))
	q.Set("format", "json")
	q.Set("expand", "full")
	endpoint.RawQuery = q.Encode()

	req, err := http.NewRequest(http.MethodGet, endpoint.String(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "apikey "+apiKey)
	req.Header.Set("Accept", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed to fetch users: %d %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	var data usersResponse
	if err := json.Unmarshal(body, &data); err != nil {
		return nil, err
	}
	return &data, nil
}

func parseAlmaDate(s string) *time.Time {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}

	if len(s) == len("2006-01-02Z") && strings.HasSuffix(s, "Z") {
		s = strings.TrimSuffix(s, "Z")
	}

	layouts := []string{
		"2006-01-02",
		"2006-01-02Z07:00",
		time.RFC3339Nano,
		time.RFC3339,
		"2006-01-02T15:04:05",
		"2006-01-02T15:04:05.000",
	}

	for _, layout := range layouts {
		if t, err := time.Parse(layout, s); err == nil {
			return &t
		}
	}

	if t, err := time.Parse("2006-01-02T15:04:05Z07:00", s); err == nil {
		return &t
	}

	return nil
}

func extractUserExpiration(user map[string]any) *time.Time {
	if expiration := parseAlmaDate(firstString(user, "expiration_date", "expiry_date", "expirationDate", "expiryDate", "expiration")); expiration != nil {
		return expiration
	}

	roles, ok := user["user_role"].([]any)
	if !ok {
		return nil
	}

	var latest *time.Time
	for _, role := range roles {
		roleMap, ok := role.(map[string]any)
		if !ok {
			continue
		}

		expiration := parseAlmaDate(firstString(roleMap, "expiration_date", "expiry_date", "expirationDate", "expiryDate", "expiration"))
		if expiration == nil {
			continue
		}
		if latest == nil || expiration.After(*latest) {
			latest = expiration
		}
	}

	return latest
}

func extractPatronType(userGroup any) string {
	m, ok := userGroup.(map[string]any)
	if !ok {
		return ""
	}

	if value := stringValue(m["value"]); value != "" {
		return value
	}
	return stringValue(m["desc"])
}

func extractEmailFromContact(contactInfo any) string {
	m, ok := contactInfo.(map[string]any)
	if !ok {
		return ""
	}

	rawEmails, ok := m["email"]
	if !ok {
		return ""
	}

	emails, ok := rawEmails.([]any)
	if !ok || len(emails) == 0 {
		return ""
	}

	for _, item := range emails {
		emailMap, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if preferred, ok := emailMap["preferred"].(bool); ok && preferred {
			return stringValue(emailMap["email_address"])
		}
	}

	if emailMap, ok := emails[0].(map[string]any); ok {
		return stringValue(emailMap["email_address"])
	}
	return ""
}

func firstString(m map[string]any, keys ...string) string {
	for _, key := range keys {
		if val, ok := m[key]; ok {
			if s := stringValue(val); s != "" {
				return s
			}
		}
	}
	return ""
}

func stringValue(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case fmt.Stringer:
		return t.String()
	case nil:
		return ""
	default:
		return fmt.Sprintf("%v", t)
	}
}

func ensureOutputDir() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}

	candidates := []string{
		filepath.Join(cwd, "../outputs"),
		filepath.Join(cwd, "outputs"),
		filepath.Join(cwd, "patron-checker/outputs"),
	}

	for _, candidate := range candidates {
		cleaned := filepath.Clean(candidate)
		if _, err := os.Stat(filepath.Dir(cleaned)); err == nil {
			if err := os.MkdirAll(cleaned, 0o755); err == nil {
				if rel, err := filepath.Rel(cwd, cleaned); err == nil {
					return rel, nil
				}
				return cleaned, nil
			}
		}
	}

	return "", fmt.Errorf("unable to create outputs directory")
}

func saveCSV(rows []expiredUserRow, environment string) (string, error) {
	outputDir, err := ensureOutputDir()
	if err != nil {
		return "", err
	}

	filename := filepath.Join(outputDir, fmt.Sprintf("expired_users_%s_%s.csv", environment, time.Now().Format("20060102_150405")))
	file, err := os.Create(filename)
	if err != nil {
		return "", err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	if err := writer.Write([]string{"primary_id", "first_name", "last_name", "email", "patron_type", "expiration_date"}); err != nil {
		return "", err
	}
	for _, row := range rows {
		if err := writer.Write([]string{row.PrimaryID, row.FirstName, row.LastName, row.Email, row.PatronType, row.ExpirationDate}); err != nil {
			return "", err
		}
	}

	return filename, writer.Error()
}

func saveJSON(rows []expiredUserRow, environment string) (string, error) {
	outputDir, err := ensureOutputDir()
	if err != nil {
		return "", err
	}

	filename := filepath.Join(outputDir, fmt.Sprintf("expired_users_%s_%s.json", environment, time.Now().Format("20060102_150405")))
	file, err := os.Create(filename)
	if err != nil {
		return "", err
	}
	defer file.Close()

	encoder := json.NewEncoder(file)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(rows); err != nil {
		return "", err
	}
	return filename, nil
}
