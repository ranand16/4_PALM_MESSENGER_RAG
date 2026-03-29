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

// Service handles email sending.
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

// SendDigest renders and sends the digest email.
func (s *Service) SendDigest(data *models.DigestData) error {
	if s.cfg.SMTPUser == "" || s.cfg.SMTPPassword == "" {
		return fmt.Errorf("SMTP credentials not configured")
	}

	var body bytes.Buffer
	if err := s.tmpl.ExecuteTemplate(&body, "digest.html", data); err != nil {
		return fmt.Errorf("render digest template: %w", err)
	}

	subject := fmt.Sprintf("Notification Digest — %s (%d messages)",
		data.GeneratedAt.Format("Jan 02 15:04"), data.TotalCount)

	return s.sendMail(subject, body.String())
}

// RenderDigest renders the digest HTML without sending.
func (s *Service) RenderDigest(data *models.DigestData) (string, error) {
	var body bytes.Buffer
	if err := s.tmpl.ExecuteTemplate(&body, "digest.html", data); err != nil {
		return "", fmt.Errorf("render digest template: %w", err)
	}
	return body.String(), nil
}

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
		"Content-Type": "text/html; charset=\"utf-8\"",
	}

	var msg bytes.Buffer
	for k, v := range headers {
		fmt.Fprintf(&msg, "%s: %s\r\n", k, v)
	}
	msg.WriteString("\r\n")
	msg.WriteString(htmlBody)

	auth := smtp.PlainAuth("", s.cfg.SMTPUser, s.cfg.SMTPPassword, host)

	// Use STARTTLS
	conn, err := smtp.Dial(addr)
	if err != nil {
		return fmt.Errorf("dial SMTP: %w", err)
	}
	defer conn.Close()

	tlsConfig := &tls.Config{
		ServerName: host,
		MinVersion: tls.VersionTLS12,
	}
	if err := conn.StartTLS(tlsConfig); err != nil {
		return fmt.Errorf("STARTTLS: %w", err)
	}

	if err := conn.Auth(auth); err != nil {
		return fmt.Errorf("SMTP auth: %w", err)
	}

	if err := conn.Mail(from); err != nil {
		return fmt.Errorf("SMTP MAIL FROM: %w", err)
	}
	if err := conn.Rcpt(to); err != nil {
		return fmt.Errorf("SMTP RCPT TO: %w", err)
	}

	w, err := conn.Data()
	if err != nil {
		return fmt.Errorf("SMTP DATA: %w", err)
	}
	if _, err := w.Write(msg.Bytes()); err != nil {
		return fmt.Errorf("write email body: %w", err)
	}
	if err := w.Close(); err != nil {
		return fmt.Errorf("close email writer: %w", err)
	}

	log.Printf("Digest email sent to %s", to)
	return conn.Quit()
}

func formatTimestamp(ts int64) string {
	if ts == 0 {
		return ""
	}
	return time.UnixMilli(ts).Format("15:04")
}

func nl2br(s string) template.HTML {
	escaped := template.HTMLEscapeString(s)
	return template.HTML(strings.ReplaceAll(escaped, "\n", "<br>"))
}
