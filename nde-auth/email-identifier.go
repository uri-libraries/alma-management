package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/joho/godotenv"
)

// User represents a user from Alma API with relevant fields only
type User struct {
	PrimaryID      string           `json:"primary_id"`
	ContactInfo    ContactInfo      `json:"contact_info"`
	UserIdentifier []UserIdentifier `json:"user_identifier"`
}

// ContactInfo contains user's email address FROM contact info section of the API response
type ContactInfo struct {
	Email []Email `json:"email"`
}

// Email represents an email address
type Email struct {
	EmailAddress string `json:"email_address"`
}

// UserIdentifier represents a user identifier
type UserIdentifier struct {
	IDType      IDType `json:"id_type"`
	Value       string `json:"value"`
	Status      string `json:"status,omitempty"`
	SegmentType string `json:"segment_type,omitempty"`
}

// IDType represents the type of an identifier
type IDType struct {
	Value string `json:"value"`
	Desc  string `json:"desc,omitempty"`
}

// UsersResponse is the response from the /users endpoint
type UsersResponse struct {
	User []struct {
		PrimaryID string `json:"primary_id"`
	} `json:"user"`
	TotalRecordCount int `json:"total_record_count"`
}

const (
	numWorkers   = 15  // parallel goroutines
	maxReqPerSec = 20  // Alma API rate limit (requests/sec)
	pageSize     = 100 // users per page when fetching IDs
	resumeFile   = "processed_users.log"
)

// startRateLimiter returns a channel that emits one token per request slot
// at the given rate. Each HTTP call should consume one token.
func startRateLimiter(perSecond int) <-chan struct{} {
	ch := make(chan struct{}, perSecond)
	interval := time.Second / time.Duration(perSecond)
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for range ticker.C {
			ch <- struct{}{}
		}
	}()
	return ch
}

// getAllUserIDs paginates through all Alma users and returns every primary_id.
func getAllUserIDs(apiKey, baseURL string, rl <-chan struct{}) ([]string, error) {
	var all []string
	offset := 0
	total := -1
	for total == -1 || offset < total {
		<-rl
		url := fmt.Sprintf("%s/almaws/v1/users?limit=%d&offset=%d", baseURL, pageSize, offset)
		req, err := http.NewRequest("GET", url, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", "apikey "+apiKey)
		req.Header.Set("Accept", "application/json")

		client := &http.Client{}
		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}

		if resp.StatusCode != http.StatusOK {
			body, _ := ioutil.ReadAll(resp.Body)
			resp.Body.Close()
			return nil, fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(body))
		}

		var ur UsersResponse
		if err := json.NewDecoder(resp.Body).Decode(&ur); err != nil {
			resp.Body.Close()
			return nil, err
		}
		resp.Body.Close()

		for _, u := range ur.User {
			if strings.HasPrefix(u.PrimaryID, "no primary id") {
				continue
			}
			all = append(all, u.PrimaryID)
		}
		if total == -1 {
			total = ur.TotalRecordCount
			fmt.Printf("  Total users in Alma: %d\n", total)
		}
		offset += pageSize
		fmt.Printf("  Fetched %d / %d user IDs...\r", len(all), total)
	}
	fmt.Println()
	return all, nil
}

// loadProcessedUsers reads the resume log and returns the set of already-processed IDs.
func loadProcessedUsers(filename string) map[string]bool {
	processed := make(map[string]bool)
	f, err := os.Open(filename)
	if err != nil {
		return processed
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		parts := strings.SplitN(strings.TrimSpace(scanner.Text()), "\t", 2)
		if len(parts) >= 1 && parts[0] != "" {
			processed[parts[0]] = true
		}
	}
	return processed
}

// markProcessed appends a completed user ID and outcome to the resume log.
func markProcessed(f *os.File, mu *sync.Mutex, userID, status string) {
	mu.Lock()
	defer mu.Unlock()
	fmt.Fprintf(f, "%s\t%s\n", userID, status)
}

