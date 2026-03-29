# PALM Messenger RAG — Step-by-Step Build Guide

Build this project module by module. Each step builds on the previous one.
Test after each step before moving on.

---

## Architecture Overview

```
┌─────────────────────────┐
│   Android App (Kotlin)  │
│   NotificationListener  │
│   + WorkManager sync    │
└──────────┬──────────────┘
           │ POST /api/notifications
           ▼
┌─────────────────────────┐     ┌──────────────┐
│   Go Backend (net/http) │◄───►│   Qdrant     │
│                         │     │   (Docker)   │
│   • Ingest + Embed      │     └──────────────┘
│   • RAG Summarize       │     ┌──────────────┐
│   • Email Digest        │◄───►│   Ollama     │
│   • Scheduler           │     │   (Docker)   │
└─────────────────────────┘     └──────────────┘
```

**Data flow:**
1. Android app captures notifications via `NotificationListenerService`
2. Stores them locally in Room DB, syncs to backend every 15 min
3. Backend embeds text via Ollama (`nomic-embed-text`, 768-dim vectors)
4. Stores vectors + metadata in Qdrant
5. On schedule, retrieves recent notifications, groups by app
6. For each group, does semantic search for related older messages (RAG)
7. Sends grouped messages + related context to Ollama (`mistral:7b`) for summary
8. Renders HTML email template, sends via SMTP

**Final directory structure:**
```
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── main.go
│   ├── Dockerfile
│   ├── go.mod / go.sum
│   ├── api/handlers.go
│   ├── config/config.go
│   ├── email/
│   │   ├── service.go
│   │   └── templates/digest.html
│   ├── models/models.go
│   ├── ollama/client.go
│   ├── rag/pipeline.go
│   ├── scheduler/scheduler.go
│   └── store/qdrant.go
└── android/
    └── app/src/main/
        ├── AndroidManifest.xml
        └── java/com/palmrag/
            ├── NotificationListener.kt
            ├── api/ApiClient.kt
            ├── db/{AppDatabase,NotificationDao,NotificationEntity}.kt
            ├── sync/NotificationSyncWorker.kt
            └── ui/SettingsActivity.kt
```

---

## STEP 1: Project Skeleton + Docker Infrastructure

### 1.1 Create project directories

```bash
mkdir -p backend/templates
mkdir -p android/app/src/main/java/com/palmrag/{db,sync,api,ui}
mkdir -p android/app/src/main/res/{layout,values,xml}
```

### 1.2 Create `.env.example`

This file defines every configurable value.
Create `.env.example` in the project root:

```env
# Qdrant
QDRANT_HOST=qdrant
QDRANT_PORT=6334
QDRANT_COLLECTION=notifications

# Ollama
OLLAMA_URL=http://ollama:11434
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_CHAT_MODEL=mistral:7b

# Email (Gmail App Password)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_TO=you@gmail.com
EMAIL_FROM=you@gmail.com

# API Key for Android app auth
API_KEY=change-me-to-a-secure-random-string

# Scheduler
DIGEST_INTERVAL_HOURS=2
DIGEST_START_HOUR=9
DIGEST_END_HOUR=19

# Server
SERVER_PORT=8000
```

**Why these values:**
- `QDRANT_PORT=6334` → gRPC port (faster than REST on 6333)
- `nomic-embed-text` → produces 768-dimension vectors, good quality/speed for short text
- `mistral:7b` → fast, concise summaries
- Gmail App Password → go to https://myaccount.google.com/apppasswords to generate one

### 1.3 Create `docker-compose.yml`

This orchestrates 4 services: Qdrant, Ollama, model-puller, and your backend.

```yaml
version: "3.8"

services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_storage:/qdrant/storage
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/version"]
      interval: 10s
      timeout: 5s
      retries: 5

  ollama-init:
    image: ollama/ollama:latest
    depends_on:
      ollama:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        OLLAMA_HOST=http://ollama:11434 ollama pull nomic-embed-text
        OLLAMA_HOST=http://ollama:11434 ollama pull mistral:7b
        echo "Models pulled successfully"
    restart: "no"

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      qdrant:
        condition: service_healthy
      ollama:
        condition: service_healthy
    restart: unless-stopped

volumes:
  qdrant_storage:
  ollama_data:
```

**Key points:**
- `ollama-init` is a one-shot container: it waits for Ollama to be healthy, pulls both models, then exits
- `backend` depends on both Qdrant and Ollama being healthy before starting
- Volumes persist Qdrant data and Ollama models across restarts

### 1.4 Test infrastructure (without backend)

```bash
cp .env.example .env
# Comment out or remove the `backend` service temporarily
docker-compose up qdrant ollama -d
# Wait for healthy, then:
curl http://localhost:6333/healthz    # Qdrant
curl http://localhost:11434/api/version  # Ollama
```

---

## STEP 2: Go Module + Config

### 2.1 Initialize Go module

```bash
cd backend
go mod init github.com/ranand16/palm-messenger-rag
```

### 2.2 Create `config/config.go`

This reads all environment variables with sensible defaults.

```go
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
```

**What you're learning:**
- Pattern: env var with fallback, no external config library needed
- Separate `getEnv`/`getEnvInt` helpers keep `Load()` clean
- All config in one struct → easy to pass around via dependency injection

### 2.3 Verify it compiles

```bash
cd backend
go build ./config/...
```

---

## STEP 3: Data Models

### 3.1 Create `models/models.go`

These structs define the shape of data flowing through the system.

```go
package models

import "time"

// Notification is what the Android app sends us.
type Notification struct {
    PackageName string `json:"package_name"`
    Title       string `json:"title"`
    Text        string `json:"text"`
    BigText     string `json:"big_text,omitempty"`
    Timestamp   int64  `json:"timestamp"`
    DeviceID    string `json:"device_id,omitempty"`
}

// NotificationBatch is the HTTP request payload from Android.
type NotificationBatch struct {
    Notifications []Notification `json:"notifications"`
    DeviceID      string         `json:"device_id,omitempty"`
    SentAt        int64          `json:"sent_at,omitempty"`
}

// StoredNotification is what lives in Qdrant (vector + payload).
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

// DigestGroup = one app's notifications + AI summary for the email.
type DigestGroup struct {
    AppName       string
    Notifications []StoredNotification
    Summary       string
}

// DigestData = everything the email template needs.
type DigestData struct {
    Groups      []DigestGroup
    GeneratedAt time.Time
    TotalCount  int
}

// AppNameMap translates Android package names → human-readable names.
var AppNameMap = map[string]string{
    "com.whatsapp":                       "WhatsApp",
    "com.whatsapp.w4b":                   "WhatsApp Business",
    "org.telegram.messenger":             "Telegram",
    "org.thoughtcrime.securesms":         "Signal",
    "com.google.android.apps.messaging":  "Messages",
    "com.facebook.orca":                  "Messenger",
    "com.instagram.android":              "Instagram",
    "com.slack":                          "Slack",
    "com.discord":                        "Discord",
    "com.google.android.gm":              "Gmail",
}

func ResolveAppName(packageName string) string {
    if name, ok := AppNameMap[packageName]; ok {
        return name
    }
    return packageName
}
```

