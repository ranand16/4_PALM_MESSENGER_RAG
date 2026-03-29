# =============================================================================
# Dockerfile for PALM Messenger RAG Backend
# Multi-stage build: compiles Go binary in builder stage, copies to minimal
# Alpine runtime image for small footprint and secure deployment.
# =============================================================================

# --- Stage 1: Builder ---
# Use Go 1.23 Alpine image as the build environment
FROM golang:1.23-alpine AS builder
# Install git (required for fetching Go module dependencies from VCS)
RUN apk add --no-cache git
# Set the working directory inside the builder container
WORKDIR /app
# Copy Go module files first for better Docker layer caching
COPY go.mod go.sum ./
# Download all Go module dependencies (cached unless go.mod/go.sum change)
RUN go mod download
# Copy the entire backend source code into the builder container
COPY . .
# Build the Go binary with CGO disabled (static binary) targeting Linux
# Output binary is placed at /palm-rag in the builder filesystem
RUN CGO_ENABLED=0 GOOS=linux go build -o /palm-rag .

# --- Stage 2: Runtime ---
# Use minimal Alpine 3.19 as the runtime base image (~5MB)
FROM alpine:3.19
# Install CA certificates so the app can make HTTPS/TLS connections (e.g., SMTP)
RUN apk add --no-cache ca-certificates
# Copy the compiled binary from the builder stage into the runtime image
COPY --from=builder /palm-rag /palm-rag
# Declare that the container listens on port 8000 at runtime
EXPOSE 8000
# Set the compiled binary as the container entrypoint (runs on container start)
ENTRYPOINT ["/palm-rag"]