// processUser handles the full GET → check → PUT flow for one user.
func processUser(userID, apiKey, baseURL string, rl <-chan struct{}, logFile *os.File, mu *sync.Mutex, done, total *int64) {
	n := atomic.AddInt64(done, 1)
	t := atomic.LoadInt64(total)

	// Rate-limit the GET
	<-rl
	userData, err := getUser(userID, apiKey, baseURL)
	if err != nil {
		log.Printf("  [%d/%d] ✗ [%s] Error fetching user: %v\n", n, t, userID, err)
		markProcessed(logFile, mu, userID, "ERROR_GET")
		return
	}

	primaryID, _ := userData["primary_id"].(string)

	existingIDs, err := extractIdentifiers(userData)
	if err != nil {
		log.Printf("  [%d/%d] ✗ [%s] Error extracting identifiers: %v\n", n, t, userID, err)
		markProcessed(logFile, mu, userID, "ERROR_EXTRACT")
		return
	}

	allEmails := extractEmails(userData)
	var uriEmail string
	for _, e := range allEmails {
		if strings.HasSuffix(e, "@uri.edu") {
			uriEmail = e
			break
		}
	}

	if uriEmail == "" {
		markProcessed(logFile, mu, userID, "NO_URI_EMAIL")
		return
	}

	for _, ident := range existingIDs {
		if ident.IDType.Value == "EMAIL" && ident.Value == uriEmail {
			fmt.Printf("  [%d/%d] ✓ [%s] EMAIL identifier already exists\n", n, t, userID)
			markProcessed(logFile, mu, userID, "ALREADY_EXISTS")
			return
		}
	}

	for _, ident := range existingIDs {
		if ident.Value == uriEmail && ident.IDType.Value != "EMAIL" {
			fmt.Printf("  [%d/%d] ⚠ [%s] Skipping: %s already exists as %s\n", n, t, userID, uriEmail, ident.IDType.Value)
			markProcessed(logFile, mu, userID, "VALUE_CONFLICT:"+ident.IDType.Value)
			return
		}
	}

	// Rate-limit the PUT
	<-rl
	if err := updateUserIdentifier(userData, primaryID, uriEmail, apiKey, baseURL); err != nil {
		log.Printf("  [%d/%d] ✗ [%s] Error updating: %v\n", n, t, userID, err)
		markProcessed(logFile, mu, userID, "ERROR_PUT")
	} else {
		fmt.Printf("  [%d/%d] ✓ [%s] Added EMAIL = %s\n", n, t, userID, uriEmail)
		markProcessed(logFile, mu, userID, "UPDATED")
	}
}

// Sandbox / Prod prompt loading the appropriat .env file based on user selection
func selectEnvironment() string {
	fmt.Println("\nSelect environment:")
	fmt.Println("1. Sandbox")
	fmt.Println("2. Production")

	reader := bufio.NewReader(os.Stdin)
	for {
		fmt.Print("\nEnter your choice (1 or 2): ")
		choice, _ := reader.ReadString('\n')
		choice = strings.TrimSpace(choice)
		if choice == "1" {
			err := godotenv.Load(".env.sandbox")
			if err != nil {
				log.Println("Warning: .env.sandbox file not found, but continuing.")
			}
			fmt.Println("✓ Using SANDBOX environment")
			return "sandbox"
		} else if choice == "2" {
			err := godotenv.Load(".env")
			if err != nil {
				log.Println("Warning: .env file not found, but continuing.")
			}
			fmt.Println("✓ Using PRODUCTION environment")
			return "prod"
		} else {
			fmt.Println("Invalid choice. Please enter 1 or 2.")
		}
	}
}

// getUsers fetches a list of user IDs from the Alma API with a specified limit
func getUsers(apiKey, baseURL string, limit int) ([]string, error) {
	url := fmt.Sprintf("%s/almaws/v1/users?limit=%d&offset=0", baseURL, limit)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "apikey "+apiKey)
	req.Header.Set("Accept", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := ioutil.ReadAll(resp.Body)
		return nil, fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(body))
	}

	var usersResponse UsersResponse
	if err := json.NewDecoder(resp.Body).Decode(&usersResponse); err != nil {
		return nil, err
	}

	var userIDs []string
	for _, user := range usersResponse.User {
		userIDs = append(userIDs, user.PrimaryID)
	}
	return userIDs, nil
}

// getUser fetches detailed information for a specific user by ID as raw JSON,
// preserving all fields so nothing is dropped on the PUT request.
func getUser(userID, apiKey, baseURL string) (map[string]interface{}, error) {
	url := fmt.Sprintf("%s/almaws/v1/users/%s", baseURL, userID)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "apikey "+apiKey)
	req.Header.Set("Accept", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API returned status %d for user %s", resp.StatusCode, userID)
	}

	var raw map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
		return nil, err
	}
	return raw, nil
}

// extractIdentifiers pulls the user_identifier array out of a raw user map.
func extractIdentifiers(raw map[string]interface{}) ([]UserIdentifier, error) {
	b, err := json.Marshal(raw["user_identifier"])
	if err != nil {
		return nil, err
	}
	var ids []UserIdentifier
	if err := json.Unmarshal(b, &ids); err != nil {
		return nil, err
	}
	return ids, nil
}

// extractEmails pulls email addresses out of a raw user map.
func extractEmails(raw map[string]interface{}) []string {
	ci, ok := raw["contact_info"].(map[string]interface{})
	if !ok {
		return nil
	}
	b, err := json.Marshal(ci["email"])
	if err != nil {
		return nil
	}
	var emails []Email
	if err := json.Unmarshal(b, &emails); err != nil {
		return nil
	}
	var out []string
	for _, e := range emails {
		out = append(out, e.EmailAddress)
	}
	return out
}

