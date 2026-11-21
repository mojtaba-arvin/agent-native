package catalog

import "testing"

func TestCreateAndGetItem(t *testing.T) {
	repository := NewMemoryRepository()
	service := NewService(repository, StaticAuthorizer{
		"items.read": true, "items.create": true,
	})

	created, err := service.CreateItem("Desk lamp")
	if err != nil {
		t.Fatal(err)
	}
	got, err := service.GetItem(created.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got != created {
		t.Fatalf("got %#v, want %#v", got, created)
	}
}

func TestGetMissingItemReturnsStableNotFound(t *testing.T) {
	service := NewService(NewMemoryRepository(), StaticAuthorizer{"items.read": true})
	_, err := service.GetItem("missing")
	if serviceErrorCode(err) != NotFound {
		t.Fatalf("got %v, want %s", err, NotFound)
	}
}

func TestCreateRejectsBlankName(t *testing.T) {
	service := NewService(NewMemoryRepository(), StaticAuthorizer{"items.create": true})
	_, err := service.CreateItem("  ")
	if serviceErrorCode(err) != InvalidInput {
		t.Fatalf("got %v, want %s", err, InvalidInput)
	}
}

func TestAuthorizationIsRequiredBeforeRepositoryAccess(t *testing.T) {
	service := NewService(NewMemoryRepository(), StaticAuthorizer{})
	_, err := service.CreateItem("Desk lamp")
	if serviceErrorCode(err) != Unauthorized {
		t.Fatalf("got %v, want %s", err, Unauthorized)
	}
}

func serviceErrorCode(err error) ErrorCode {
	if value, ok := err.(*ServiceError); ok {
		return value.Code
	}
	return ""
}
