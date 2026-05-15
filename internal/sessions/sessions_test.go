package sessions

import (
	"strings"
	"testing"
)

func TestNewSessionIDFormat(t *testing.T) {
	id := newSessionID()
	if !strings.HasPrefix(id, "sess_") {
		t.Errorf("prefix = %q", id)
	}
	if len(id) != 5+24 {
		t.Errorf("length = %d, want 29", len(id))
	}
	// unique-ish
	if newSessionID() == id {
		t.Error("collision in two calls")
	}
}
