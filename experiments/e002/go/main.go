package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const (
	maxConcurrent = 64
	workDeadline  = 750 * time.Millisecond
)

func main() {
	slots := make(chan struct{}, maxConcurrent)
	mux := http.NewServeMux()

	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	mux.HandleFunc("/work", func(w http.ResponseWriter, r *http.Request) {
		select {
		case slots <- struct{}{}:
			defer func() { <-slots }()
		default:
			http.Error(w, "overloaded", http.StatusServiceUnavailable)
			return
		}

		rawQuery := r.URL.RawQuery
		value, found := strings.CutPrefix(rawQuery, "ms=")
		if !found || value == "" || strings.ContainsAny(value, "&;") {
			http.Error(w, "invalid ms", http.StatusBadRequest)
			return
		}
		for _, character := range value {
			if character < '0' || character > '9' {
				http.Error(w, "invalid ms", http.StatusBadRequest)
				return
			}
		}
		ms, err := strconv.Atoi(value)
		if err != nil || ms > 5000 {
			http.Error(w, "invalid ms", http.StatusBadRequest)
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), workDeadline)
		defer cancel()

		timer := time.NewTimer(time.Duration(ms) * time.Millisecond)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			http.Error(w, "deadline exceeded", http.StatusGatewayTimeout)
		case <-timer.C:
			w.WriteHeader(http.StatusOK)
			_, _ = fmt.Fprintf(w, "completed:%d", ms)
		}
	})

	mux.HandleFunc("/stream", func(w http.ResponseWriter, r *http.Request) {
		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "streaming unsupported", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/octet-stream")
		for _, chunk := range []string{"chunk-1\n", "chunk-2\n", "chunk-3\n"} {
			select {
			case <-r.Context().Done():
				return
			default:
				if _, err := w.Write([]byte(chunk)); err != nil {
					return
				}
				flusher.Flush()
			}
		}
	})

	server := &http.Server{
		Addr:              "127.0.0.1:8080",
		Handler:           mux,
		ReadHeaderTimeout: 2 * time.Second,
		IdleTimeout:       30 * time.Second,
	}
	log.Fatal(server.ListenAndServe())
}
