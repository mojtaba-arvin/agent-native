package catalog

import (
	"fmt"
	"strings"
	"sync"
)

type ErrorCode string

const (
	Unauthorized ErrorCode = "unauthorized"
	NotFound     ErrorCode = "not_found"
	InvalidInput ErrorCode = "invalid_input"
)

type ServiceError struct {
	Code ErrorCode
}

func (e *ServiceError) Error() string { return string(e.Code) }

type Item struct {
	ID   string
	Name string
}

type Repository interface {
	Get(id string) (Item, bool)
	Create(name string) Item
}

type Authorizer interface {
	Require(capability string) bool
}

type Service struct {
	repository Repository
	authorizer Authorizer
}

func NewService(repository Repository, authorizer Authorizer) *Service {
	return &Service{repository: repository, authorizer: authorizer}
}

func (s *Service) GetItem(id string) (Item, error) {
	if !s.authorizer.Require("items.read") {
		return Item{}, &ServiceError{Code: Unauthorized}
	}
	item, ok := s.repository.Get(id)
	if !ok {
		return Item{}, &ServiceError{Code: NotFound}
	}
	return item, nil
}

func (s *Service) CreateItem(name string) (Item, error) {
	if !s.authorizer.Require("items.create") {
		return Item{}, &ServiceError{Code: Unauthorized}
	}
	if strings.TrimSpace(name) == "" {
		return Item{}, &ServiceError{Code: InvalidInput}
	}
	return s.repository.Create(name), nil
}

type MemoryRepository struct {
	mu     sync.RWMutex
	items  map[string]Item
	nextID uint64
}

func NewMemoryRepository() *MemoryRepository {
	return &MemoryRepository{items: make(map[string]Item)}
}

func (r *MemoryRepository) Get(id string) (Item, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	item, ok := r.items[id]
	return item, ok
}

func (r *MemoryRepository) Create(name string) Item {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.nextID++
	id := fmt.Sprintf("item-%d", r.nextID)
	item := Item{ID: id, Name: name}
	r.items[id] = item
	return item
}

type StaticAuthorizer map[string]bool

func (a StaticAuthorizer) Require(capability string) bool {
	return a[capability]
}
