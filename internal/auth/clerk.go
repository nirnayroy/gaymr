// Package auth verifies Clerk-issued JWTs and resolves them to a local user row.
package auth

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/MicahParks/keyfunc/v3"
	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"

	"github.com/gaymr/gaymr/internal/store"
	"github.com/gaymr/gaymr/internal/store/sqlc"
)

type Claims struct {
	Subject string
	Email   string
	UserID  uuid.UUID // local users.id, populated after upsert
}

type ctxKey struct{}

func FromContext(ctx context.Context) (Claims, bool) {
	c, ok := ctx.Value(ctxKey{}).(Claims)
	return c, ok
}

type Verifier struct {
	keyfunc keyfunc.Keyfunc
	issuer  string
	store   *store.Store
}

func NewVerifier(ctx context.Context, issuer string, st *store.Store) (*Verifier, error) {
	if issuer == "" {
		return nil, errors.New("CLERK_JWT_ISSUER is empty")
	}
	jwksURL := strings.TrimRight(issuer, "/") + "/.well-known/jwks.json"
	kf, err := keyfunc.NewDefaultCtx(ctx, []string{jwksURL})
	if err != nil {
		return nil, fmt.Errorf("fetch jwks %s: %w", jwksURL, err)
	}
	return &Verifier{keyfunc: kf, issuer: issuer, store: st}, nil
}

// Middleware verifies the Bearer token, upserts the user, and injects Claims.
func (v *Verifier) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth := r.Header.Get("Authorization")
		if !strings.HasPrefix(auth, "Bearer ") {
			http.Error(w, "missing bearer token", http.StatusUnauthorized)
			return
		}
		raw := strings.TrimPrefix(auth, "Bearer ")
		tok, err := jwt.Parse(raw, v.keyfunc.Keyfunc,
			jwt.WithIssuer(v.issuer),
			jwt.WithExpirationRequired(),
			jwt.WithLeeway(30*time.Second),
		)
		if err != nil || !tok.Valid {
			http.Error(w, "invalid token", http.StatusUnauthorized)
			return
		}
		mc, ok := tok.Claims.(jwt.MapClaims)
		if !ok {
			http.Error(w, "invalid claims", http.StatusUnauthorized)
			return
		}
		sub, _ := mc["sub"].(string)
		if sub == "" {
			http.Error(w, "missing sub", http.StatusUnauthorized)
			return
		}
		email, _ := mc["email"].(string)

		var emailPtr *string
		if email != "" {
			emailPtr = &email
		}
		u, err := v.store.UpsertUser(r.Context(), sqlc.UpsertUserParams{
			ClerkSubject: sub,
			Email:        emailPtr,
		})
		if err != nil {
			http.Error(w, "user resolve failed", http.StatusInternalServerError)
			return
		}
		var uid uuid.UUID
		_ = uid.UnmarshalBinary(u.ID.Bytes[:])
		ctx := context.WithValue(r.Context(), ctxKey{}, Claims{
			Subject: sub,
			Email:   email,
			UserID:  uid,
		})
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
