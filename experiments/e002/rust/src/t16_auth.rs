use std::{
    ffi::{c_int, c_uchar, c_uint},
    time::{SystemTime, UNIX_EPOCH},
};

#[repr(C)]
struct EvpMd {
    _private: [u8; 0],
}

#[link(name = "crypto")]
extern "C" {
    fn EVP_sha256() -> *const EvpMd;
    fn HMAC(
        evp_md: *const EvpMd,
        key: *const c_uchar,
        key_len: c_int,
        data: *const c_uchar,
        data_len: usize,
        output: *mut c_uchar,
        output_len: *mut c_uint,
    ) -> *mut c_uchar;
}

fn hmac_sha256(key: &[u8], message: &[u8]) -> Result<[u8; 32], String> {
    let mut output = [0u8; 32];
    let mut output_len = 0u32;
    let result = unsafe {
        HMAC(
            EVP_sha256(),
            key.as_ptr(),
            key.len() as c_int,
            message.as_ptr(),
            message.len(),
            output.as_mut_ptr(),
            &mut output_len,
        )
    };
    if result.is_null() || output_len != 32 {
        return Err("hmac_sha256_failed".to_owned());
    }
    Ok(output)
}

pub fn decode_hex(value: &str) -> Result<Vec<u8>, String> {
    if value.len() % 2 != 0 {
        return Err("invalid_hex".to_owned());
    }
    let mut output = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let text = std::str::from_utf8(pair).map_err(|_| "invalid_hex".to_owned())?;
        output.push(u8::from_str_radix(text, 16).map_err(|_| "invalid_hex".to_owned())?);
    }
    Ok(output)
}

