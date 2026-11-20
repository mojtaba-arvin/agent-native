# Agent Native Service IR v1

**Status:** normative and frozen for v1.  
**Schema:** [\`schemas/service-ir-v1.schema.json\`](../schemas/service-ir-v1.schema.json)  
**Validator:** \`agent_native.validate_ir\` (implemented in \`src/agent_native/ir.py\`).

This document freezes the structured service intermediate representation used by the parser, runtime, and Agent Gateway. It does not select the surface language, implementation language, compiler, or runtime.

## 1. Version identifiers are distinct

There are three separate version concepts; they must not be conflated:

| Field | Meaning |
|---|---|
| \`ir_version\` | Integer protocol version of the service IR. v1 requires exactly integer \`1\`. |
| \`service.version\` | Non-empty application/service release string. It is not the IR protocol version. |
| Manifest \`schema_version\` | Version of the service-manifest envelope. The existing service-manifest v1 and v2 schemas describe this envelope, not the service IR. |

The Gateway proposal, plan, and validation schemas likewise describe tool envelopes. They do not replace or redefine the canonical service IR document.

## 2. Canonical v1 document

A v1 IR is a **complete snapshot**, not a patch, partial operation list, merge instruction, or request to fill omitted fields from previously inspected state.

The root object contains exactly these fields:

| Field | Required shape |
|---|---|
| \`ir_version\` | Integer \`1\` |
| \`service\` | Object containing exactly \`name\` and \`version\` |
| \`types\` | Array of complete record type declarations; may be empty |
| \`operations\` | Non-empty array of complete operation declarations |

### Service identity

- \`service.name\` is an identifier matching \`[A-Za-z_][A-Za-z0-9_]*\`.
- \`service.version\` is a non-empty string.
- No other service identity properties are permitted in v1.

### Record types

Each type contains exactly \`name\` and \`fields\`. The type name is a non-empty identifier and cannot reuse a built-in type name. A type has at least one field. Each field contains exactly \`name\` and \`type\`; field names are unique identifiers.

The built-in type names are \`String\`, \`UUID\`, \`Integer\`, \`Boolean\`, \`Bytes\`, and \`Float\`. A field type must resolve to one of those built-ins or a declared record type. Forward references between declared record types are allowed because validation resolves the complete type-name set before checking references.

### Operations

Each operation contains exactly:

- \`name\`: unique identifier.
- \`method\`: one of \`GET\`, \`POST\`, \`PUT\`, \`PATCH\`, or \`DELETE\`.
- \`path\`: an absolute route path.
- \`input\`: an array of input declarations.
- \`output\`: a known type reference, or \`List<TypeName>\` where \`TypeName\` resolves.
- \`errors\`: unique, non-empty declared error names.
- \`validation\`: unique validation rule names.
- \`effects\`: unique effect names; an empty array is allowed.
- \`capability\`: a non-empty capability name.

Each input contains exactly \`name\`, \`type\`, and \`source\`. Its source is one of \`path\`, \`query\`, \`body\`, or \`header\`; its type must resolve to a built-in or declared record type. Input names are unique within an operation.

Every operation must declare the \`Unauthorized\` error. An operation with one or more inputs must also declare \`InvalidInput\`. A \`GET\` operation cannot declare body inputs.

The v1 validation vocabulary currently supports only \`<StringInput>.non_empty\`, bound to an input whose type is \`String\`. Unknown, unsupported, or unbound validation rules are rejected; they are not treated as advisory strings.

### Route and cross-field constraints

The JSON Schema describes the structural form. The executable semantic validator additionally enforces constraints that depend on multiple declarations or on canonical path interpretation:

- Paths begin with \`/\`; query strings, fragments, percent-encoded paths, backslashes, repeated slashes, control characters, DEL, non-NFC Unicode, and dot or dot-dot segments are rejected.
- Path placeholders are well-formed, unique, and exactly match the set of inputs whose source is \`path\`.
- The pair \`(method, path)\` is unique across the service.
- Type, field, operation, and input names are valid and unique in their respective scopes.
- Record fields and operation inputs resolve their types; operation outputs resolve either a named type or a supported \`List<T>\` reference.
- Required authorization/input errors and validation-rule bindings are enforced.

These are acceptance constraints, not parser suggestions. Consumers must call the semantic validator even after structural JSON Schema validation.

## 3. Structural and semantic validation

Two complementary checks define v1 acceptance:

1. **Structural validation:** validate the JSON document against Draft 2020-12 and the frozen \`service-ir-v1.schema.json\`. Object shapes are closed with \`additionalProperties: false\`; unknown fields are rejected.
2. **Semantic validation:** call \`agent_native.validate_ir(ir)\`. It raises the stable \`Diagnostic\` type with a diagnostic code when the version, references, routes, capabilities, declared errors, or cross-field constraints are invalid.

\`Parser.parse()\` emits an IR v1 object and passes it through \`validate_ir()\` before returning it. The public \`agent_native.validate_ir\` function is also required for untrusted structured IR supplied directly by a caller; validating only source text is insufficient.

JSON Schema alone cannot express all v1 cross-field constraints, such as resolving a type name against the complete declarations, requiring path inputs to match placeholders, rejecting duplicate route pairs, or binding a validation rule to a String input. Those checks are part of \`validate_ir()\` and are covered by executable positive and negative tests.

Consumers must reject unknown or unsupported versions and unknown properties; both **fail closed**. A caller must not ignore a validation error, guess a default, or continue to runtime/plan execution after validation has failed.

## 4. Complete-snapshot and deterministic representation rules

The \`ir\` supplied to a proposal is the complete snapshot for that proposal revision. Omitted types or operations are not inherited from a prior inspection. A client that wants to preserve an existing service must include the exact existing declarations and make only its requested edit.

The parser emits deterministic arrays sorted by their declaration key or string value: types, record fields, operations, operation inputs, errors, validation rules, and effects. The order of declarations does not establish route priority or authorization precedence; duplicate routes are rejected. A snapshot transport, proposal store, or hash-bound round trip must preserve the submitted declaration order rather than silently reorder or repair an already-submitted document.

A partial-update or patch protocol, if introduced later, requires a separate explicit type, schema, endpoint, base-revision binding, conflict rules, and validation semantics. It must never be inferred from an incomplete v1 \`ir\` object.

## 5. Compatibility and evolution policy

v1 is immutable. In particular:

- Do not add optional or required properties to a v1 object. Closed objects make even an additive property incompatible.
- Do not change a field's type, requiredness, allowed values, interpretation, default, validation rule, or security meaning in place.
- Do not silently loosen or tighten route, type-resolution, error, capability, or effect semantics under the same \`ir_version\`.
- Documentation clarifications that do not change the accepted data or its meaning do not create a new IR version.
- Any incompatible structural **or semantic** change requires a new integer IR version and a new versioned schema file (for example, \`service-ir-v2.schema.json\`). Keep the v1 schema and v1 validator behavior available for v1 documents.
- Consumers dispatch by the integer \`ir_version\`. Unknown or unsupported versions fail closed; a consumer must not reinterpret v2 as v1 or select a schema by guesswork.

A future v1-to-v2 change requires an explicit migration function named for its source and target versions; this is an explicit migration, not an automatic reinterpretation. It must declare its source and target versions, be deterministic, preserve the meaning of every source declaration, and reject source values it cannot represent. It must not silently discard unknown fields, synthesize authority/capabilities, or invent defaults. The existence of a v2 schema does not imply an automatic migration or an automatic downgrade path.

These rules apply to the IR protocol version only. A service release string or a manifest envelope \`schema_version\` may evolve independently without changing \`ir_version\`, provided the embedded IR remains valid v1.

## 6. Compatibility fixtures and acceptance

The package tests use real Catalog and Inventory service declarations plus constructed positive and negative structured IR cases. They exercise both the public parser output and direct untrusted-IR validation. The frozen schema metadata and closed object shapes are tested alongside the semantic validator.

Run the focused contract suite with:

\`\`\`sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_ir_v1_contract.py' -v
\`\`\`

The v1 acceptance script runs that suite and checks the schema identifier, Draft version, root fields, version constant, and compatibility requirements.