**What you're learning:**
- Three layers of the same data: `Notification` (input) → `StoredNotification` (storage) → `DigestGroup` (output)
- `json` tags match what the Android app sends (snake_case)
- `AppNameMap` is a simple lookup; `ResolveAppName` falls back to raw package name

### 3.2 Verify

```bash
go build ./models/...
```

---

## STEP 4: Ollama Client

### 4.1 Create `ollama/client.go`

This talks to Ollama's REST API for two operations: **embed text** and **chat completion**.

```go
package ollama

import (
    "bytes"
    "context"
    "encoding/json"
    "fmt"
    "io"
    "net/http"
    "time"
)

type Client struct {
    baseURL    string
    httpClient *http.Client
}

func NewClient(baseURL string) *Client {
    return &Client{
        baseURL: baseURL,
        httpClient: &http.Client{
            Timeout: 120 * time.Second,  // LLM inference can be slow
        },
    }
}
```

**Embedding endpoint** — calls `POST /api/embed`:

```go
type embedRequest struct {
    Model string `json:"model"`
    Input string `json:"input"`
}

type embedResponse struct {
    Embeddings [][]float32 `json:"embeddings"`
}

func (c *Client) Embed(ctx context.Context, model, text string) ([]float32, error) {
    body, err := json.Marshal(embedRequest{Model: model, Input: text})
    if err != nil {
        return nil, fmt.Errorf("marshal embed request: %w", err)
    }

    req, err := http.NewRequestWithContext(ctx, http.MethodPost,
        c.baseURL+"/api/embed", bytes.NewReader(body))
    if err != nil {
        return nil, fmt.Errorf("create embed request: %w", err)
    }
    req.Header.Set("Content-Type", "application/json")

    resp, err := c.httpClient.Do(req)
    if err != nil {
        return nil, fmt.Errorf("embed request failed: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusOK {
        respBody, _ := io.ReadAll(resp.Body)
        return nil, fmt.Errorf("embed returned %d: %s", resp.StatusCode, string(respBody))
    }

    var result embedResponse
    if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
        return nil, fmt.Errorf("decode embed response: %w", err)
    }

    if len(result.Embeddings) == 0 {
        return nil, fmt.Errorf("no embeddings returned")
    }

    return result.Embeddings[0], nil
}
```

**Chat endpoint** — calls `POST /api/chat`:

```go
type chatMessage struct {
    Role    string `json:"role"`
    Content string `json:"content"`
}

type chatRequest struct {
    Model    string        `json:"model"`
    Messages []chatMessage `json:"messages"`
    Stream   bool          `json:"stream"`
}

type chatResponse struct {
    Message chatMessage `json:"message"`
}

func (c *Client) Chat(ctx context.Context, model, systemPrompt, userPrompt string) (string, error) {
    messages := []chatMessage{
        {Role: "system", Content: systemPrompt},
        {Role: "user", Content: userPrompt},
    }

    body, err := json.Marshal(chatRequest{
        Model: model, Messages: messages, Stream: false,
    })
    if err != nil {
        return "", fmt.Errorf("marshal chat request: %w", err)
    }

    req, err := http.NewRequestWithContext(ctx, http.MethodPost,
        c.baseURL+"/api/chat", bytes.NewReader(body))
    if err != nil {
        return "", fmt.Errorf("create chat request: %w", err)
    }
    req.Header.Set("Content-Type", "application/json")

    resp, err := c.httpClient.Do(req)
    if err != nil {
        return "", fmt.Errorf("chat request failed: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusOK {
        respBody, _ := io.ReadAll(resp.Body)
        return "", fmt.Errorf("chat returned %d: %s", resp.StatusCode, string(respBody))
    }

    var result chatResponse
    if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
        return "", fmt.Errorf("decode chat response: %w", err)
    }

    return result.Message.Content, nil
}
```

**Health check:**

```go
func (c *Client) Healthy(ctx context.Context) error {
    req, err := http.NewRequestWithContext(ctx, http.MethodGet,
        c.baseURL+"/api/version", nil)
    if err != nil {
        return err
    }
    resp, err := c.httpClient.Do(req)
    if err != nil {
        return err
    }
    defer resp.Body.Close()
    if resp.StatusCode != http.StatusOK {
        return fmt.Errorf("ollama returned %d", resp.StatusCode)
    }
    return nil
}
```

**What you're learning:**
- Ollama has a simple REST API — no SDK needed in Go
- `Stream: false` means we get the full response in one JSON blob (not SSE)
- `http.NewRequestWithContext` ensures requests respect cancellation/timeouts
- 120s timeout because LLM inference on CPU can be slow

### 4.2 Verify

```bash
go build ./ollama/...
```

---

## STEP 5: Qdrant Vector Store

### 5.1 Install the Qdrant Go client

```bash
go get github.com/qdrant/go-client
go get google.golang.org/grpc
go get github.com/google/uuid
```

### 5.2 Create `store/qdrant.go`

This is the largest module. It handles: connect, create collection, upsert vectors, scroll (filter by timestamp), and semantic search.

**Connection + collection setup:**

```go
package store

import (
    "context"
    "fmt"
    "log"
    "time"

    "github.com/google/uuid"
    pb "github.com/qdrant/go-client/qdrant"
    "github.com/ranand16/palm-messenger-rag/models"
    "google.golang.org/grpc"
    "google.golang.org/grpc/credentials/insecure"
)

const vectorSize = 768  // nomic-embed-text output dimension

type Store struct {
    conn           *grpc.ClientConn
    points         pb.PointsClient
    collections    pb.CollectionsClient
    collectionName string
}

func New(host string, port int, collection string) (*Store, error) {
    addr := fmt.Sprintf("%s:%d", host, port)
    conn, err := grpc.NewClient(addr,
        grpc.WithTransportCredentials(insecure.NewCredentials()))
    if err != nil {
        return nil, fmt.Errorf("connect to qdrant at %s: %w", addr, err)
    }

    s := &Store{
        conn:           conn,
        points:         pb.NewPointsClient(conn),
        collections:    pb.NewCollectionsClient(conn),
        collectionName: collection,
    }

    if err := s.ensureCollection(); err != nil {
        conn.Close()
        return nil, err
    }

    return s, nil
}
```

**Why gRPC instead of REST?**
The Go client uses gRPC (port 6334) which is faster and more type-safe than the REST API (port 6333).

**`ensureCollection`** — creates the collection + payload indexes if they don't exist:

