package jobs

import (
	"encoding/json"
	"testing"
)

func TestProvisionPayloadRoundtrip(t *testing.T) {
	task, err := NewProvision("sess_abc")
	if err != nil {
		t.Fatal(err)
	}
	if task.Type() != TypeProvisionSession {
		t.Errorf("type = %q, want %q", task.Type(), TypeProvisionSession)
	}
	var p SessionPayload
	if err := json.Unmarshal(task.Payload(), &p); err != nil {
		t.Fatal(err)
	}
	if p.SessionID != "sess_abc" {
		t.Errorf("session = %q, want sess_abc", p.SessionID)
	}
}

func TestTerminatePayloadRoundtrip(t *testing.T) {
	task, err := NewTerminate("sess_xyz")
	if err != nil {
		t.Fatal(err)
	}
	if task.Type() != TypeTerminateSession {
		t.Errorf("type = %q, want %q", task.Type(), TypeTerminateSession)
	}
}