// updateUserIdentifier adds an EMAIL identifier to the raw user map and PUTs it back to Alma.
func updateUserIdentifier(raw map[string]interface{}, primaryID, uriEmail, apiKey, baseURL string) error {
	existingIDs, err := extractIdentifiers(raw)
	if err != nil {
		return fmt.Errorf("failed to extract identifiers: %w", err)
	}

	// Build updated identifier list: keep existing (excluding primary_id duplicates),
	// deduplicate by type+value, then append the new EMAIL identifier.
	seen := make(map[string]bool)
	var updated []UserIdentifier
	for _, ident := range existingIDs {
		if ident.Value == primaryID {
			continue
		}
		key := ident.IDType.Value + "|" + ident.Value
		if !seen[key] {
			seen[key] = true
			updated = append(updated, ident)
		}
	}
	updated = append(updated, UserIdentifier{
		Value:       uriEmail,
		Status:      "ACTIVE",
		IDType:      IDType{Value: "EMAIL", Desc: "Email"},
		SegmentType: "Internal",
	})

	// Patch only user_identifier in the raw map — all other fields stay intact.
	raw["user_identifier"] = updated

	url := fmt.Sprintf("%s/almaws/v1/users/%s", baseURL, primaryID)
	jsonData, err := json.Marshal(raw)
	if err != nil {
		return err
	}

	req, err := http.NewRequest("PUT", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "apikey "+apiKey)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusNoContent {
		body, _ := ioutil.ReadAll(resp.Body)
		return fmt.Errorf("update API returned status %d: %s", resp.StatusCode, string(body))
	}
	return nil
}

// getIdentifierTypes prints the available user identifier type codes from Alma
func getIdentifierTypes(apiKey, baseURL string) {
	url := fmt.Sprintf("%s/almaws/v1/conf/code-tables/UserIdentifierTypes", baseURL)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		log.Printf("Error creating request: %v", err)
		return
	}
	req.Header.Set("Authorization", "apikey "+apiKey)
	req.Header.Set("Accept", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("Error fetching identifier types: %v", err)
		return
	}
	defer resp.Body.Close()

	body, _ := ioutil.ReadAll(resp.Body)
	fmt.Println(string(body))
}

// main function orchestrates the flow with pagination, a worker pool, rate limiting, and resume support.
func main() {
	_ = selectEnvironment()

	apiKey := os.Getenv("ALMA_API_KEY")
	apiBaseURL := os.Getenv("ALMA_API_BASE_URL")

	if apiKey == "" || apiBaseURL == "" {
		log.Fatal("ERROR: Missing ALMA_API_KEY or ALMA_API_BASE_URL in environment file")
	}

	// Start rate limiter
	rl := startRateLimiter(maxReqPerSec)

	// Fetch all user IDs via pagination
	fmt.Println("\nFetching all user IDs from Alma (paginating)...")
	start := time.Now()
	userIDs, err := getAllUserIDs(apiKey, apiBaseURL, rl)
	if err != nil {
		log.Fatalf("Error fetching user IDs: %v", err)
	}
	fmt.Printf("Fetched %d user IDs in %s\n", len(userIDs), time.Since(start).Round(time.Second))

	// Load resume log and filter out already-processed users
	processed := loadProcessedUsers(resumeFile)
	if len(processed) > 0 {
		fmt.Printf("Resuming: skipping %d already-processed users (from %s)\n", len(processed), resumeFile)
	}
	var pending []string
	for _, id := range userIDs {
		if !processed[id] {
			pending = append(pending, id)
		}
	}
	fmt.Printf("Processing %d users with %d workers at %d req/sec...\n\n", len(pending), numWorkers, maxReqPerSec)

	// Open resume log file (append mode)
	logFile, err := os.OpenFile(resumeFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Fatalf("Error opening resume log: %v", err)
	}
	defer logFile.Close()

	var mu sync.Mutex
	var done, total int64
	total = int64(len(pending))

	// Worker pool
	work := make(chan string, numWorkers*2)
	var wg sync.WaitGroup
	for i := 0; i < numWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for userID := range work {
				processUser(userID, apiKey, apiBaseURL, rl, logFile, &mu, &done, &total)
			}
		}()
	}

	runStart := time.Now()
	for _, id := range pending {
		work <- id
	}
	close(work)
	wg.Wait()

	fmt.Printf("\nDone! Processed %d users in %s\n", len(pending), time.Since(runStart).Round(time.Second))
	fmt.Printf("Results saved to %s\n", resumeFile)
}