fn encode_hex(value: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(value.len() * 2);
    for byte in value {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut difference = 0u8;
    for (a, b) in left.iter().zip(right.iter()) {
        difference |= a ^ b;
    }
    difference == 0
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn valid_capability(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_'))
}

fn valid_resource_prefix(value: &str) -> bool {
    value.starts_with('/')
        && !value.contains("//")
        && !value.chars().any(|ch| matches!(ch, '|' | '~' | ',' | ';' | '?' | '#' | '%' | '\\') || ch.is_control())
        && value.split('/').all(|segment| segment != "." && segment != "..")
}

#[derive(Clone)]
pub struct Grant {
    pub capability: String,
    pub resource_prefix: String,
    pub expires_at: Option<i64>,
}

pub struct Principal {
    pub principal_id: String,
    pub tenant_id: String,
    pub expires_at: i64,
    pub grants: Vec<Grant>,
}

pub fn verify_bearer(authorization: &str, key: &[u8]) -> Result<Principal, String> {
    if key.len() < 32 {
        return Err("invalid_signing_key".to_owned());
    }
    let token = authorization.strip_prefix("Bearer ").ok_or("invalid_bearer_scheme")?;
    if token.is_empty() || token.len() > 8192 {
        return Err("malformed_bearer_token".to_owned());
    }
    let (payload, signature_text) = token.rsplit_once('.').ok_or("malformed_bearer_token")?;
    let supplied = decode_hex(signature_text)?;
    if supplied.len() != 32 {
        return Err("invalid_token_signature_encoding".to_owned());
    }
    let expected = hmac_sha256(key, payload.as_bytes())?;
    if !constant_time_equal(&expected, &supplied) {
        return Err("invalid_token_signature".to_owned());
    }

    let fields: Vec<&str> = payload.split('|').collect();
    if fields.len() != 8
        || fields[0] != "AN-CAP-V1"
        || fields[1] != "agent-native"
        || fields[2] != "agent-native-api"
    {
        return Err("invalid_token_claims".to_owned());
    }
    if !valid_identity(fields[5]) || !valid_identity(fields[6]) || fields[7].is_empty() {
        return Err("invalid_token_identity_or_grants".to_owned());
    }
    let issued_at: i64 = fields[3].parse().map_err(|_| "invalid_token_time")?;
    let expires_at: i64 = fields[4].parse().map_err(|_| "invalid_token_time")?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "trusted_clock_unavailable")?
        .as_secs() as i64;
    if issued_at < 0
        || issued_at > now
        || expires_at <= now
        || expires_at <= issued_at
        || expires_at - issued_at > 900
    {
        return Err("token_expired_or_outside_validity_window".to_owned());
    }

    let items: Vec<&str> = fields[7].split(',').collect();
    if items.is_empty() || items.len() > 128 {
        return Err("invalid_token_grants".to_owned());
    }
    let mut grants = Vec::with_capacity(items.len());
    for item in items {
        let parts: Vec<&str> = item.split('~').collect();
        if parts.len() != 4 || !valid_capability(parts[0]) || !valid_resource_prefix(parts[1]) {
            return Err("invalid_token_grant".to_owned());
        }
        let grant_expiry = if parts[2] == "-" {
            None
        } else {
            let expiry: i64 = parts[2].parse().map_err(|_| "invalid_token_grant_expiry")?;
            if expiry < 0 {
                return Err("invalid_token_grant_expiry".to_owned());
            }
            Some(expiry)
        };
        let delegation_depth: i64 = parts[3].parse().map_err(|_| "invalid_token_grant_depth")?;
        if delegation_depth < 0 {
            return Err("invalid_token_grant_depth".to_owned());
        }
        grants.push(Grant {
            capability: parts[0].to_owned(),
            resource_prefix: parts[1].to_owned(),
            expires_at: grant_expiry,
        });
    }
    Ok(Principal {
        principal_id: fields[5].to_owned(),
        tenant_id: fields[6].to_owned(),
        expires_at,
        grants,
    })
}

pub fn authorize(principal: &Principal, capability: &str, resource: &str) -> (bool, &'static str) {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs() as i64)
        .unwrap_or(i64::MAX);
    if now >= principal.expires_at { return (false, "TOKEN_EXPIRED"); }
    let matching: Vec<&Grant> = principal.grants.iter()
        .filter(|grant| grant.capability == capability)
        .collect();
    if matching.is_empty() {
        return (false, "MISSING_CAPABILITY");
    }
    let live: Vec<&Grant> = matching.iter().copied()
        .filter(|grant| grant.expires_at.map(|expiry| now < expiry).unwrap_or(true))
        .collect();
    if live.is_empty() {
        return (false, "EXPIRED_GRANT");
    }
    for grant in live {
        let prefix = grant.resource_prefix.trim_end_matches('/');
        let prefix = if prefix.is_empty() { "/" } else { prefix };
        if resource == prefix || resource.starts_with(&format!("{}/", prefix.trim_end_matches('/'))) {
            return (true, "ALLOW");
        }
    }
    (false, "RESOURCE_SCOPE")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn signed_bearer_verifies_capability_scope_and_rejects_tampering_and_expiry() {
        let key = b"0123456789abcdef0123456789abcdef";
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64;
        let payload = format!(
            "AN-CAP-V1|agent-native|agent-native-api|{}|{}|user-1|tenant-a|catalog.read~/v1/records/fixture-0001~-~0",
            now - 1, now + 60
        );
        let token = format!("{}.{}", payload, encode_hex(&hmac_sha256(key, payload.as_bytes()).unwrap()));
        let identity = verify_bearer(&format!("Bearer {token}"), key).expect("signed token should verify");
        assert_eq!(identity.principal_id, "user-1");
        assert_eq!(identity.tenant_id, "tenant-a");
        assert_eq!(authorize(&identity, "catalog.read", "/v1/records/fixture-0001").0, true);
        assert_eq!(authorize(&identity, "jobs.create", "/v1/jobs").1, "MISSING_CAPABILITY");
        assert_eq!(authorize(&identity, "catalog.read", "/v1/records/fixture-0002").1, "RESOURCE_SCOPE");

        let tampered = format!("{}0", token);
        assert!(verify_bearer(&format!("Bearer {tampered}"), key).is_err());

        let expired_payload = format!(
            "AN-CAP-V1|agent-native|agent-native-api|{}|{}|user-1|tenant-a|catalog.read~/v1/records/fixture-0001~-~0",
            now - 100, now - 1
        );
        let expired = format!("{}.{}", expired_payload, encode_hex(&hmac_sha256(key, expired_payload.as_bytes()).unwrap()));
        assert!(verify_bearer(&format!("Bearer {expired}"), key).is_err());
    }

    #[test]
    fn openssl_hmac_sha256_matches_rfc4231_test_vector() {
        let digest = hmac_sha256(
            b"key",
            b"The quick brown fox jumps over the lazy dog",
        ).expect("OpenSSL HMAC should succeed");
        assert_eq!(
            encode_hex(&digest),
            "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
        );
    }
}
