package rag

import (
	"context"
	"fmt"
	"log"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/ranand16/palm-messenger-rag/config"
	"github.com/ranand16/palm-messenger-rag/models"
	"github.com/ranand16/palm-messenger-rag/ollama"
	"github.com/ranand16/palm-messenger-rag/store"
)

// Pipeline orchestrates the RAG workflow: embed, store, retrieve, summarize.
type Pipeline struct {
	store  *store.Store
	ollama *ollama.Client
	cfg    *config.Config
}

func NewPipeline(s *store.Store, o *ollama.Client, cfg *config.Config) *Pipeline {
	return &Pipeline{store: s, ollama: o, cfg: cfg}
}

// Ingest embeds and stores a batch of notifications.
func (p *Pipeline) Ingest(ctx context.Context, notifications []models.Notification) (int, error) {
	stored := 0
	for _, n := range notifications {
		// Build text to embed: combine title and text
		embedText := n.Title
		if n.Text != "" {
			embedText += ": " + n.Text
		}
		if n.BigText != "" {
			embedText = n.Title + ": " + n.BigText
		}

		// Skip empty notifications
		if strings.TrimSpace(embedText) == "" {
			continue
		}

		// Generate embedding
		vector, err := p.ollama.Embed(ctx, p.cfg.OllamaEmbedModel, embedText)
		if err != nil {
			log.Printf("Failed to embed notification from %s: %v", n.PackageName, err)
			continue
		}

		// Build stored notification
		sn := models.StoredNotification{
			ID:          uuid.New().String(),
			PackageName: n.PackageName,
			AppName:     models.ResolveAppName(n.PackageName),
			Title:       n.Title,
			Text:        bestText(n),
			Timestamp:   n.Timestamp,
			StoredAt:    time.Now(),
			Summarized:  false,
		}

		if err := p.store.Upsert(ctx, sn, vector); err != nil {
			log.Printf("Failed to store notification: %v", err)
			continue
		}
		stored++
	}

	return stored, nil
}

// GenerateDigest produces a digest of recent notifications using RAG.
func (p *Pipeline) GenerateDigest(ctx context.Context, sinceHours int) (*models.DigestData, error) {
	// 1. Retrieve recent notifications from Qdrant
	notifications, err := p.store.QueryRecent(ctx, sinceHours)
	if err != nil {
		return nil, fmt.Errorf("query recent notifications: %w", err)
	}

	if len(notifications) == 0 {
		return &models.DigestData{
			Groups:      nil,
			GeneratedAt: time.Now(),
			TotalCount:  0,
		}, nil
	}

	// 2. Group by app
	groups := groupByApp(notifications)

	// 3. For each group, generate an AI summary using RAG
	var digestGroups []models.DigestGroup
	for appName, notifs := range groups {
		// Sort by timestamp descending
		sort.Slice(notifs, func(i, j int) bool {
			return notifs[i].Timestamp > notifs[j].Timestamp
		})

		// Build context from notifications
		var msgLines []string
		for _, n := range notifs {
			t := time.UnixMilli(n.Timestamp).Format("15:04")
			line := fmt.Sprintf("[%s] %s: %s", t, n.Title, n.Text)
			msgLines = append(msgLines, line)
		}
		messagesContext := strings.Join(msgLines, "\n")

		// Optional: retrieve semantically similar older messages for richer context
		var ragContext string
		if len(notifs) > 0 {
			sampleText := notifs[0].Title + ": " + notifs[0].Text
			sampleVec, err := p.ollama.Embed(ctx, p.cfg.OllamaEmbedModel, sampleText)
			if err == nil {
				similar, err := p.store.SearchSimilar(ctx, sampleVec, 5)
				if err == nil && len(similar) > 0 {
					var oldLines []string
					for _, s := range similar {
						oldLines = append(oldLines, fmt.Sprintf("- %s: %s", s.Title, s.Text))
					}
					ragContext = "\n\nRelated older messages:\n" + strings.Join(oldLines, "\n")
				}
			}
		}

		// Generate summary with LLM
		systemPrompt := `You are a notification digest assistant. Summarize the following messages concisely.
Group related conversations together. Highlight important or urgent messages.
Keep the summary brief but informative. Use bullet points.
Do not add any information that is not in the messages.`

		userPrompt := fmt.Sprintf("App: %s\nRecent messages:\n%s%s\n\nProvide a concise summary of these messages:",
			appName, messagesContext, ragContext)

		summary, err := p.ollama.Chat(ctx, p.cfg.OllamaChatModel, systemPrompt, userPrompt)
		if err != nil {
			log.Printf("Failed to summarize %s: %v, using raw messages", appName, err)
			summary = messagesContext // fallback to raw messages
		}

		digestGroups = append(digestGroups, models.DigestGroup{
			AppName:       appName,
			Notifications: notifs,
			Summary:       summary,
		})
	}

	// Sort groups by name for consistent ordering
	sort.Slice(digestGroups, func(i, j int) bool {
		return digestGroups[i].AppName < digestGroups[j].AppName
	})

	return &models.DigestData{
		Groups:      digestGroups,
		GeneratedAt: time.Now(),
		TotalCount:  len(notifications),
	}, nil
}

func groupByApp(notifications []models.StoredNotification) map[string][]models.StoredNotification {
	groups := make(map[string][]models.StoredNotification)
	for _, n := range notifications {
		groups[n.AppName] = append(groups[n.AppName], n)
	}
	return groups
}

func bestText(n models.Notification) string {
	if n.BigText != "" {
		return n.BigText
	}
	return n.Text
}
