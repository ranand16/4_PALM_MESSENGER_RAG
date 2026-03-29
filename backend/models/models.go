package models

import "time"

// Notification represents a single notification from the Android app.
type Notification struct {
	PackageName string `json:"package_name"`
	Title       string `json:"title"`
	Text        string `json:"text"`
	BigText     string `json:"big_text,omitempty"`
	Timestamp   int64  `json:"timestamp"`
	DeviceID    string `json:"device_id,omitempty"`
}

// NotificationBatch is the payload sent by the Android app.
type NotificationBatch struct {
	Notifications []Notification `json:"notifications"`
	DeviceID      string         `json:"device_id,omitempty"`
	SentAt        int64          `json:"sent_at,omitempty"`
}

// StoredNotification is a notification enriched with metadata for storage.
type StoredNotification struct {
	ID          string    `json:"id"`
	PackageName string    `json:"package_name"`
	AppName     string    `json:"app_name"`
	Title       string    `json:"title"`
	Text        string    `json:"text"`
	Timestamp   int64     `json:"timestamp"`
	StoredAt    time.Time `json:"stored_at"`
	Summarized  bool      `json:"summarized"`
}

// DigestGroup groups notifications by app for email rendering.
type DigestGroup struct {
	AppName       string
	Notifications []StoredNotification
	Summary       string
}

// DigestData holds all data needed to render the email template.
type DigestData struct {
	Groups      []DigestGroup
	GeneratedAt time.Time
	TotalCount  int
}

// AppNameMap maps Android package names to human-readable app names.
var AppNameMap = map[string]string{
	"com.whatsapp":                      "WhatsApp",
	"com.whatsapp.w4b":                  "WhatsApp Business",
	"org.telegram.messenger":            "Telegram",
	"org.thoughtcrime.securesms":        "Signal",
	"com.google.android.apps.messaging": "Messages",
	"com.facebook.orca":                 "Messenger",
	"com.instagram.android":             "Instagram",
	"com.slack":                         "Slack",
	"com.discord":                       "Discord",
	"com.google.android.gm":             "Gmail",
}

// ResolveAppName returns a human-readable app name for a package name.
func ResolveAppName(packageName string) string {
	if name, ok := AppNameMap[packageName]; ok {
		return name
	}
	return packageName
}
