// Command api serves the public REST API for the gaymr control plane.
//
// Phase 0 scope: hello-world handler with OTel-instrumented HTTP, structured
// logging, and graceful shutdown. Auth, sessions, billing endpoints land in
// later phases.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gaymr/gaymr/internal/config"
	"github.com/gaymr/gaymr/internal/obs"
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
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdown(shutdownCtx)
	}()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		// Phase 0: same as healthz. Later: actually probe DB + Redis.
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ready"}`))
	})
	mux.HandleFunc("GET /v1/hello", func(w http.ResponseWriter, r *http.Request) {
		slog.InfoContext(r.Context(), "hello", "remote", r.RemoteAddr)
		w.Header().Set("content-type", "application/json")
		_, _ = w.Write([]byte(`{"message":"gaymr api is alive"}`))
	})

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           obs.WrapHandler("api", mux),
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

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("graceful shutdown: %w", err)
	}
	slog.Info("api stopped cleanly")
	return nil
}
