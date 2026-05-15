package providers

import "fmt"

// Registry is a tiny lookup of named providers wired at startup.
type Registry struct {
	byName map[string]Provider
}

func NewRegistry() *Registry { return &Registry{byName: make(map[string]Provider)} }

func (r *Registry) Register(p Provider) { r.byName[p.Name()] = p }

func (r *Registry) Get(name string) (Provider, error) {
	p, ok := r.byName[name]
	if !ok {
		return nil, fmt.Errorf("unknown provider %q", name)
	}
	return p, nil
}
