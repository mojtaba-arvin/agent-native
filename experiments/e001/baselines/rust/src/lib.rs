use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Item {
    pub id: String,
    pub name: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ErrorCode {
    Unauthorized,
    NotFound,
    InvalidInput,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ServiceError {
    pub code: ErrorCode,
}

pub trait Repository: Send + Sync {
    fn get(&self, id: &str) -> Option<Item>;
    fn create(&self, name: &str) -> Item;
}

pub trait Authorizer: Send + Sync {
    fn require(&self, capability: &str) -> bool;
}

pub struct Service {
    repository: Arc<dyn Repository>,
    authorizer: Arc<dyn Authorizer>,
}

impl Service {
    pub fn new(repository: Arc<dyn Repository>, authorizer: Arc<dyn Authorizer>) -> Self {
        Self { repository, authorizer }
    }

    pub fn get_item(&self, id: &str) -> Result<Item, ServiceError> {
        if !self.authorizer.require("items.read") {
            return Err(ServiceError { code: ErrorCode::Unauthorized });
        }
        self.repository
            .get(id)
            .ok_or(ServiceError { code: ErrorCode::NotFound })
    }

    pub fn create_item(&self, name: &str) -> Result<Item, ServiceError> {
        if !self.authorizer.require("items.create") {
            return Err(ServiceError { code: ErrorCode::Unauthorized });
        }
        if name.trim().is_empty() {
            return Err(ServiceError { code: ErrorCode::InvalidInput });
        }
        Ok(self.repository.create(name))
    }
}

#[derive(Default)]
pub struct MemoryRepository {
    state: Mutex<(HashMap<String, Item>, u64)>,
}

impl Repository for MemoryRepository {
    fn get(&self, id: &str) -> Option<Item> {
        self.state.lock().expect("repository lock poisoned").0.get(id).cloned()
    }

    fn create(&self, name: &str) -> Item {
        let mut state = self.state.lock().expect("repository lock poisoned");
        state.1 += 1;
        let item = Item {
            id: format!("00000000-0000-0000-0000-{:012}", state.1),
            name: name.to_owned(),
        };
        state.0.insert(item.id.clone(), item.clone());
        item
    }
}

pub struct StaticAuthorizer {
    capabilities: HashSet<String>,
}

impl StaticAuthorizer {
    pub fn new(capabilities: impl IntoIterator<Item = impl Into<String>>) -> Self {
        Self { capabilities: capabilities.into_iter().map(Into::into).collect() }
    }
}

impl Authorizer for StaticAuthorizer {
    fn require(&self, capability: &str) -> bool {
        self.capabilities.contains(capability)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn service(capabilities: &[&str]) -> Service {
        Service::new(
            Arc::new(MemoryRepository::default()),
            Arc::new(StaticAuthorizer::new(capabilities.iter().copied())),
        )
    }

    #[test]
    fn create_and_get_item() {
        let service = service(&["items.read", "items.create"]);
        let created = service.create_item("Desk lamp").unwrap();
        assert_eq!(service.get_item(&created.id).unwrap(), created);
    }

    #[test]
    fn missing_item_has_stable_error() {
        let error = service(&["items.read"]).get_item("missing").unwrap_err();
        assert_eq!(error.code, ErrorCode::NotFound);
    }

    #[test]
    fn blank_name_is_rejected() {
        let error = service(&["items.create"]).create_item("  ").unwrap_err();
        assert_eq!(error.code, ErrorCode::InvalidInput);
    }

    #[test]
    fn authorization_is_required_before_repository_access() {
        let error = service(&[]).create_item("Desk lamp").unwrap_err();
        assert_eq!(error.code, ErrorCode::Unauthorized);
    }
}
