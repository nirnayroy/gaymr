// Package sessions implements the session lifecycle service: create,
// fetch, terminate. State transitions are guarded by Postgres row-level
// locks per system-design §3.5.
package sessions

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/hibiken/asynq"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/gaymr/gaymr/internal/jobs"
	"github.com/gaymr/gaymr/internal/store"
	"github.com/gaymr/gaymr/internal/store/sqlc"
)

var ErrNotFound = errors.New("session not found")

type CreateRequest struct {
	SKU    string
	Region string
}

type Service struct {
	store    *store.Store
	enqueuer *asynq.Client
}

func NewService(s *store.Store, c *asynq.Client) *Service {
	return &Service{store: s, enqueuer: c}
}

func (s *Service) Create(ctx context.Context, userID uuid.UUID, req CreateRequest) (*sqlc.Session, error) {
	if req.SKU == "" || req.Region == "" {
		return nil, fmt.Errorf("sku and region are required")
	}
	id := newSessionID()
	sess, err := s.store.CreateSession(ctx, sqlc.CreateSessionParams{
		ID:     id,
		UserID: pgUUID(userID),
		Sku:    req.SKU,
		Region: req.Region,
	})
	if err != nil {
		return nil, fmt.Errorf("create session: %w", err)
	}
	t, err := jobs.NewProvision(id)
	if err != nil {
		return nil, fmt.Errorf("build job: %w", err)
	}
	if _, err := s.enqueuer.EnqueueContext(ctx, t); err != nil {
		return nil, fmt.Errorf("enqueue: %w", err)
	}
	return &sess, nil
}

func (s *Service) GetForUser(ctx context.Context, userID uuid.UUID, id string) (*sqlc.Session, error) {
	sess, err := s.store.GetSessionForUser(ctx, sqlc.GetSessionForUserParams{
		ID:     id,
		UserID: pgUUID(userID),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &sess, nil
}

func (s *Service) Terminate(ctx context.Context, userID uuid.UUID, id string) error {
	sess, err := s.GetForUser(ctx, userID, id)
	if err != nil {
		return err
	}
	if sess.Status == sqlc.SessionStatusTerminated || sess.Status == sqlc.SessionStatusTerminating {
		return nil
	}
	if err := s.store.SetSessionStatus(ctx, sqlc.SetSessionStatusParams{
		ID:     id,
		Status: sqlc.SessionStatusTerminating,
	}); err != nil {
		return err
	}
	t, err := jobs.NewTerminate(id)
	if err != nil {
		return err
	}
	_, err = s.enqueuer.EnqueueContext(ctx, t)
	return err
}

func newSessionID() string {
	var b [12]byte
	_, _ = rand.Read(b[:])
	return "sess_" + hex.EncodeToString(b[:])
}

func pgUUID(u uuid.UUID) pgtype.UUID {
	var p pgtype.UUID
	copy(p.Bytes[:], u[:])
	p.Valid = true
	return p
}
