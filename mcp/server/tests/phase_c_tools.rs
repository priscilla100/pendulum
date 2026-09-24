//! Phase C §5.C tool-suite tests.
//!
//! Each test runs against the in-process catalogue (no spawned
//! binary, no OCaml dependency) to keep the workspace test suite
//! hermetic. The smoke tests in `smoke.rs` cover the end-to-end
//! wire path.

use pltl_mcp_server::tools::{all, known_names};

#[test]
fn full_catalogue_has_expected_tool_count() {
    // Catalogue has 14 tools after removing detect_ambiguity and
    // synthesize_from_traces. Update this count when genuinely-new
    // tools land.
    let names = known_names();
    assert_eq!(
        names.len(),
        14,
        "tool catalogue size changed unexpectedly; got {names:?}"
    );
    for required in [
        "ltl_to_nl",
        "nl_to_ltl_via_salt",
        "nl_to_ltl_via_python",
        "extract_ap_mapping",
        "salt_help",
        "parse_and_canonicalize",
    ] {
        assert!(
            names.contains(&required),
            "expected `{required}` in catalogue; got {names:?}"
        );
    }
}

#[test]
fn every_tool_advertises_a_json_object_schema() {
    for tool in all() {
        let schema = tool.input_schema();
        let obj = schema
            .as_object()
            .expect("input_schema must be an Object");
        assert!(
            !obj.is_empty(),
            "tool `{}` produced an empty schema",
            tool.name()
        );
    }
}

#[test]
fn tools_surface_clean_result_or_clean_error() {
    // No tool in the catalogue should ever panic — every call must
    // return either a clean Ok result or a clean ToolError variant.
    // Sat-dependent tools surface Analysis("unsupported: BLACK
    // solver not found…") when BLACK is missing; an installed BLACK
    // returns Ok. Either is fine here.
    let pairs: &[(&str, serde_json::Value)] = &[
        ("check_entailment", serde_json::json!({"f1": "p", "f2": "q"})),
        ("gen_satisfying_trace", serde_json::json!({"formula": "F p"})),
    ];
    for (name, input) in pairs {
        let tool = all()
            .into_iter()
            .find(|t| t.name() == *name)
            .unwrap_or_else(|| panic!("missing tool {name}"));
        let result = futures::executor::block_on(
            pltl_mcp_server::tool::Tool::call(&*tool, input.clone()),
        );
        match result {
            Ok(_) => {}
            Err(pltl_mcp_server::tool::ToolError::NotImplemented(_)) => {}
            Err(pltl_mcp_server::tool::ToolError::Analysis(_)) => {}
            Err(other) => panic!("unexpected error variant for {name}: {other:?}"),
        }
    }
}
