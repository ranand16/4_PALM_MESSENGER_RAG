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
		pipeline: pipeline,
		emailSvc: emailSvc,
		cfg:      cfg,
		stop:     make(chan struct{}),
	}
}

func (s *Scheduler) Start() {
	go s.run()
	log.Printf("Scheduler started: digest every %d hours between %d:00-%d:00",
		s.cfg.DigestIntervalHours, s.cfg.DigestStartHour, s.cfg.DigestEndHour)
}

func (s *Scheduler) Stop() {
	close(s.stop)
}

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
				log.Printf("Skipping digest at %02d:00 (outside %d:00-%d:00 window)",
					hour, s.cfg.DigestStartHour, s.cfg.DigestEndHour)
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
		log.Printf("Failed to send digest email: %v", err)
		return
	}

	log.Printf("Digest sent successfully: %d messages in %d groups",
		digest.TotalCount, len(digest.Groups))
}