```go
func (s *Store) ensureCollection() error {
    ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer cancel()

    // Check if it already exists
    resp, err := s.collections.List(ctx, &pb.ListCollectionsRequest{})
    if err != nil {
        return fmt.Errorf("list collections: %w", err)
    }
    for _, c := range resp.GetCollections() {
        if c.GetName() == s.collectionName {
            log.Printf("Collection %q already exists", s.collectionName)
            return nil
        }
    }

    // Create it
    size := uint64(vectorSize)
    _, err = s.collections.Create(ctx, &pb.CreateCollection{
        CollectionName: s.collectionName,
        VectorsConfig: &pb.VectorsConfig{
            Config: &pb.VectorsConfig_Params{
                Params: &pb.VectorParams{
                    Size:     size,
                    Distance: pb.Distance_Cosine,
                },
            },
        },
    })
    if err != nil {
        return fmt.Errorf("create collection %q: %w", s.collectionName, err)
    }

    // Index on timestamp → enables efficient range queries
    fieldType := pb.FieldType_FieldTypeInteger
    s.points.CreateFieldIndex(ctx, &pb.CreateFieldIndexCollection{
        CollectionName: s.collectionName,
        FieldName:      "timestamp",
        FieldType:      &fieldType,
    })

    // Index on app_name → enables efficient grouping
    fieldTypeKw := pb.FieldType_FieldTypeKeyword
    s.points.CreateFieldIndex(ctx, &pb.CreateFieldIndexCollection{
        CollectionName: s.collectionName,
        FieldName:      "app_name",
        FieldType:      &fieldTypeKw,
    })

    log.Printf("Created collection %q with vector size %d", s.collectionName, vectorSize)
    return nil
}
```

**`Upsert`** — stores one notification as a vector point:

```go
func (s *Store) Upsert(ctx context.Context, notif models.StoredNotification, vector []float32) error {
    if notif.ID == "" {
        notif.ID = uuid.New().String()
    }

    pointID := &pb.PointId{
        PointIdOptions: &pb.PointId_Uuid{Uuid: notif.ID},
    }

    // The "payload" is metadata stored alongside the vector
    payload := map[string]*pb.Value{
        "package_name": {Kind: &pb.Value_StringValue{StringValue: notif.PackageName}},
        "app_name":     {Kind: &pb.Value_StringValue{StringValue: notif.AppName}},
        "title":        {Kind: &pb.Value_StringValue{StringValue: notif.Title}},
        "text":         {Kind: &pb.Value_StringValue{StringValue: notif.Text}},
        "timestamp":    {Kind: &pb.Value_IntegerValue{IntegerValue: notif.Timestamp}},
        "stored_at":    {Kind: &pb.Value_StringValue{StringValue: notif.StoredAt.Format(time.RFC3339)}},
        "summarized":   {Kind: &pb.Value_BoolValue{BoolValue: notif.Summarized}},
    }

    wait := true
    _, err := s.points.Upsert(ctx, &pb.UpsertPoints{
        CollectionName: s.collectionName,
        Wait:           &wait,  // block until written to disk
        Points: []*pb.PointStruct{
            {
                Id:      pointID,
                Vectors: &pb.Vectors{VectorsOptions: &pb.Vectors_Vector{
                    Vector: &pb.Vector{Data: vector},
                }},
                Payload: payload,
            },
        },
    })
    if err != nil {
        return fmt.Errorf("upsert point: %w", err)
    }
    return nil
}
```

**`QueryRecent`** — scrolls all notifications from the last N hours using payload filter:

```go
func (s *Store) QueryRecent(ctx context.Context, sinceHours int) ([]models.StoredNotification, error) {
    cutoff := time.Now().Add(-time.Duration(sinceHours) * time.Hour).UnixMilli()

    limit := uint32(500)
    resp, err := s.points.Scroll(ctx, &pb.ScrollPoints{
        CollectionName: s.collectionName,
        Filter: &pb.Filter{
            Must: []*pb.Condition{
                {
                    ConditionOneOf: &pb.Condition_Field{
                        Field: &pb.FieldCondition{
                            Key: "timestamp",
                            Range: &pb.Range{
                                Gte: float64Ptr(float64(cutoff)),
                            },
                        },
                    },
                },
            },
        },
        Limit:       &limit,
        WithPayload: &pb.WithPayloadSelector{
            SelectorOptions: &pb.WithPayloadSelector_Enable{Enable: true},
        },
    })
    if err != nil {
        return nil, fmt.Errorf("scroll recent: %w", err)
    }

    return pointsToNotifications(resp.GetResult()), nil
}
```

**`SearchSimilar`** — vector similarity search (the "R" in RAG):

```go
func (s *Store) SearchSimilar(ctx context.Context, queryVector []float32, topK uint64) ([]models.StoredNotification, error) {
    resp, err := s.points.Search(ctx, &pb.SearchPoints{
        CollectionName: s.collectionName,
        Vector:         queryVector,
        Limit:          topK,
        WithPayload: &pb.WithPayloadSelector{
            SelectorOptions: &pb.WithPayloadSelector_Enable{Enable: true},
        },
    })
    if err != nil {
        return nil, fmt.Errorf("search similar: %w", err)
    }

    var results []models.StoredNotification
    for _, r := range resp.GetResult() {
        results = append(results, scoredPointToNotification(r))
    }
    return results, nil
}
```

**Helper functions** to convert Qdrant protobuf objects back into your Go structs:

```go
func (s *Store) Close() error { return s.conn.Close() }

func (s *Store) Healthy(ctx context.Context) error {
    _, err := s.collections.List(ctx, &pb.ListCollectionsRequest{})
    return err
}

func pointsToNotifications(points []*pb.RetrievedPoint) []models.StoredNotification {
    var results []models.StoredNotification
    for _, p := range points {
        results = append(results, retrievedPointToNotification(p))
    }
    return results
}

func retrievedPointToNotification(p *pb.RetrievedPoint) models.StoredNotification {
    payload := p.GetPayload()
    return models.StoredNotification{
        ID:          p.GetId().GetUuid(),
        PackageName: getStr(payload, "package_name"),
        AppName:     getStr(payload, "app_name"),
        Title:       getStr(payload, "title"),
        Text:        getStr(payload, "text"),
        Timestamp:   getInt(payload, "timestamp"),
        Summarized:  getBool(payload, "summarized"),
    }
}

func scoredPointToNotification(p *pb.ScoredPoint) models.StoredNotification {
    payload := p.GetPayload()
    return models.StoredNotification{
        ID:          p.GetId().GetUuid(),
        PackageName: getStr(payload, "package_name"),
        AppName:     getStr(payload, "app_name"),
        Title:       getStr(payload, "title"),
        Text:        getStr(payload, "text"),
        Timestamp:   getInt(payload, "timestamp"),
        Summarized:  getBool(payload, "summarized"),
    }
}

func getStr(p map[string]*pb.Value, k string) string {
    if v, ok := p[k]; ok { return v.GetStringValue() }
    return ""
}
func getInt(p map[string]*pb.Value, k string) int64 {
    if v, ok := p[k]; ok { return v.GetIntegerValue() }
    return 0
}
func getBool(p map[string]*pb.Value, k string) bool {
    if v, ok := p[k]; ok { return v.GetBoolValue() }
    return false
}
func float64Ptr(f float64) *float64 { return &f }
```

