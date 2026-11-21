package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func performRequest(t *testing.T, handler http.Handler, path string) *httptest.ResponseRecorder {
	t.Helper()
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
	return recorder
}

func TestParseWorkMS(t *testing.T) {
	tests := []struct {
		name    string
		query   string
		want    uint64
		wantErr bool
	}{
		{name: "zero", query: "ms=0", want: 0},
		{name: "normal", query: "ms=20", want: 20},
		{name: "leading zeroes are decimal digits", query: "ms=0020", want: 20},
		{name: "maximum", query: "ms=5000", want: maxWorkMS},
		{name: "missing query", query: "", wantErr: true},
		{name: "wrong key", query: "other=20", wantErr: true},
		{name: "empty value", query: "ms=", wantErr: true},
		{name: "additional parameter", query: "ms=20&x=1", wantErr: true},
		{name: "reordered parameter", query: "x=1&ms=20", wantErr: true},
		{name: "duplicate parameter", query: "ms=20&ms=21", wantErr: true},
		{name: "encoded key", query: "%6ds=20", wantErr: true},
		{name: "plus sign", query: "ms=+1", wantErr: true},
		{name: "minus sign", query: "ms=-1", wantErr: true},
		{name: "whitespace", query: "ms= 1", wantErr: true},
		{name: "over maximum", query: "ms=5001", wantErr: true},
		{name: "uint overflow", query: "ms=18446744073709551616", wantErr: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := parseWorkMS(test.query)
			if (err != nil) != test.wantErr {
				t.Fatalf("parseWorkMS(%q) error = %v, wantErr %v", test.query, err, test.wantErr)
			}
			if err == nil && got != test.want {
				t.Fatalf("parseWorkMS(%q) = %d, want %d", test.query, got, test.want)
			}
		})
	}
}

func TestWorkCompletesBeforeDeadline(t *testing.T) {
	recorder := performRequest(t, newHandler(1, time.Second), "/work?ms=20")
	if recorder.Code != http.StatusOK || recorder.Body.String() != "completed:20" {
		t.Fatalf("unexpected work response: %d %q", recorder.Code, recorder.Body.String())
	}
}

func TestWorkTimesOutAtRegisteredDeadline(t *testing.T) {
	if workDeadline != 750*time.Millisecond {
		t.Fatalf("registered deadline = %s, want 750ms", workDeadline)
	}
	recorder := performRequest(t, newHandler(1, 15*time.Millisecond), "/work?ms=900")
	if recorder.Code != http.StatusGatewayTimeout || !strings.HasPrefix(recorder.Body.String(), "deadline exceeded") {
		t.Fatalf("unexpected deadline response: %d %q", recorder.Code, recorder.Body.String())
	}
}

func TestWorkAdmissionIsBoundedAndReleasesCapacity(t *testing.T) {
	handler := newHandler(1, time.Second)
	app := handler.(*application)
	first := httptest.NewRecorder()
	firstDone := make(chan struct{})
	go func() {
		handler.ServeHTTP(first, httptest.NewRequest(http.MethodGet, "/work?ms=100", nil))
		close(firstDone)
	}()

	until := time.Now().Add(time.Second)
	for len(app.slots) == 0 && time.Now().Before(until) {
		time.Sleep(time.Millisecond)
	}
	if len(app.slots) != 1 {
		t.Fatal("first request did not acquire the only work slot")
	}

	overloaded := performRequest(t, handler, "/work?ms=0")
	if overloaded.Code != http.StatusServiceUnavailable || !strings.HasPrefix(overloaded.Body.String(), "overloaded") {
		t.Fatalf("unexpected overload response: %d %q", overloaded.Code, overloaded.Body.String())
	}
	<-firstDone
	if first.Code != http.StatusOK {
		t.Fatalf("first request failed: %d %q", first.Code, first.Body.String())
	}
	if len(app.slots) != 0 {
		t.Fatalf("work slot leaked after success: %d active", len(app.slots))
	}

	recovered := performRequest(t, handler, "/work?ms=0")
	if recovered.Code != http.StatusOK || recovered.Body.String() != "completed:0" {
		t.Fatalf("capacity was not reusable after success: %d %q", recovered.Code, recovered.Body.String())
	}
}

func TestWorkTimeoutReleasesAdmissionCapacity(t *testing.T) {
	handler := newHandler(1, 10*time.Millisecond)
	timedOut := performRequest(t, handler, "/work?ms=900")
	if timedOut.Code != http.StatusGatewayTimeout {
		t.Fatalf("expected 504 deadline response, got %d %q", timedOut.Code, timedOut.Body.String())
	}
	app := handler.(*application)
	if len(app.slots) != 0 {
		t.Fatalf("work slot leaked after timeout: %d active", len(app.slots))
	}
	recovered := performRequest(t, handler, "/work?ms=0")
	if recovered.Code != http.StatusOK || recovered.Body.String() != "completed:0" {
		t.Fatalf("capacity was not reusable after timeout: %d %q", recovered.Code, recovered.Body.String())
	}
}

func TestWorkFailureResponsesMatchHTTPContract(t *testing.T) {
	invalid := performRequest(t, newHandler(1, time.Second), "/work?ms=not-a-number")
	if invalid.Code != http.StatusBadRequest || !strings.HasPrefix(invalid.Body.String(), "invalid ms") {
		t.Fatalf("unexpected invalid-query response: %d %q", invalid.Code, invalid.Body.String())
	}

	handler := newHandler(1, time.Second)
	app := handler.(*application)
	app.slots <- struct{}{}
	overloaded := performRequest(t, handler, "/work?ms=20")
	if overloaded.Code != http.StatusServiceUnavailable || !strings.HasPrefix(overloaded.Body.String(), "overloaded") {
		t.Fatalf("unexpected overload response: %d %q", overloaded.Code, overloaded.Body.String())
	}
}

func TestStreamPreservesOrderedChunks(t *testing.T) {
	recorder := performRequest(t, newHandler(1, time.Second), "/stream")
	want := "chunk-1\nchunk-2\nchunk-3\n"
	if recorder.Code != http.StatusOK || recorder.Body.String() != want {
		t.Fatalf("unexpected stream response: %d %q", recorder.Code, recorder.Body.String())
	}
	if got := recorder.Header().Get("Content-Type"); got != "application/octet-stream" {
		t.Fatalf("stream content type = %q", got)
	}
}

func TestHealthAndUnknownRoute(t *testing.T) {
	handler := newHandler(1, time.Second)
	health := performRequest(t, handler, "/health")
	if health.Code != http.StatusOK || health.Body.String() != "ok" {
		t.Fatalf("unexpected health response: %d %q", health.Code, health.Body.String())
	}
	missing := performRequest(t, handler, "/missing")
	if missing.Code != http.StatusNotFound {
		t.Fatalf("unknown route status = %d, want 404", missing.Code)
	}
}

func TestRegisteredAdmissionLimitIs64(t *testing.T) {
	handler := newHandler(maxConcurrent, workDeadline)
	app := handler.(*application)
	if got := cap(app.slots); got != 64 {
		t.Fatalf("registered active-work capacity = %d, want 64", got)
	}
}
