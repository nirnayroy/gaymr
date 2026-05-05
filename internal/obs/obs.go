// Package obs centralizes observability setup: structured logging, OpenTelemetry
// tracing, and a request-wrapping HTTP middleware.
//
// Phase 0 ships a no-op tracing setup so the API can boot without an OTel
// collector running. Real OTLP export wiring lands when we add the
// go.opentelemetry.io/otel deps in a follow-up commit.
package obs

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"time"
)

// NewLogger returns a JSON slog handler at the requested level.
// "debug" | "info" | "warn" | "error"; anything else falls back to info.
func NewLogger(level string) *slog.Logger {
	var lvl slog.Level
	switch strings.ToLower(level) {
	case "debug":
		lvl = slog.LevelDebug
	case "warn":
		lvl = slog.LevelWarn
	case "error":
		lvl = slog.LevelError
	default:
		lvl = slog.LevelInfo
	}
	return slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: lvl,
	}))
}

// ShutdownFunc finalizes telemetry exporters; call before process exit.
type ShutdownFunc func(context.Context) error

// SetupTracing initializes OTel exporters.
//
// PHASE 0: noop. The full implementation pulls in go.opentelemetry.io/otel,
// configures an OTLP gRPC exporter pointed at cfg.OTelEndpoint, sets the
// global TracerProvider, and returns a shutdown that flushes the batch
// processor. We're stubbing it out for now so cmd/api compiles with no
// external deps; replace with the real wiring before any deploy.
func SetupTracing(ctx context.Context, cfg interface{ /* config.Config */ }) (ShutdownFunc, error) {
	_ = ctx
	_ = cfg
	return func(context.Context) error { return nil }, nil
}

// WrapHandler is the per-request HTTP middleware. Adds a request ID,
// records timing, and (when tracing is wired) starts a server span.
func WrapHandler(serviceName string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rw, r)
		slog.LogAttrs(r.Context(), slog.LevelInfo, "http",
			slog.String("svc", serviceName),
			slog.String("method", r.Method),
			slog.String("path", r.URL.Path),
			slog.Int("status", rw.status),
			slog.Duration("dur", time.Since(start)),
		)
	})
}

type responseWriter struct {
	http.ResponseWriter
	status int
}

func (r *responseWriter) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}