**What you're learning:**
- Qdrant stores each item as: UUID + vector ([]float32) + payload (map of typed values)
- `Scroll` = paginated retrieval with filters (no vector needed)
- `Search` = nearest-neighbor search by vector similarity (cosine distance)
- `ensureCollection` is idempotent — safe to call on every startup
- Payload indexes on `timestamp` and `app_name` make filtered queries fast

### 5.3 Verify

```bash
go mod tidy
go build ./store/...
```

---

## STEP 6: RAG Pipeline

This is the brain of the system. It does two things:
1. **Ingest**: embed notifications and store them
2. **GenerateDigest**: retrieve, group, search for context (RAG), summarize with LLM

### 6.1 Create `rag/pipeline.go`

```go
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

type Pipeline struct {
    store  *store.Store
    ollama *ollama.Client
    cfg    *config.Config
}

func NewPipeline(s *store.Store, o *ollama.Client, cfg *config.Config) *Pipeline {
    return &Pipeline{store: s, ollama: o, cfg: cfg}
}
```

**Ingest** — for each notification: build text → embed → store in Qdrant:

```go
func (p *Pipeline) Ingest(ctx context.Context, notifications []models.Notification) (int, error) {
    stored := 0
    for _, n := range notifications {
        // Combine title + text for embedding
        embedText := n.Title
        if n.Text != "" {
            embedText += ": " + n.Text
        }
        if n.BigText != "" {
            embedText = n.Title + ": " + n.BigText  // prefer bigText
        }

        if strings.TrimSpace(embedText) == "" {
            continue
        }

        // Step 1: Generate embedding vector
        vector, err := p.ollama.Embed(ctx, p.cfg.OllamaEmbedModel, embedText)
        if err != nil {
            log.Printf("Failed to embed from %s: %v", n.PackageName, err)
            continue
        }

        // Step 2: Build stored notification
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

        // Step 3: Store vector + metadata in Qdrant
        if err := p.store.Upsert(ctx, sn, vector); err != nil {
            log.Printf("Failed to store: %v", err)
            continue
        }
        stored++
    }
    return stored, nil
}

func bestText(n models.Notification) string {
    if n.BigText != "" { return n.BigText }
    return n.Text
}
```

**GenerateDigest** — the full RAG flow:

```go
func (p *Pipeline) GenerateDigest(ctx context.Context, sinceHours int) (*models.DigestData, error) {
    // STEP 1: Retrieve recent notifications from Qdrant
    notifications, err := p.store.QueryRecent(ctx, sinceHours)
    if err != nil {
        return nil, fmt.Errorf("query recent: %w", err)
    }

    if len(notifications) == 0 {
        return &models.DigestData{GeneratedAt: time.Now(), TotalCount: 0}, nil
    }

    // STEP 2: Group by app
    groups := groupByApp(notifications)

    // STEP 3: For each app group, do RAG + summarize
    var digestGroups []models.DigestGroup
    for appName, notifs := range groups {
        // Sort newest first
        sort.Slice(notifs, func(i, j int) bool {
            return notifs[i].Timestamp > notifs[j].Timestamp
        })

        // Build "recent messages" text block
        var msgLines []string
        for _, n := range notifs {
            t := time.UnixMilli(n.Timestamp).Format("15:04")
            msgLines = append(msgLines, fmt.Sprintf("[%s] %s: %s", t, n.Title, n.Text))
        }
        messagesContext := strings.Join(msgLines, "\n")

        // RAG: find semantically similar OLDER messages for richer context
        var ragContext string
        if len(notifs) > 0 {
            sampleText := notifs[0].Title + ": " + notifs[0].Text
            sampleVec, err := p.ollama.Embed(ctx, p.cfg.OllamaEmbedModel, sampleText)
            if err == nil {
                similar, err := p.store.SearchSimilar(ctx, sampleVec, 5)
                if err == nil && len(similar) > 0 {
                    var oldLines []string
                    for _, s := range similar {
                        oldLines = append(oldLines,
                            fmt.Sprintf("- %s: %s", s.Title, s.Text))
                    }
                    ragContext = "\n\nRelated older messages:\n" +
                        strings.Join(oldLines, "\n")
                }
            }
        }

        // STEP 4: Send to LLM for summarization
        systemPrompt := `You are a notification digest assistant.
Summarize the following messages concisely.
Group related conversations together.
Highlight important or urgent messages.
Keep the summary brief but informative. Use bullet points.
Do not add any information that is not in the messages.`

        userPrompt := fmt.Sprintf(
            "App: %s\nRecent messages:\n%s%s\n\nProvide a concise summary:",
            appName, messagesContext, ragContext)

        summary, err := p.ollama.Chat(ctx,
            p.cfg.OllamaChatModel, systemPrompt, userPrompt)
        if err != nil {
            log.Printf("Failed to summarize %s: %v", appName, err)
            summary = messagesContext  // fallback: raw messages
        }

        digestGroups = append(digestGroups, models.DigestGroup{
            AppName:       appName,
            Notifications: notifs,
            Summary:       summary,
        })
    }

    // Sort groups alphabetically for consistent email ordering
    sort.Slice(digestGroups, func(i, j int) bool {
        return digestGroups[i].AppName < digestGroups[j].AppName
    })

    return &models.DigestData{
        Groups:      digestGroups,
        GeneratedAt: time.Now(),
        TotalCount:  len(notifications),
    }, nil
}

func groupByApp(notifs []models.StoredNotification) map[string][]models.StoredNotification {
    groups := make(map[string][]models.StoredNotification)
    for _, n := range notifs {
        groups[n.AppName] = append(groups[n.AppName], n)
    }
    return groups
}
```

**What you're learning — this is the core RAG pattern:**
1. **Retrieve** — `QueryRecent` pulls notifications by timestamp filter (not vector search)
2. **Augment** — `SearchSimilar` finds semantically related older messages to add context
3. **Generate** — LLM gets both recent messages + related context → produces summary
4. The LLM never sees raw vector data — it only sees text. Vectors are just used for retrieval.

### 6.2 Verify

```bash
go build ./rag/...
```

---

## STEP 7: Email Digest Service

### 7.1 Create `email/templates/digest.html`

