// Package jobs defines the asynq task types and helpers for enqueueing
// session lifecycle work.
package jobs

import (
	"encoding/json"

	"github.com/hibiken/asynq"
)

const (
	TypeProvisionSession = "session:provision"
	TypeTerminateSession = "session:terminate"
)

type SessionPayload struct {
	SessionID string `json:"session_id"`
}

func NewProvision(sessionID string) (*asynq.Task, error) {
	b, err := json.Marshal(SessionPayload{SessionID: sessionID})
	if err != nil {
		return nil, err
	}
	return asynq.NewTask(TypeProvisionSession, b, asynq.MaxRetry(2)), nil
}

func NewTerminate(sessionID string) (*asynq.Task, error) {
	b, err := json.Marshal(SessionPayload{SessionID: sessionID})
	if err != nil {
		return nil, err
	}
	return asynq.NewTask(TypeTerminateSession, b, asynq.MaxRetry(3)), nil
}

func RedisOpt(redisURL string) (asynq.RedisConnOpt, error) {
	return asynq.ParseRedisURI(redisURL)
}
