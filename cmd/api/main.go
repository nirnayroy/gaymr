// Command api serves the public REST API for the gaymr control plane.
//
// Phase 2A: Clerk-authenticated session lifecycle (POST/GET/DELETE /sessions)
// backed by Postgres + asynq. Provisioning is handled out-of-band by
// cmd/orchestrator.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/hibiken/asynq"

	"github.com/gaymr/gaymr/internal/auth"
	"github.com/gaymr/gaymr/internal/config"
	"github.com/gaymr/gaymr/internal/jobs"
	"github.com/gaymr/gaymr/internal/obs"
	"github.com/gaymr/gaymr/internal/sessions"
	"github.com/gaymr/gaymr/internal/store"
)

func main() {
	if err := run(); err != nil {
		slog.Error("fatal", "err", err)
		os.Exit(1)
	}
}

func run() error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load("api")
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}

	logger := obs.NewLogger(cfg.LogLevel)
	slog.SetDefault(logger)

	shutdown, err := obs.SetupTracing(ctx, cfg)
	if err != nil {
		return fmt.Errorf("setup tracing: %w", err)
	}
	defer func() {
		sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdown(sctx)
	}()

	if cfg.DatabaseURL == "" {
		return errors.New("DATABASE_URL is required")
	}
	if cfg.RedisURL == "" {
		return errors.New("REDIS_URL is required")
	}
	st, err := store.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return fmt.Errorf("store: %w", err)
	}
	defer st.Close()

	redisOpt, err := jobs.RedisOpt(cfg.RedisURL)
	if err != nil {
		return fmt.Errorf("redis opt: %w", err)
	}
	asynqClient := asynq.NewClient(redisOpt)
	defer asynqClient.Close()

	verifier, err := auth.NewVerifier(ctx, cfg.ClerkJWTIssuer, st)
	if err != nil {
		return fmt.Errorf("clerk verifier: %w", err)
	}

	svc := sessions.NewService(st, asynqClient)

	r := chi.NewRouter()
	r.Get("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	r.Get("/readyz", func(w http.ResponseWriter, r *http.Request) {
		if err := st.Pool().Ping(r.Context()); err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "db_down"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})

	r.Group(func(r chi.Router) {
		r.Use(verifier.Middleware)
		r.Get("/v1/me", handleMe)
		r.Post("/v1/sessions", handleCreateSession(svc))
		r.Get("/v1/sessions/{id}", handleGetSession(svc))
		r.Delete("/v1/sessions/{id}", handleDeleteSession(svc))
	})

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           obs.WrapHandler("api", r),
		ReadHeaderTimeout: 5 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		slog.Info("api listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	select {
	case <-ctx.Done():
		slog.Info("shutdown signal received, draining...")
	case err := <-errCh:
		return fmt.Errorf("server: %w", err)
	}

	sctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := srv.Shutdown(sctx); err != nil {
		return fmt.Errorf("graceful shutdown: %w", err)
	}
	slog.Info("api stopped cleanly")
	return nil
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("content-type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func handleMe(w http.ResponseWriter, r *http.Request) {
	c, _ := auth.FromContext(r.Context())
	writeJSON(w, http.StatusOK, map[string]string{
		"subject": c.Subject,
		"email":   c.Email,
		"user_id": c.UserID.String(),
	})
}

type createSessionReq struct {
	SKU    string `json:"sku"`
	Region string `json:"region"`
}

func handleCreateSession(svc *sessions.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		c, _ := auth.FromContext(r.Context())
		var req createSessionReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid body", http.StatusBadRequest)
			return
		}
		sess, err := svc.Create(r.Context(), c.UserID, sessions.CreateRequest{SKU: req.SKU, Region: req.Region})
		if err != nil {
			slog.ErrorContext(r.Context(), "create session", "err", err)
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		writeJSON(w, http.StatusAccepted, sess)
	}
}

func handleGetSession(svc *sessions.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		c, _ := auth.FromContext(r.Context())
		id := chi.URLParam(r, "id")
		sess, err := svc.GetForUser(r.Context(), c.UserID, id)
		if errors.Is(err, sessions.ErrNotFound) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		writeJSON(w, http.StatusOK, sess)
	}
}

func handleDeleteSession(svc *sessions.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		c, _ := auth.FromContext(r.Context())
		id := chi.URLParam(r, "id")
		if err := svc.Terminate(r.Context(), c.UserID, id); err != nil {
			if errors.Is(err, sessions.ErrNotFound) {
				http.Error(w, "not found", http.StatusNotFound)
				return
			}
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusAccepted)
	}
}