This is the HTML email template using Go's `html/template` syntax:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
  <div style="background-color: #ffffff; border-radius: 8px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
    <h1 style="color: #1a1a1a; font-size: 22px; margin: 0 0 4px 0;">📱 Notification Digest</h1>
    <p style="color: #666; font-size: 13px; margin: 0 0 24px 0;">
      Generated: {{.GeneratedAt.Format "Jan 02, 2006 15:04"}} · {{.TotalCount}} messages
    </p>

    {{if not .Groups}}
    <p style="color: #888; text-align: center; padding: 40px 0;">No new notifications.</p>
    {{end}}

    {{range .Groups}}
    <div style="margin-bottom: 24px; border-left: 3px solid #4A90D9; padding-left: 16px;">
      <h2 style="color: #333; font-size: 16px; margin: 0 0 8px 0;">
        {{.AppName}}
        <span style="color: #999; font-size: 12px; font-weight: normal;">
          ({{len .Notifications}} messages)
        </span>
      </h2>

      <div style="background-color: #f8f9fa; border-radius: 6px; padding: 12px; margin-bottom: 12px;">
        <p style="color: #444; font-size: 14px; margin: 0; line-height: 1.5;">
          {{nl2br .Summary}}
        </p>
      </div>

      <details style="margin-top: 8px;">
        <summary style="color: #888; font-size: 12px; cursor: pointer;">Show raw messages</summary>
        <ul style="list-style: none; padding: 8px 0 0 0; margin: 0;">
          {{range .Notifications}}
          <li style="color: #555; font-size: 13px; padding: 4px 0; border-bottom: 1px solid #eee;">
            <strong>{{.Title}}</strong>: {{.Text}}
          </li>
          {{end}}
        </ul>
      </details>
    </div>
    {{end}}

    <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0 12px 0;">
    <p style="color: #aaa; font-size: 11px; text-align: center; margin: 0;">
      PALM Messenger RAG · Powered by Ollama + Qdrant
    </p>
  </div>
</body>
</html>
```

**Why inline CSS?** Email clients (Gmail, Outlook) strip `<style>` tags. All styling must be inline.

### 7.2 Create `email/service.go`

Uses Go's `embed` to bundle the HTML template into the binary, and `net/smtp` with STARTTLS:

```go
package email

import (
    "bytes"
    "crypto/tls"
    "embed"
    "fmt"
    "html/template"
    "log"
    "net/smtp"
    "strings"
    "time"

    "github.com/ranand16/palm-messenger-rag/config"
    "github.com/ranand16/palm-messenger-rag/models"
)

//go:embed templates/*.html
var templateFS embed.FS

type Service struct {
    cfg  *config.Config
    tmpl *template.Template
}

func NewService(cfg *config.Config) (*Service, error) {
    funcMap := template.FuncMap{
        "formatTimestamp": formatTimestamp,
        "nl2br":          nl2br,
    }

    tmpl, err := template.New("").Funcs(funcMap).ParseFS(templateFS, "templates/*.html")
    if err != nil {
        return nil, fmt.Errorf("parse email templates: %w", err)
    }

    return &Service{cfg: cfg, tmpl: tmpl}, nil
}
```

**Key concept: `//go:embed`**
This directive tells the Go compiler to include `templates/*.html` inside the binary at compile time. No need to ship HTML files separately — they're baked into the Docker image.

**SendDigest** — render template + send via SMTP:

```go
func (s *Service) SendDigest(data *models.DigestData) error {
    if s.cfg.SMTPUser == "" || s.cfg.SMTPPassword == "" {
        return fmt.Errorf("SMTP credentials not configured")
    }

    var body bytes.Buffer
    if err := s.tmpl.ExecuteTemplate(&body, "digest.html", data); err != nil {
        return fmt.Errorf("render template: %w", err)
    }

    subject := fmt.Sprintf("Notification Digest — %s (%d messages)",
        data.GeneratedAt.Format("Jan 02 15:04"), data.TotalCount)

    return s.sendMail(subject, body.String())
}

// RenderDigest renders without sending — used for the preview endpoint.
func (s *Service) RenderDigest(data *models.DigestData) (string, error) {
    var body bytes.Buffer
    if err := s.tmpl.ExecuteTemplate(&body, "digest.html", data); err != nil {
        return "", fmt.Errorf("render template: %w", err)
    }
    return body.String(), nil
}
```

**SMTP with STARTTLS** (what Gmail requires):

```go
func (s *Service) sendMail(subject, htmlBody string) error {
    from := s.cfg.EmailFrom
    to := s.cfg.EmailTo
    host := s.cfg.SMTPHost
    addr := fmt.Sprintf("%s:%d", host, s.cfg.SMTPPort)

    headers := map[string]string{
        "From":         from,
        "To":           to,
        "Subject":      subject,
        "MIME-Version": "1.0",
        "Content-Type": `text/html; charset="utf-8"`,
    }

    var msg bytes.Buffer
    for k, v := range headers {
        fmt.Fprintf(&msg, "%s: %s\r\n", k, v)
    }
    msg.WriteString("\r\n")
    msg.WriteString(htmlBody)

    auth := smtp.PlainAuth("", s.cfg.SMTPUser, s.cfg.SMTPPassword, host)

    // Connect → STARTTLS → Auth → Send
    conn, err := smtp.Dial(addr)
    if err != nil {
        return fmt.Errorf("dial SMTP: %w", err)
    }
    defer conn.Close()

    tlsConfig := &tls.Config{ServerName: host, MinVersion: tls.VersionTLS12}
    if err := conn.StartTLS(tlsConfig); err != nil {
        return fmt.Errorf("STARTTLS: %w", err)
    }
    if err := conn.Auth(auth); err != nil {
        return fmt.Errorf("SMTP auth: %w", err)
    }
    if err := conn.Mail(from); err != nil {
        return fmt.Errorf("MAIL FROM: %w", err)
    }
    if err := conn.Rcpt(to); err != nil {
        return fmt.Errorf("RCPT TO: %w", err)
    }

    w, err := conn.Data()
    if err != nil {
        return fmt.Errorf("DATA: %w", err)
    }
    w.Write(msg.Bytes())
    w.Close()

    log.Printf("Digest email sent to %s", to)
    return conn.Quit()
}

func formatTimestamp(ts int64) string {
    if ts == 0 { return "" }
    return time.UnixMilli(ts).Format("15:04")
}

func nl2br(s string) template.HTML {
    escaped := template.HTMLEscapeString(s)
    return template.HTML(strings.ReplaceAll(escaped, "\n", "<br>"))
}
```

**Security note on `nl2br`:** HTML-escapes user content first, then replaces newlines. This prevents XSS in the email.

### 7.3 Verify

```bash
go build ./email/...
```

---

## STEP 8: HTTP API Handlers

### 8.1 Create `api/handlers.go`

Five endpoints: health, ingest, preview digest, send digest, list recent.

**Setup + dependency injection:**

```go
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

type Handler struct {
    pipeline *rag.Pipeline
    emailSvc *email.Service
    store    *store.Store
    ollama   *ollama.Client
    cfg      *config.Config
}

func NewHandler(pipeline *rag.Pipeline, emailSvc *email.Service,
    s *store.Store, o *ollama.Client, cfg *config.Config) *Handler {
    return &Handler{pipeline: pipeline, emailSvc: emailSvc,
        store: s, ollama: o, cfg: cfg}
}

func (h *Handler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("GET /health", h.healthCheck)
    mux.HandleFunc("POST /api/notifications", h.authMiddleware(h.ingestNotifications))
    mux.HandleFunc("GET /api/digest/preview", h.authMiddleware(h.previewDigest))
    mux.HandleFunc("POST /api/digest/send", h.authMiddleware(h.sendDigest))
    mux.HandleFunc("GET /api/notifications/recent", h.authMiddleware(h.recentNotifications))
}
```

