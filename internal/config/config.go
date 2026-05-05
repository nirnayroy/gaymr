// Package config loads typed configuration from environment variables.
//
// Precedence: env > .env (loaded by docker-compose / direnv) > defaults.
// On startup, services call Load() and a missing required value returns
// an error rather than silently defaulting.
package config

import (
	"fmt"
	"os"
	"strconv"
)

// Config is the union of all settings any service may need.
// Services use the subset they care about; missing optional values are
// zero-valued.
type Config struct {
	Service  string
	Port     string
	LogLevel string

	DatabaseURL string
	RedisURL    string

	// Observability.
	OTelEndpoint    string
	OTelSampler     string
	OTelServiceName string

	// AWS / providers (loaded lazily by callers that need them).
	AWSRegion       string
	AWSGPURegion    string
	AWSGPUAMIParam  string
	AWSGPUKeyPair   string
	StripeSecretKey string
	ClerkSecretKey  string
	ClerkJWTIssuer  string
}

// Load reads the environment and returns a Config. The serviceName argument
// is the OTel service.name attribute (e.g. "api", "orchestrator").
func Load(serviceName string) (*Config, error) {
	cfg := &Config{
		Service:  serviceName,
		Port:     getenv("PORT", "8080"),
		LogLevel: getenv("LOG_LEVEL", "info"),

		DatabaseURL: os.Getenv("DATABASE_URL"),
		RedisURL:    os.Getenv("REDIS_URL"),

		OTelEndpoint:    getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
		OTelSampler:     getenv("OTEL_TRACES_SAMPLER", "parentbased_always_on"),
		OTelServiceName: getenv("OTEL_SERVICE_NAME", "gaymr-"+serviceName),

		AWSRegion:       getenv("AWS_REGION", "us-east-1"),
		AWSGPURegion:    getenv("AWS_GPU_REGION", "ap-south-1"),
		AWSGPUAMIParam:  getenv("AWS_GPU_AMI_PARAM", "/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id"),
		AWSGPUKeyPair:   os.Getenv("AWS_GPU_KEYPAIR"),
		StripeSecretKey: os.Getenv("STRIPE_SECRET_KEY"),
		ClerkSecretKey:  os.Getenv("CLERK_SECRET_KEY"),
		ClerkJWTIssuer:  os.Getenv("CLERK_JWT_ISSUER"),
	}
	return cfg, nil
}

// MustGet returns a required env var or fails.
func MustGet(key string) (string, error) {
	v := os.Getenv(key)
	if v == "" {
		return "", fmt.Errorf("required env var %s is not set", key)
	}
	return v, nil
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// GetenvInt is a helper for numeric env vars.
func GetenvInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return n
}
