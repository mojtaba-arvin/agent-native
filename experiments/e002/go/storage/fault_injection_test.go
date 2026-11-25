package storage

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestRollbackAfterEachLogicalWrite(t *testing.T) {
	stages := []string{"after_job", "after_outbox", "after_idempotency", "after_audit", "before_commit"}
	for _, stage := range stages {
		t.Run(stage, func(t *testing.T) {
			adapter := openTestAdapter(t, true, withFaultHook(func(current string) error {
				if current == stage {
					return errors.New("injected_precommit_failure")
				}
				return nil
			}))
			_, err := adapter.AdmitJob(context.Background(),
				testAdmission("fault-"+stage, "tenant-a", "jobs.create", "fault-key", "lamp"))
			if err == nil {
				t.Fatal("injected pre-commit failure unexpectedly committed")
			}
			counts, err := adapter.Recover(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			if counts.Jobs != 0 || counts.Outbox != 0 || counts.Idempotency != 0 || counts.Audit != 0 {
				t.Fatalf("partial transaction survived %s: %+v", stage, counts)
			}
		})
	}
}

func TestCrashAfterCommitBeforeResponseReconciles(t *testing.T) {
	if os.Getenv("E002_GO_CRASH_HELPER") == "1" {
		dsn := os.Getenv("E002_GO_DSN")
		marker := os.Getenv("E002_GO_MARKER")
		adapter, err := NewPostgresAdapter(context.Background(), dsn,
			WithSchema(testSchema),
			WithFaultHook(func(stage string) error {
				if stage == "after_commit" {
					if err := os.WriteFile(marker, []byte("committed"), 0o600); err != nil {
						return err
					}
					for {
						time.Sleep(time.Second)
					}
				}
				return nil
			}),
		)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		_, err = adapter.AdmitJob(context.Background(),
			testAdmission("crash-before-response", "tenant-a", "jobs.create", "crash-key", "lamp"))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(3)
		}
		os.Exit(0)
	}

	adapter := openTestAdapter(t, true)
	dsn := os.Getenv("AGENT_NATIVE_E002_POSTGRES_DSN")
	if err := adapter.Close(); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(t.TempDir(), "committed.marker")
	command := exec.Command(os.Args[0], "-test.run=^TestCrashAfterCommitBeforeResponseReconciles$")
	command.Env = append(os.Environ(),
		"E002_GO_CRASH_HELPER=1",
		"E002_GO_DSN="+dsn,
		"E002_GO_MARKER="+marker,
	)
	var stdout, stderr bytes.Buffer
	command.Stdout = &stdout
	command.Stderr = &stderr
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	waited := make(chan error, 1)
	go func() { waited <- command.Wait() }()
	deadline := time.Now().Add(20 * time.Second)
	for {
		select {
		case waitErr := <-waited:
			t.Fatalf("child exited before post-commit pause: %v %s %s", waitErr, stdout.String(), stderr.String())
		default:
		}
		if _, err := os.Stat(marker); err == nil {
			break
		}
		if time.Now().After(deadline) {
			_ = command.Process.Kill()
			<-waited
			t.Fatalf("child did not reach post-commit pause: %s %s", stdout.String(), stderr.String())
		}
		time.Sleep(25 * time.Millisecond)
	}
	select {
	case waitErr := <-waited:
		t.Fatalf("child exited after commit marker before SIGKILL: %v", waitErr)
	default:
	}
	if err := command.Process.Kill(); err != nil {
		t.Fatalf("kill post-commit child: %v", err)
	}
	if err := <-waited; err == nil {
		t.Fatal("child survived SIGKILL")
	}

	reopened := openTestAdapter(t, false)
	result, err := reopened.AdmitJob(context.Background(),
		testAdmission("retry-after-crash", "tenant-a", "jobs.create", "crash-key", "lamp"))
	if err != nil {
		t.Fatal(err)
	}
	if result.Status != "replayed" {
		t.Fatalf("ambiguous commit did not reconcile as replay: %+v", result)
	}
	counts, err := reopened.Recover(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if counts.Jobs != 1 || counts.Outbox != 1 || counts.Idempotency != 1 || counts.Audit != 2 {
		t.Fatalf("post-crash state is not exactly-once logical admission plus retry audit: %+v", counts)
	}
}
