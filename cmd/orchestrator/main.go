// Command orchestrator consumes asynq tasks and drives the GPU provider
// to provision/terminate session nodes.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/hibiken/asynq"
	"github.com/jackc/pgx/v5"

	"github.com/gaymr/gaymr/internal/config"
	"github.com/gaymr/gaymr/internal/jobs"
	"github.com/gaymr/gaymr/internal/obs"
	"github.com/gaymr/gaymr/internal/providers"
	awsmanaged "github.com/gaymr/gaymr/internal/providers/aws_managed"
	"github.com/gaymr/gaymr/internal/store"
	"github.com/gaymr/gaymr/internal/store/sqlc"
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

	cfg, err := config.Load("orchestrator")
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}
	logger := obs.NewLogger(cfg.LogLevel)
	slog.SetDefault(logger)

	if cfg.DatabaseURL == "" || cfg.RedisURL == "" {
		return errors.New("DATABASE_URL and REDIS_URL are required")
	}
	st, err := store.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return fmt.Errorf("store: %w", err)
	}
	defer st.Close()

	provisionScript := os.Getenv("AWS_PROVISION_SCRIPT")
	if provisionScript == "" {
		provisionScript = "infra/sunshine-node/provision-remote.sh"
	}
	awsProv, err := awsmanaged.New(ctx, awsmanaged.Config{
		Region:          cfg.AWSGPURegion,
		AMIParam:        cfg.AWSGPUAMIParam,
		KeyPair:         cfg.AWSGPUKeyPair,
		SecurityGroupID: os.Getenv("AWS_GPU_SG_ID"),
		ProvisionScript: provisionScript,
		SSHKeyPath:      os.Getenv("AWS_GPU_SSH_KEY"),
	})
	if err != nil {
		return fmt.Errorf("aws-managed provider: %w", err)
	}
	registry := providers.NewRegistry()
	registry.Register(awsProv)

	h := &handler{store: st, registry: registry, defaultProvider: "aws-managed"}

	redisOpt, err := jobs.RedisOpt(cfg.RedisURL)
	if err != nil {
		return fmt.Errorf("redis opt: %w", err)
	}
	srv := asynq.NewServer(redisOpt, asynq.Config{
		Concurrency: 4,
		Logger:      &asynqSlog{},
	})
	mux := asynq.NewServeMux()
	mux.HandleFunc(jobs.TypeProvisionSession, h.handleProvision)
	mux.HandleFunc(jobs.TypeTerminateSession, h.handleTerminate)

	errCh := make(chan error, 1)
	go func() {
		slog.Info("orchestrator started")
		if err := srv.Run(mux); err != nil {
			errCh <- err
		}
	}()
	select {
	case <-ctx.Done():
		slog.Info("orchestrator draining...")
		srv.Shutdown()
	case err := <-errCh:
		return err
	}
	return nil
}

type handler struct {
	store           *store.Store
	registry        *providers.Registry
	defaultProvider string
}

func (h *handler) handleProvision(ctx context.Context, t *asynq.Task) error {
	var p jobs.SessionPayload
	if err := json.Unmarshal(t.Payload(), &p); err != nil {
		return fmt.Errorf("decode: %w", err)
	}
	sess, err := h.store.GetSession(ctx, p.SessionID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil // gone
		}
		return err
	}
	if sess.Status != sqlc.SessionStatusPending {
		slog.Info("skip provision", "session", p.SessionID, "status", sess.Status)
		return nil
	}
	if err := h.store.SetSessionStatus(ctx, sqlc.SetSessionStatusParams{
		ID: p.SessionID, Status: sqlc.SessionStatusProvisioning,
	}); err != nil {
		return err
	}
	prov, err := h.registry.Get(h.defaultProvider)
	if err != nil {
		return h.fail(ctx, p.SessionID, err)
	}
	pctx, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()
	node, err := prov.Provision(pctx, providers.SessionRequest{
		SessionID: sess.ID,
		UserID:    uuidString(sess.UserID.Bytes),
		Region:    sess.Region,
		SKU:       sess.Sku,
	})
	if err != nil {
		return h.fail(ctx, p.SessionID, err)
	}
	if err := h.store.SetSessionReady(ctx, sqlc.SetSessionReadyParams{
		ID:         p.SessionID,
		InstanceID: &node.NodeID,
		PublicIp:   &node.PublicIP,
	}); err != nil {
		return err
	}
	slog.Info("session ready", "session", p.SessionID, "instance", node.NodeID, "ip", node.PublicIP)
	return nil
}

func (h *handler) handleTerminate(ctx context.Context, t *asynq.Task) error {
	var p jobs.SessionPayload
	if err := json.Unmarshal(t.Payload(), &p); err != nil {
		return fmt.Errorf("decode: %w", err)
	}
	sess, err := h.store.GetSession(ctx, p.SessionID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil
		}
		return err
	}
	prov, err := h.registry.Get(h.defaultProvider)
	if err != nil {
		return err
	}
	if sess.InstanceID != nil && *sess.InstanceID != "" {
		if err := prov.Terminate(ctx, *sess.InstanceID); err != nil {
			slog.Error("terminate failed", "err", err, "instance", *sess.InstanceID)
			// fall through; mark terminated anyway so we don't loop forever.
		}
	}
	return h.store.SetSessionTerminated(ctx, p.SessionID)
}

func (h *handler) fail(ctx context.Context, id string, cause error) error {
	reason := cause.Error()
	_ = h.store.SetSessionError(ctx, sqlc.SetSessionErrorParams{ID: id, ErrorReason: &reason})
	return cause
}

func uuidString(b [16]byte) string {
	var u uuid.UUID
	copy(u[:], b[:])
	return u.String()
}

type asynqSlog struct{}

func (a *asynqSlog) Debug(args ...any) { slog.Debug("asynq", "msg", fmt.Sprint(args...)) }
func (a *asynqSlog) Info(args ...any)  { slog.Info("asynq", "msg", fmt.Sprint(args...)) }
func (a *asynqSlog) Warn(args ...any)  { slog.Warn("asynq", "msg", fmt.Sprint(args...)) }
func (a *asynqSlog) Error(args ...any) { slog.Error("asynq", "msg", fmt.Sprint(args...)) }
func (a *asynqSlog) Fatal(args ...any) { slog.Error("asynq fatal", "msg", fmt.Sprint(args...)) }