**Note on routing:** Go 1.22+ supports method-based routing (`"GET /health"`) in the standard `http.ServeMux`. No third-party router needed.

**Auth middleware** — constant-time comparison to prevent timing attacks:

```go
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
```

**Health check:**

```go
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
```

**Ingest notifications** — what the Android app calls:

```go
func (h *Handler) ingestNotifications(w http.ResponseWriter, r *http.Request) {
    var batch models.NotificationBatch
    // Limit body to 1MB to prevent abuse
    if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&batch); err != nil {
        writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
        return
    }

    if len(batch.Notifications) == 0 {
        writeJSON(w, http.StatusBadRequest, map[string]string{"error": "no notifications provided"})
        return
    }

    // Propagate batch-level device_id to individual notifications
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
        "stored": stored, "received": len(batch.Notifications),
    })
}
```

**Preview digest** (returns HTML, good for testing in browser):

```go
func (h *Handler) previewDigest(w http.ResponseWriter, r *http.Request) {
    hours := queryInt(r, "hours", h.cfg.DigestIntervalHours)

    ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
    defer cancel()

    digest, err := h.pipeline.GenerateDigest(ctx, hours)
    if err != nil {
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
```

**Send digest + list recent:**

```go
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
        writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "email send failed"})
        return
    }
    writeJSON(w, http.StatusOK, map[string]interface{}{
        "message": "digest sent", "total_count": digest.TotalCount, "groups": len(digest.Groups),
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
        "count": len(notifications), "notifications": notifications,
    })
}

// --- Helpers ---

func writeJSON(w http.ResponseWriter, code int, data interface{}) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(code)
    json.NewEncoder(w).Encode(data)
}

func queryInt(r *http.Request, key string, fallback int) int {
    if v := r.URL.Query().Get(key); v != "" {
        if i, err := strconv.Atoi(v); err == nil && i > 0 { return i }
    }
    return fallback
}
```

**What you're learning:**
- `http.MaxBytesReader` prevents the Android app from sending a huge payload
- `crypto/subtle.ConstantTimeCompare` prevents timing-based API key guessing
- Every handler creates its own `context.WithTimeout` — if Ollama hangs, it won't block forever
- `queryInt` lets you override defaults via `?hours=24`

### 8.2 Verify

```bash
go build ./api/...
```

---

## STEP 9: Scheduler

### 9.1 Create `scheduler/scheduler.go`

Runs in a goroutine; ticks every N hours; only runs during work hours:

```go
package scheduler

import (
    "context"
    "log"
    "time"

    "github.com/ranand16/palm-messenger-rag/config"
    "github.com/ranand16/palm-messenger-rag/email"
    "github.com/ranand16/palm-messenger-rag/rag"
)

type Scheduler struct {
    pipeline *rag.Pipeline
    emailSvc *email.Service
    cfg      *config.Config
    stop     chan struct{}
}

func New(pipeline *rag.Pipeline, emailSvc *email.Service, cfg *config.Config) *Scheduler {
    return &Scheduler{
        pipeline: pipeline, emailSvc: emailSvc,
        cfg: cfg, stop: make(chan struct{}),
    }
}

func (s *Scheduler) Start() {
    go s.run()
    log.Printf("Scheduler started: every %dh between %d:00-%d:00",
        s.cfg.DigestIntervalHours, s.cfg.DigestStartHour, s.cfg.DigestEndHour)
}

func (s *Scheduler) Stop() { close(s.stop) }

func (s *Scheduler) run() {
    interval := time.Duration(s.cfg.DigestIntervalHours) * time.Hour
    ticker := time.NewTicker(interval)
    defer ticker.Stop()

    for {
        select {
        case <-s.stop:
            log.Println("Scheduler stopped")
            return
        case t := <-ticker.C:
            hour := t.Hour()
            if hour >= s.cfg.DigestStartHour && hour < s.cfg.DigestEndHour {
                s.runDigest()
            } else {
                log.Printf("Skipping digest at %02d:00 (outside window)", hour)
            }
        }
    }
}

func (s *Scheduler) runDigest() {
    log.Println("Running scheduled digest...")
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
    defer cancel()

    digest, err := s.pipeline.GenerateDigest(ctx, s.cfg.DigestIntervalHours)
    if err != nil {
        log.Printf("Digest generation failed: %v", err)
        return
    }
    if digest.TotalCount == 0 {
        log.Println("No notifications to digest, skipping email")
        return
    }
    if err := s.emailSvc.SendDigest(digest); err != nil {
        log.Printf("Failed to send digest: %v", err)
        return
    }
    log.Printf("Digest sent: %d messages in %d groups",
        digest.TotalCount, len(digest.Groups))
}
```

**What you're learning:**
- `time.NewTicker` + goroutine = simple recurring job
- `select` with `stop` channel = clean shutdown
- Work-hours window check prevents emails at 3am

---

## STEP 10: Main Entry Point

### 10.1 Install godotenv

```bash
go get github.com/joho/godotenv
```

### 10.2 Create `main.go`

This wires everything together:

```go
package main

import (
    "fmt"
    "log"
    "net/http"
    "os"
    "os/signal"
    "syscall"

    "github.com/joho/godotenv"
    "github.com/ranand16/palm-messenger-rag/api"
    "github.com/ranand16/palm-messenger-rag/config"
    "github.com/ranand16/palm-messenger-rag/email"
    "github.com/ranand16/palm-messenger-rag/ollama"
    "github.com/ranand16/palm-messenger-rag/rag"
    "github.com/ranand16/palm-messenger-rag/scheduler"
    "github.com/ranand16/palm-messenger-rag/store"
)

func main() {
    _ = godotenv.Load()  // load .env file (silently ignore if missing)
    cfg := config.Load()
    log.Println("Starting PALM Messenger RAG backend...")

    // 1. Connect to Qdrant
    qdrant, err := store.New(cfg.QdrantHost, cfg.QdrantPort, cfg.QdrantCollection)
    if err != nil {
        log.Fatalf("Failed to connect to Qdrant: %v", err)
    }
    defer qdrant.Close()
    log.Println("Connected to Qdrant")

    // 2. Create Ollama client
    ollamaClient := ollama.NewClient(cfg.OllamaURL)
    log.Printf("Ollama configured at %s", cfg.OllamaURL)

    // 3. Create RAG pipeline
    pipeline := rag.NewPipeline(qdrant, ollamaClient, cfg)

    // 4. Create email service
    emailSvc, err := email.NewService(cfg)
    if err != nil {
        log.Fatalf("Failed to create email service: %v", err)
    }

    // 5. Start scheduler
    sched := scheduler.New(pipeline, emailSvc, cfg)
    sched.Start()
    defer sched.Stop()

    // 6. Setup HTTP server
    mux := http.NewServeMux()
    handler := api.NewHandler(pipeline, emailSvc, qdrant, ollamaClient, cfg)
    handler.RegisterRoutes(mux)

    addr := fmt.Sprintf(":%d", cfg.ServerPort)
    server := &http.Server{
        Addr:    addr,
        Handler: logMiddleware(mux),
    }

    // 7. Graceful shutdown on SIGINT/SIGTERM
    go func() {
        sigCh := make(chan os.Signal, 1)
        signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
        <-sigCh
        log.Println("Shutting down...")
        server.Close()
    }()

    log.Printf("Server listening on %s", addr)
    if err := server.ListenAndServe(); err != http.ErrServerClosed {
        log.Fatalf("Server error: %v", err)
    }
    log.Println("Server stopped")
}

func logMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        log.Printf("%s %s %s", r.Method, r.URL.Path, r.RemoteAddr)
        next.ServeHTTP(w, r)
    })
}
```

