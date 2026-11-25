package main

import (
	"context"
	"errors"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const (
	maxConcurrent = 64
	maxWorkMS     = uint64(5000)
	workDeadline  = 750 * time.Millisecond
)

var errInvalidWorkQuery = errors.New("invalid ms")

type application struct {
	slots    chan struct{}
	deadline time.Duration
	product  *productService
}

func newHandler(maxActive int, deadline time.Duration) http.Handler {
	if maxActive < 1 {
		panic("maxActive must be positive")
	}
	if deadline <= 0 {
		panic("deadline must be positive")
	}
	return &application{slots: make(chan struct{}, maxActive), deadline: deadline}
}

// parseWorkMS accepts only the exact raw query shape ms=<ASCII decimal digits>.
func parseWorkMS(rawQuery string) (uint64, error) {
	if !strings.HasPrefix(rawQuery, "ms=") {
		return 0, errInvalidWorkQuery
	}
	value := rawQuery[len("ms="):]
	if value == "" {
		return 0, errInvalidWorkQuery
	}
	for i := 0; i < len(value); i++ {
		if value[i] < '0' || value[i] > '9' {
			return 0, errInvalidWorkQuery
		}
	}
	ms, err := strconv.ParseUint(value, 10, 64)
	if err != nil || ms > maxWorkMS {
		return 0, errInvalidWorkQuery
	}
	return ms, nil
}

func (app *application) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if strings.HasPrefix(r.URL.Path, "/v1/") {
		app.serveProduct(w, r)
		return
	}
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	switch r.URL.Path {
	case "/health":
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "ok")
	case "/work":
		app.serveWork(w, r)
	case "/stream":
		app.serveStream(w, r)
	default:
		http.NotFound(w, r)
	}
}

func (app *application) serveWork(w http.ResponseWriter, r *http.Request) {
	ms, err := parseWorkMS(r.URL.RawQuery)
	if err != nil {
		http.Error(w, "invalid ms", http.StatusBadRequest)
		return
	}

	select {
	case app.slots <- struct{}{}:
		defer func() { <-app.slots }()
	default:
		http.Error(w, "overloaded", http.StatusServiceUnavailable)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), app.deadline)
	defer cancel()

	timer := time.NewTimer(time.Duration(ms) * time.Millisecond)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		if r.Context().Err() != nil {
			return
		}
		http.Error(w, "deadline exceeded", http.StatusGatewayTimeout)
	case <-timer.C:
		if r.Context().Err() != nil {
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "completed:"+strconv.FormatUint(ms, 10))
	}
}

func (app *application) serveStream(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/octet-stream")
	for _, chunk := range []string{"chunk-1\n", "chunk-2\n", "chunk-3\n"} {
		if r.Context().Err() != nil {
			return
		}
		if _, err := io.WriteString(w, chunk); err != nil {
			return
		}
		flusher.Flush()
	}
}

func main() {
	handler := newHandler(maxConcurrent, workDeadline)
	product, err := newProductServiceFromEnv()
	if err != nil {
		log.Fatal(err)
	}
	if product != nil {
		handler.(*application).product = product
		defer product.pool.close()
	}
	server := &http.Server{
		Addr:              "127.0.0.1:8080",
		Handler:           handler,
		ReadHeaderTimeout: 2 * time.Second,
		IdleTimeout:       30 * time.Second,
	}
	log.Fatal(server.ListenAndServe())
}
