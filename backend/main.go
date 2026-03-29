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
	_ = godotenv.Load()
	cfg := config.Load()
	log.Println("Starting PALM Messenger RAG backend...")

	qdrant, err := store.New(cfg.QdrantHost, cfg.QdrantPort, cfg.QdrantCollection)
	if err != nil {
		log.Fatalf("Failed to connect to Qdrant: %v", err)
	}
	defer qdrant.Close()
	log.Println("Connected to Qdrant")

	ollamaClient := ollama.NewClient(cfg.OllamaURL)
	log.Printf("Ollama client configured at %s", cfg.OllamaURL)

	pipeline := rag.NewPipeline(qdrant, ollamaClient, cfg)

	emailSvc, err := email.NewService(cfg)
	if err != nil {
		log.Fatalf("Failed to create email service: %v", err)
	}

	sched := scheduler.New(pipeline, emailSvc, cfg)
	sched.Start()
	defer sched.Stop()

	mux := http.NewServeMux()
	handler := api.NewHandler(pipeline, emailSvc, qdrant, ollamaClient, cfg)
	handler.RegisterRoutes(mux)

	addr := fmt.Sprintf(":%d", cfg.ServerPort)
	server := &http.Server{
		Addr:    addr,
		Handler: logMiddleware(mux),
	}

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
