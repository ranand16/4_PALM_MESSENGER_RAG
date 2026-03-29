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
