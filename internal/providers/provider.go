// Package providers defines the GPU provider abstraction.
//
// All implementations (aws_managed, aws_byoc, vastai, runpod) satisfy the
// Provider interface. The orchestrator depends only on this interface; new
// providers are added by writing one file plus a registration entry.
package providers

import (
	"context"
	"errors"
	"time"
)

// SessionRequest captures everything a provider needs to launch a node.
type SessionRequest struct {
	SessionID string
	UserID    string
	Region    string // e.g. "ap-south-1"
	SKU       string // e.g. "g4dn.xlarge"
}

// Node is the provider's response after a successful Provision.
type Node struct {
	NodeID    string    // provider-specific ID (e.g. "i-0abc...")
	PublicIP  string    // accessible from the browser for WebRTC
	Region    string
	SKU       string
	StartedAt time.Time
}

// NodeStatus is the response from GetStatus.
type NodeStatus struct {
	NodeID string
	State  string // "pending" | "running" | "stopping" | "terminated" | "error"
	Reason string // populated on error
}

// Provider is implemented by every GPU backend.
type Provider interface {
	// Name returns a stable identifier (e.g. "aws-managed", "vastai").
	Name() string

	// Provision launches an instance and blocks until it's reachable.
	Provision(ctx context.Context, req SessionRequest) (*Node, error)

	// Terminate stops the instance. Idempotent.
	Terminate(ctx context.Context, nodeID string) error

	// GetStatus returns the current lifecycle state.
	GetStatus(ctx context.Context, nodeID string) (*NodeStatus, error)

	// EstimatedCostPerSecond returns the rate this provider charges for the
	// given SKU. Used for billing math and the user-facing cost estimate.
	EstimatedCostPerSecond(sku string) (float64, error)
}

// ErrProviderUnavailable is returned when the provider's API is failing
// the circuit breaker. Callers should retry with a different provider or
// surface a retryable error to the user.
var ErrProviderUnavailable = errors.New("provider unavailable")

// ErrUnsupportedSKU is returned when the requested SKU isn't offered by
// this provider in this region.
var ErrUnsupportedSKU = errors.New("unsupported SKU")
