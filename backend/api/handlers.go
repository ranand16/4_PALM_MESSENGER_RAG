package api

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/ranand16/palm-messenger-rag/config"
	"github.com/ranand16/palm-messenger-rag/email"
	"github.com/ranand16/palm-messenger-rag/models"
	"github.com/ranand16/palm-messenger-rag/ollama"
	"github.com/ranand16/palm-messenger-rag/rag"
	"github.com/ranand16/palm-messenger-rag/store"
)

// Handler holds all HTTP handler dependencies.
type Handler struct {
	pipeline *rag.Pipeline
	emailSvc *email.Service
	store    *store.Store
	ollama   *ollama.Client
	cfg      *config.Config
}

func NewHandler(pipeline *rag.Pipeline, emailSvc *email.Service, s *store.Store, o *ollama.Client, cfg *config.Config) *Handler {
	return &Handler{
		pipeline: pipeline,
		emailSvc: emailSvc,
		store:    s,
		ollama:   o,
		cfg:      cfg,
	}
}

// RegisterRoutes sets up the HTTP routes on the given mux.
func (h *Handler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /health", h.healthCheck)
	mux.HandleFunc("POST /api/notifications", h.authMiddleware(h.ingestNotifications))
	mux.HandleFunc("GET /api/digest/preview", h.authMiddleware(h.previewDigest))
	mux.HandleFunc("POST /api/digest/send", h.authMiddleware(h.sendDigest))
	mux.HandleFunc("GET /api/notifications/recent", h.authMiddleware(h.recentNotifications))
}

// --- Handlers ---

func (h *Handler) healthCheck(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	status := map[string]string{"status": "ok"}

	if err := h.store.Healthy(ctx); err != nil {
		status["qdrant"] = "unhealthy: " + err.Error()
		status["status"] = "degraded"
	} else {
		status["qdrant"] = "ok"
	}

	if err := h.ollama.Healthy(ctx); err != nil {
		status["ollama"] = "unhealthy: " + err.Error()
		status["status"] = "degraded"
	} else {
		status["ollama"] = "ok"
	}

	code := http.StatusOK
	if status["status"] != "ok" {
		code = http.StatusServiceUnavailable
	}

	writeJSON(w, code, status)
}

func (h *Handler) ingestNotifications(w http.ResponseWriter, r *http.Request) {
	var batch models.NotificationBatch
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&batch); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}

	if len(batch.Notifications) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "no notifications provided"})
		return
	}

	// Apply device_id from batch level if individual notifications don't have it
	for i := range batch.Notifications {
		if batch.Notifications[i].DeviceID == "" {
			batch.Notifications[i].DeviceID = batch.DeviceID
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Minute)
	defer cancel()

	stored, err := h.pipeline.Ingest(ctx, batch.Notifications)
	if err != nil {
		log.Printf("Ingest error: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "ingest failed"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"stored":   stored,
		"received": len(batch.Notifications),
	})
}

func (h *Handler) previewDigest(w http.ResponseWriter, r *http.Request) {
	hours := queryInt(r, "hours", h.cfg.DigestIntervalHours)

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
	defer cancel()

	digest, err := h.pipeline.GenerateDigest(ctx, hours)
	if err != nil {
		log.Printf("Digest generation error: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "digest generation failed"})
		return
	}

	html, err := h.emailSvc.RenderDigest(digest)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "render failed"})
		return
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(html))
}

func (h *Handler) sendDigest(w http.ResponseWriter, r *http.Request) {
	hours := queryInt(r, "hours", h.cfg.DigestIntervalHours)

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
	defer cancel()

	digest, err := h.pipeline.GenerateDigest(ctx, hours)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "digest generation failed"})
		return
	}

	if digest.TotalCount == 0 {
		writeJSON(w, http.StatusOK, map[string]string{"message": "no notifications to send"})
		return
	}

	if err := h.emailSvc.SendDigest(digest); err != nil {
		log.Printf("Send digest error: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "email send failed"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"message":     "digest sent",
		"total_count": digest.TotalCount,
		"groups":      len(digest.Groups),
	})
}

func (h *Handler) recentNotifications(w http.ResponseWriter, r *http.Request) {
	hours := queryInt(r, "hours", 24)

	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()

	notifications, err := h.store.QueryRecent(ctx, hours)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "query failed"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"count":         len(notifications),
		"notifications": notifications,
	})
}

// --- Middleware ---

func (h *Handler) authMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		apiKey := r.Header.Get("X-API-Key")
		if apiKey == "" {
			apiKey = r.URL.Query().Get("api_key")
		}

		if subtle.ConstantTimeCompare([]byte(apiKey), []byte(h.cfg.APIKey)) != 1 {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
			return
		}

		next(w, r)
	}
}

// --- Helpers ---

func writeJSON(w http.ResponseWriter, code int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(data)
}

func queryInt(r *http.Request, key string, fallback int) int {
	if v := r.URL.Query().Get(key); v != "" {
		if i, err := strconv.Atoi(v); err == nil && i > 0 {
			return i
		}
	}
	return fallback
}