**What you're learning:**
- Dependency injection: create each component, pass it to the next
- `godotenv.Load()` reads `.env` into `os.Getenv` — the `config` package doesn't care where env vars come from
- Graceful shutdown: signal handler closes server, defers stop scheduler and close Qdrant connection

### 10.3 Build and test

```bash
go mod tidy
go build .
# or:
go vet ./...   # static analysis
```

---

## STEP 11: Dockerfile

### 11.1 Create `backend/Dockerfile`

Multi-stage build — final image is ~15MB:

```dockerfile
FROM golang:1.23-alpine AS builder
RUN apk add --no-cache git
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /palm-rag .

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=builder /palm-rag /palm-rag
EXPOSE 8000
ENTRYPOINT ["/palm-rag"]
```

**Why multi-stage?**
- Stage 1 (`golang:1.23-alpine`): has Go compiler (~300MB) — only used to build
- Stage 2 (`alpine:3.19`): only has the compiled binary + CA certs (~15MB)
- `ca-certificates` needed for SMTP TLS connections to Gmail

### 11.2 Full test

```bash
cp .env.example .env
# Edit .env with real values
docker-compose up --build
curl http://localhost:8000/health
```

---

## STEP 12: Android App

### 12.1 Create Android project files

Open Android Studio → New Project → Empty Activity → package name `com.palmrag` → min SDK 26.

Or create the files manually as described below.

### 12.2 `AndroidManifest.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.palmrag">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />

    <application
        android:allowBackup="true"
        android:label="PALM RAG"
        android:theme="@style/Theme.MaterialComponents.Light.DarkActionBar">

        <activity
            android:name=".ui.SettingsActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <service
            android:name=".NotificationListener"
            android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE"
            android:exported="true">
            <intent-filter>
                <action android:name="android.service.notification.NotificationListenerService" />
            </intent-filter>
        </service>
    </application>
</manifest>
```

**Key point:** `BIND_NOTIFICATION_LISTENER_SERVICE` requires the user to manually grant access in Settings → Notification access. You can't request it at runtime.

### 12.3 `app/build.gradle` dependencies

```groovy
dependencies {
    implementation 'androidx.core:core-ktx:1.12.0'
    implementation 'androidx.appcompat:appcompat:1.6.1'
    implementation 'com.google.android.material:material:1.11.0'

    // Room (local SQLite DB)
    implementation 'androidx.room:room-runtime:2.6.1'
    implementation 'androidx.room:room-ktx:2.6.1'
    kapt 'androidx.room:room-compiler:2.6.1'

    // WorkManager (reliable background sync)
    implementation 'androidx.work:work-runtime-ktx:2.9.0'

    // Retrofit (HTTP client)
    implementation 'com.squareup.retrofit2:retrofit:2.9.0'
    implementation 'com.squareup.retrofit2:converter-gson:2.9.0'

    // Coroutines
    implementation 'org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3'
}
```

### 12.4 Room Database (local storage)

**`db/NotificationEntity.kt`** — the SQLite table schema:

```kotlin
@Entity(tableName = "notifications")
data class NotificationEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val packageName: String,
    val title: String,
    val text: String,
    val timestamp: Long,
    val synced: Boolean = false,
    val createdAt: Long = System.currentTimeMillis()
)
```

**`db/NotificationDao.kt`** — queries:

```kotlin
@Dao
interface NotificationDao {
    @Insert
    suspend fun insert(notification: NotificationEntity)

    @Query("SELECT * FROM notifications WHERE synced = 0 ORDER BY id ASC LIMIT 100")
    suspend fun getUnsynced(): List<NotificationEntity>

    @Query("UPDATE notifications SET synced = 1 WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<Long>)

    @Query("DELETE FROM notifications WHERE synced = 1 AND createdAt < :before")
    suspend fun cleanOld(before: Long)

    @Query("SELECT COUNT(*) FROM notifications WHERE synced = 0")
    suspend fun unsyncedCount(): Int
}
```

**`db/AppDatabase.kt`** — singleton Room database:

```kotlin
@Database(entities = [NotificationEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun notificationDao(): NotificationDao

    companion object {
        @Volatile private var INSTANCE: AppDatabase? = null

        fun getInstance(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                Room.databaseBuilder(context.applicationContext,
                    AppDatabase::class.java, "palm_rag_db").build()
                    .also { INSTANCE = it }
            }
        }
    }
}
```

**Why Room + `synced` flag?**
If the phone has no network, notifications queue up locally. WorkManager retries when connectivity returns. The `synced` flag ensures nothing is sent twice.

### 12.5 `NotificationListener.kt` — the core capture service

```kotlin
class NotificationListener : NotificationListenerService() {

    companion object {
        val WATCHED_PACKAGES = setOf(
            "com.whatsapp", "com.whatsapp.w4b",
            "org.telegram.messenger",
            "org.thoughtcrime.securesms",        // Signal
            "com.google.android.apps.messaging", // Google Messages
            "com.facebook.orca",                 // Messenger
            "com.instagram.android",
            "com.slack", "com.discord"
        )
    }

    private val scope = CoroutineScope(Dispatchers.IO)

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        // 1. Filter: only capture whitelisted apps
        if (!isWatched(sbn.packageName)) return

        // 2. Extract data from the notification
        val extras = sbn.notification.extras
        val title = extras.getCharSequence("android.title")?.toString() ?: ""
        val text = extras.getCharSequence("android.text")?.toString() ?: ""
        val bigText = extras.getCharSequence("android.bigText")?.toString() ?: ""

        if (title.isBlank() && text.isBlank()) return

        // 3. Save to local Room DB
        val entity = NotificationEntity(
            packageName = sbn.packageName,
            title = title,
            text = if (bigText.isNotBlank()) bigText else text,
            timestamp = sbn.postTime
        )

        scope.launch {
            AppDatabase.getInstance(applicationContext)
                .notificationDao().insert(entity)
            scheduleSync()
        }
    }

    private fun isWatched(pkg: String): Boolean {
        val prefs = getSharedPreferences("palm_rag_prefs", MODE_PRIVATE)
        val custom = prefs.getStringSet("watched_packages", null)
        return pkg in (custom ?: WATCHED_PACKAGES)
    }

