package config

import (
	"os"
	"strconv"
)

type Config struct {
	// Qdrant
	QdrantHost       string
	QdrantPort       int
	QdrantCollection string

	// Ollama
	OllamaURL        string
	OllamaEmbedModel string
	OllamaChatModel  string

	// Email
	SMTPHost     string
	SMTPPort     int
	SMTPUser     string
	SMTPPassword string
	EmailTo      string
	EmailFrom    string

	// Auth
	APIKey string

	// Scheduler
	DigestIntervalHours int
	DigestStartHour     int
	DigestEndHour       int

	// Server
	ServerPort int
}

func Load() *Config {
	return &Config{
		QdrantHost:       getEnv("QDRANT_HOST", "localhost"),
		QdrantPort:       getEnvInt("QDRANT_PORT", 6334),
		QdrantCollection: getEnv("QDRANT_COLLECTION", "notifications"),

		OllamaURL:        getEnv("OLLAMA_URL", "http://localhost:11434"),
		OllamaEmbedModel: getEnv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
		OllamaChatModel:  getEnv("OLLAMA_CHAT_MODEL", "mistral:7b"),

		SMTPHost:     getEnv("SMTP_HOST", "smtp.gmail.com"),
		SMTPPort:     getEnvInt("SMTP_PORT", 587),
		SMTPUser:     getEnv("SMTP_USER", ""),
		SMTPPassword: getEnv("SMTP_PASSWORD", ""),
		EmailTo:      getEnv("EMAIL_TO", ""),
		EmailFrom:    getEnv("EMAIL_FROM", ""),

		APIKey: getEnv("API_KEY", "change-me"),

		DigestIntervalHours: getEnvInt("DIGEST_INTERVAL_HOURS", 2),
		DigestStartHour:     getEnvInt("DIGEST_START_HOUR", 9),
		DigestEndHour:       getEnvInt("DIGEST_END_HOUR", 19),

		ServerPort: getEnvInt("SERVER_PORT", 8000),
	}
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if i, err := strconv.Atoi(v); err == nil {
			return i
		}
	}
	return fallback
}
