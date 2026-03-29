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

const vectorSize = 768 // nomic-embed-text dimension

// Store wraps the Qdrant gRPC client.
type Store struct {
	conn           *grpc.ClientConn
	points         pb.PointsClient
	collections    pb.CollectionsClient
	collectionName string
}

// New connects to Qdrant and ensures the collection exists.
func New(host string, port int, collection string) (*Store, error) {
	addr := fmt.Sprintf("%s:%d", host, port)
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
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

func (s *Store) ensureCollection() error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Check if collection exists
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

	// Create collection
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

	// Create payload index on timestamp for efficient filtering
	fieldType := pb.FieldType_FieldTypeInteger
	_, err = s.points.CreateFieldIndex(ctx, &pb.CreateFieldIndexCollection{
		CollectionName: s.collectionName,
		FieldName:      "timestamp",
		FieldType:      &fieldType,
	})
	if err != nil {
		log.Printf("Warning: could not create timestamp index: %v", err)
	}

	// Create payload index on app_name for grouping
	fieldTypeKw := pb.FieldType_FieldTypeKeyword
	_, err = s.points.CreateFieldIndex(ctx, &pb.CreateFieldIndexCollection{
		CollectionName: s.collectionName,
		FieldName:      "app_name",
		FieldType:      &fieldTypeKw,
	})
	if err != nil {
		log.Printf("Warning: could not create app_name index: %v", err)
	}

	log.Printf("Created collection %q with vector size %d", s.collectionName, vectorSize)
	return nil
}

// Upsert stores a notification with its embedding vector.
func (s *Store) Upsert(ctx context.Context, notif models.StoredNotification, vector []float32) error {
	if notif.ID == "" {
		notif.ID = uuid.New().String()
	}

	pointID := &pb.PointId{PointIdOptions: &pb.PointId_Uuid{Uuid: notif.ID}}

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
		Wait:           &wait,
		Points: []*pb.PointStruct{
			{
				Id:      pointID,
				Vectors: &pb.Vectors{VectorsOptions: &pb.Vectors_Vector{Vector: &pb.Vector{Data: vector}}},
				Payload: payload,
			},
		},
	})
	if err != nil {
		return fmt.Errorf("upsert point: %w", err)
	}
	return nil
}

// QueryRecent returns notifications from the last `sinceHours` hours.
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
		WithPayload: &pb.WithPayloadSelector{SelectorOptions: &pb.WithPayloadSelector_Enable{Enable: true}},
	})
	if err != nil {
		return nil, fmt.Errorf("scroll recent: %w", err)
	}

	return pointsToNotifications(resp.GetResult()), nil
}

// SearchSimilar finds notifications semantically similar to the query vector.
func (s *Store) SearchSimilar(ctx context.Context, queryVector []float32, topK uint64) ([]models.StoredNotification, error) {
	resp, err := s.points.Search(ctx, &pb.SearchPoints{
		CollectionName: s.collectionName,
		Vector:         queryVector,
		Limit:          topK,
		WithPayload:    &pb.WithPayloadSelector{SelectorOptions: &pb.WithPayloadSelector_Enable{Enable: true}},
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

// Close shuts down the gRPC connection.
func (s *Store) Close() error {
	return s.conn.Close()
}

// Healthy checks connectivity.
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
		PackageName: getStringPayload(payload, "package_name"),
		AppName:     getStringPayload(payload, "app_name"),
		Title:       getStringPayload(payload, "title"),
		Text:        getStringPayload(payload, "text"),
		Timestamp:   getIntPayload(payload, "timestamp"),
		Summarized:  getBoolPayload(payload, "summarized"),
	}
}

func scoredPointToNotification(p *pb.ScoredPoint) models.StoredNotification {
	payload := p.GetPayload()
	return models.StoredNotification{
		ID:          p.GetId().GetUuid(),
		PackageName: getStringPayload(payload, "package_name"),
		AppName:     getStringPayload(payload, "app_name"),
		Title:       getStringPayload(payload, "title"),
		Text:        getStringPayload(payload, "text"),
		Timestamp:   getIntPayload(payload, "timestamp"),
		Summarized:  getBoolPayload(payload, "summarized"),
	}
}

func getStringPayload(payload map[string]*pb.Value, key string) string {
	if v, ok := payload[key]; ok {
		return v.GetStringValue()
	}
	return ""
}

func getIntPayload(payload map[string]*pb.Value, key string) int64 {
	if v, ok := payload[key]; ok {
		return v.GetIntegerValue()
	}
	return 0
}

func getBoolPayload(payload map[string]*pb.Value, key string) bool {
	if v, ok := payload[key]; ok {
		return v.GetBoolValue()
	}
	return false
}

func float64Ptr(f float64) *float64 {
	return &f
}