    private fun scheduleSync() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED).build()

        val request = PeriodicWorkRequestBuilder<NotificationSyncWorker>(
            15, TimeUnit.MINUTES
        ).setConstraints(constraints).build()

        WorkManager.getInstance(applicationContext)
            .enqueueUniquePeriodicWork("notification_sync",
                ExistingPeriodicWorkPolicy.KEEP, request)
    }
}
```

**What you're learning:**
- `onNotificationPosted` fires for every notification on the phone
- `android.title` = sender name, `android.text` = message preview, `android.bigText` = full message
- `bigText` is preferred over `text` because `text` is often truncated
- WorkManager with `KEEP` policy means only one sync job exists at a time

### 12.6 `api/ApiClient.kt` — Retrofit HTTP client

```kotlin
data class NotificationDTO(
    val package_name: String, val title: String,
    val text: String, val timestamp: Long, val device_id: String
)
data class NotificationBatch(
    val notifications: List<NotificationDTO>, val device_id: String
)
data class IngestResponse(val stored: Int, val received: Int)

interface NotificationApi {
    @POST("/api/notifications")
    suspend fun sendNotifications(
        @Header("X-API-Key") apiKey: String,
        @Body batch: NotificationBatch
    ): Response<IngestResponse>
}

object ApiClient {
    private var retrofit: Retrofit? = null
    private var currentBaseUrl: String? = null

    fun getApi(baseUrl: String): NotificationApi {
        if (retrofit == null || currentBaseUrl != baseUrl) {
            currentBaseUrl = baseUrl
            retrofit = Retrofit.Builder()
                .baseUrl(baseUrl)
                .addConverterFactory(GsonConverterFactory.create())
                .build()
        }
        return retrofit!!.create(NotificationApi::class.java)
    }
}
```

### 12.7 `sync/NotificationSyncWorker.kt` — background sync

```kotlin
class NotificationSyncWorker(context: Context, params: WorkerParameters)
    : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("palm_rag_prefs",
            Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("backend_url", null)
        val apiKey = prefs.getString("api_key", null)

        if (baseUrl.isNullOrBlank() || apiKey.isNullOrBlank())
            return Result.retry()

        val db = AppDatabase.getInstance(applicationContext)
        val unsynced = db.notificationDao().getUnsynced()
        if (unsynced.isEmpty()) return Result.success()

        val deviceId = Build.MODEL + "_" + Build.ID
        val batch = NotificationBatch(
            notifications = unsynced.map {
                NotificationDTO(it.packageName, it.title, it.text, it.timestamp, deviceId)
            },
            device_id = deviceId
        )

        return try {
            val response = ApiClient.getApi(baseUrl).sendNotifications(apiKey, batch)
            if (response.isSuccessful) {
                db.notificationDao().markSynced(unsynced.map { it.id })
                // Clean old synced entries (>7 days)
                val cutoff = System.currentTimeMillis() - 7 * 24 * 3600 * 1000L
                db.notificationDao().cleanOld(cutoff)
                Result.success()
            } else {
                Result.retry()
            }
        } catch (e: Exception) {
            Result.retry()  // WorkManager will retry with backoff
        }
    }
}
```

### 12.8 `ui/SettingsActivity.kt` — simple settings screen

```kotlin
class SettingsActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        val etUrl = findViewById<EditText>(R.id.et_backend_url)
        val etKey = findViewById<EditText>(R.id.et_api_key)
        val tvStatus = findViewById<TextView>(R.id.tv_status)
        val tvPending = findViewById<TextView>(R.id.tv_pending_count)

        // Load saved settings
        val prefs = getSharedPreferences("palm_rag_prefs", MODE_PRIVATE)
        etUrl.setText(prefs.getString("backend_url", "http://192.168.1.100:8000"))
        etKey.setText(prefs.getString("api_key", ""))

        // Save button
        findViewById<Button>(R.id.btn_save).setOnClickListener {
            prefs.edit()
                .putString("backend_url", etUrl.text.toString().trim())
                .putString("api_key", etKey.text.toString().trim())
                .apply()
            Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show()
        }

        // Grant notification access button
        findViewById<Button>(R.id.btn_grant_access).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }

        // Show notification access status
        val enabled = Settings.Secure.getString(contentResolver,
            "enabled_notification_listeners")
            ?.contains(ComponentName(this, "com.palmrag.NotificationListener")
                .flattenToString()) == true
        tvStatus.text = if (enabled) "Access: GRANTED" else "Access: NOT GRANTED"

        // Show pending count
        CoroutineScope(Dispatchers.IO).launch {
            val count = AppDatabase.getInstance(applicationContext)
                .notificationDao().unsyncedCount()
            withContext(Dispatchers.Main) {
                tvPending.text = "Pending sync: $count"
            }
        }
    }
}
```

---

## STEP 13: Test End-to-End

### 13.1 Start infrastructure

```bash
cp .env.example .env
# Edit .env with your real SMTP credentials and a strong API_KEY
docker-compose up --build -d
```

### 13.2 Health check

```bash
curl http://localhost:8000/health
# {"qdrant":"ok","ollama":"ok","status":"ok"}
```

### 13.3 Simulate Android sending notifications

```bash
curl -X POST http://localhost:8000/api/notifications \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "notifications": [
      {
        "package_name": "com.whatsapp",
        "title": "John",
        "text": "Hey, are we still meeting at 3pm?",
        "timestamp": 1711612800000
      },
      {
        "package_name": "com.whatsapp",
        "title": "Mom",
        "text": "Call me when you get a chance",
        "timestamp": 1711613400000
      },
      {
        "package_name": "org.telegram.messenger",
        "title": "Work Group",
        "text": "Deployment scheduled for tonight at 10pm",
        "timestamp": 1711614000000
      }
    ]
  }'
# {"received":3,"stored":3}
```

### 13.4 Preview digest

```bash
curl "http://localhost:8000/api/digest/preview?hours=24&api_key=YOUR_API_KEY"
# Returns styled HTML — open in browser to see
```

### 13.5 Send digest email

```bash
curl -X POST "http://localhost:8000/api/digest/send?hours=24" \
  -H "X-API-Key: YOUR_API_KEY"
# {"groups":2,"message":"digest sent","total_count":3}
```

### 13.6 Install Android app

1. Open `android/` in Android Studio
2. Build → Run on phone
3. Set backend URL + API key in the app
4. Grant notification access
5. Send yourself a WhatsApp message → check backend logs

---

## Module Dependency Graph

Build order matters because of imports:

```
config  ←── everything depends on this
  ↓
models  ←── no dependencies (just structs)
  ↓
ollama  ←── standalone HTTP client
  ↓
store   ←── depends on models
  ↓
rag     ←── depends on store + ollama + config + models
  ↓
email   ←── depends on config + models
  ↓
scheduler ←── depends on rag + email + config
  ↓
api     ←── depends on rag + email + store + ollama + config + models
  ↓
main.go ←── wires everything together
```

Each module can be built and tested independently:
```bash
go build ./config/...
go build ./models/...
go build ./ollama/...
go build ./store/...
go build ./rag/...
go build ./email/...
go build ./scheduler/...
go build ./api/...
go build .
```
