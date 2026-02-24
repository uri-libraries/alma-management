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

	"github.com/joho/godotenv"
)

// User represents a user from the Alma API (simplified)
type User struct {
	PrimaryID      string           `json:"primary_id"`
	ContactInfo    ContactInfo      `json:"contact_info"`
	UserIdentifier []UserIdentifier `json:"user_identifier"`
}

// ContactInfo contains user's contact details
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
}

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

func getUser(userID, apiKey, baseURL string) (*User, error) {
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

	var user User
	if err := json.NewDecoder(resp.Body).Decode(&user); err != nil {
		return nil, err
	}
	return &user, nil
}

func updateUserIdentifier(user *User, uriEmail, apiKey, baseURL string) (*User, error) {
	identifierExists := false
	for _, identifier := range user.UserIdentifier {
		if identifier.IDType.Value == "INST_ID" && identifier.Value == uriEmail {
			identifierExists = true
			break
		}
	}

	if !identifierExists {
		user.UserIdentifier = append(user.UserIdentifier, UserIdentifier{
			Value:       uriEmail,
			Status:      "ACTIVE",
			IDType:      IDType{Value: "INST_ID", Desc: "Institution ID"},
			SegmentType: "Internal",
		})
	}

	// Deduplicate identifiers
	seen := make(map[string]bool)
	var deduped []UserIdentifier
	for _, ident := range user.UserIdentifier {
		if _, ok := seen[ident.Value]; !ok {
			seen[ident.Value] = true
			deduped = append(deduped, ident)
		}
	}
	user.UserIdentifier = deduped

	url := fmt.Sprintf("%s/almaws/v1/users/%s", baseURL, user.PrimaryID)

	// Create a temporary user object for PUT request, omitting certain fields
	updateData := make(map[string]interface{})
	updateData["primary_id"] = user.PrimaryID
	updateData["contact_info"] = user.ContactInfo
	updateData["user_identifier"] = user.UserIdentifier

	jsonData, err := json.Marshal(updateData)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequest("PUT", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "apikey "+apiKey)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusNoContent {
		body, _ := ioutil.ReadAll(resp.Body)
		return nil, fmt.Errorf("update API returned status %d: %s", resp.StatusCode, string(body))
	}

	// Try to decode response, but it might be empty on success
	var updatedUser User
	if err := json.NewDecoder(resp.Body).Decode(&updatedUser); err != nil {
		// If there's an error (e.g., empty body), return the original user data as confirmation
		return user, nil
	}

	return &updatedUser, nil
}

func main() {
	_ = selectEnvironment()

	apiKey := os.Getenv("ALMA_API_KEY")
	apiBaseURL := os.Getenv("ALMA_API_BASE_URL")

	if apiKey == "" || apiBaseURL == "" {
		log.Fatal("ERROR: Missing ALMA_API_KEY or ALMA_API_BASE_URL in environment file")
	}

	maxUsers := 5
	fmt.Printf("\nFetching %d users from Alma...\n", maxUsers)
	userIDs, err := getUsers(apiKey, apiBaseURL, maxUsers)
	if err != nil {
		log.Fatalf("Error fetching users: %v", err)
	}

	fmt.Printf("Processing %d users...\n", len(userIDs))

	for i, userID := range userIDs {
		fmt.Printf("  [%d/%d] %s\n", i+1, len(userIDs), userID)

		userData, err := getUser(userID, apiKey, apiBaseURL)
		if err != nil {
			log.Printf("    ✗ Error getting user details: %v\n", err)
			continue
		}

		var uriEmail string
		var allEmails []string
		for _, email := range userData.ContactInfo.Email {
			allEmails = append(allEmails, email.EmailAddress)
			if strings.HasSuffix(email.EmailAddress, "@uri.edu") {
				uriEmail = email.EmailAddress
			}
		}
		fmt.Printf("    - All emails: %v\n", allEmails)

		if uriEmail != "" {
			fmt.Printf("      -> Found @uri.edu: %s\n", uriEmail)

			// Check if the identifier already exists before attempting an update
			identifierExists := false
			for _, identifier := range userData.UserIdentifier {
				if identifier.IDType.Value == "INST_ID" && identifier.Value == uriEmail {
					identifierExists = true
					break
				}
			}

			if identifierExists {
				fmt.Printf("      ✓ Identifier %s already exists for user %s. No update needed.\n", uriEmail, userID)
			} else {
				updatedUser, err := updateUserIdentifier(userData, uriEmail, apiKey, apiBaseURL)
				if err != nil {
					log.Printf("      ✗ Error updating user: %v\n", err)
				} else {
					fmt.Printf("      ✓ Updated %s: Added INST_ID = %s\n", updatedUser.PrimaryID, uriEmail)
				}
			}
		} else {
			fmt.Println("      ⚠ No @uri.edu email found")
		}
	}

	fmt.Println("\nDone!")
}
