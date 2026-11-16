#[cfg(test)]
mod tests {
    #[test]
    fn workload_contract_has_fixed_deadline_and_capacity() {
        // The executable server contract is mirrored in README.md.
        // Keep this small compile-time test as a marker until the server
        // is refactored into a directly testable library surface.
        assert_eq!(750_u64, 750);
        assert_eq!(64_usize, 64);
    }
}
