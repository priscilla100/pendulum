//! `ToolRegistry` — the indexed set of tools the server exposes.
//!
//! Built once at startup from the `--tools` selector. Holds:
//!
//! * `name → Arc<dyn Tool>` map.
//! * An [`AnalysisCache`] keyed on `(tool_name, canonical_input)`.
//!   The same cache backs every registered tool; capacity from
//!   `MCP_CACHE_CAPACITY` per BUILD_PLAN §3.
//!
//! Dispatch path:
//! 1. Look up the tool by name. Missing → return a clean
//!    `ToolError::InvalidInput` (mapped to MCP `method_not_found`).
//! 2. Canonicalise the input JSON.
//! 3. Cache lookup. Hit → return cached body.
//! 4. Run `tool.call(input)`.
//! 5. Insert into cache *only if* `cache_policy` clears the
//!    deterministic-or-(temp=0, seed=set) gate.

use crate::tool::{Tool, ToolError};
use pltl_mcp_shared::cache::{should_cache, AnalysisCache};
use std::collections::BTreeMap;
use std::sync::Arc;

/// Indexed tool catalogue.
pub struct ToolRegistry {
    tools: BTreeMap<&'static str, Arc<dyn Tool>>,
    cache: Arc<AnalysisCache<String, String>>,
}

impl std::fmt::Debug for ToolRegistry {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ToolRegistry")
            .field("tools", &self.tools.keys().collect::<Vec<_>>())
            .finish()
    }
}

/// Outcome of one dispatch, including the cache classification so the
/// caller can log it.
#[derive(Debug, Clone)]
pub struct DispatchOutcome {
    /// JSON body to return to the MCP client.
    pub body: serde_json::Value,
    /// `true` if served from the registry cache.
    pub from_cache: bool,
}

impl ToolRegistry {
    /// Build a registry containing exactly the tools whose name is
    /// listed in `selected`. Returns an error listing the unknown or
    /// invalid names so the CLI can surface them.
    ///
    /// Edge cases (codex Phase B review #5):
    ///
    /// * `selected == ["all"]` (case-insensitive) registers
    ///   everything. Mixing `all` with named tools is rejected as
    ///   ambiguous.
    /// * Empty entries (`--tools ""` or `--tools foo,,bar`) are
    ///   rejected.
    /// * Duplicates are silently deduplicated.
    pub fn new(
        selected: &[String],
        available: Vec<Arc<dyn Tool>>,
    ) -> Result<Self, RegistryBuildError> {
        let mut by_name: BTreeMap<&'static str, Arc<dyn Tool>> = BTreeMap::new();
        for t in &available {
            by_name.insert(t.name(), t.clone());
        }

        // Trim + reject empty entries early.
        let mut cleaned: Vec<String> = Vec::with_capacity(selected.len());
        for raw in selected {
            let trimmed = raw.trim();
            if trimmed.is_empty() {
                return Err(RegistryBuildError::EmptySelector);
            }
            cleaned.push(trimmed.to_string());
        }
        if cleaned.is_empty() {
            return Err(RegistryBuildError::EmptySelector);
        }

        let has_all = cleaned.iter().any(|s| s.eq_ignore_ascii_case("all"));
        let registered = if has_all {
            // Ambiguous if `all` is mixed with named tools.
            if cleaned.iter().any(|s| !s.eq_ignore_ascii_case("all")) {
                return Err(RegistryBuildError::MixedAllAndNamed);
            }
            by_name
        } else {
            let mut chosen: BTreeMap<&'static str, Arc<dyn Tool>> = BTreeMap::new();
            let mut unknown: Vec<String> = Vec::new();
            for name in &cleaned {
                if let Some((k, v)) = by_name.iter().find(|(k, _)| **k == name.as_str()) {
                    chosen.insert(*k, v.clone());
                } else {
                    unknown.push(name.clone());
                }
            }
            if !unknown.is_empty() {
                return Err(RegistryBuildError::UnknownTools(unknown));
            }
            chosen
        };

        Ok(Self {
            tools: registered,
            cache: Arc::new(AnalysisCache::from_env()),
        })
    }

    /// Tool names in this registry, sorted.
    pub fn names(&self) -> Vec<&'static str> {
        self.tools.keys().copied().collect()
    }

    /// Look up a tool handle by name.
    pub fn get(&self, name: &str) -> Option<Arc<dyn Tool>> {
        self.tools.get(name).cloned()
    }

    /// Iterate over every registered tool. Used by the rmcp handler's
    /// `list_tools` implementation.
    pub fn iter(&self) -> impl Iterator<Item = (&&'static str, &Arc<dyn Tool>)> {
        self.tools.iter()
    }

    /// Dispatch a tool call through the registry cache.
    pub async fn dispatch(
        &self,
        name: &str,
        input: serde_json::Value,
    ) -> Result<DispatchOutcome, ToolError> {
        let tool = self
            .tools
            .get(name)
            .ok_or_else(|| ToolError::InvalidInput(format!("unknown tool: {name}")))?
            .clone();

        let key = cache_key(name, &input)?;

        if let Some(hit) = self.cache.get(&key) {
            // Cached values are stored as JSON strings (we serialise
            // before insertion). Deserialise on read; if it fails,
            // surface a clean internal error rather than panicking.
            return match serde_json::from_str(&hit) {
                Ok(body) => Ok(DispatchOutcome {
                    body,
                    from_cache: true,
                }),
                Err(e) => Err(ToolError::Internal(format!(
                    "cache deserialise: {e}"
                ))),
            };
        }

        let body = tool.call(input).await?;

        let policy = tool.cache_policy();
        if should_cache(policy.temperature, policy.seed) {
            match serde_json::to_string(&body) {
                Ok(s) => self.cache.put(key, s),
                Err(e) => tracing::warn!(error = %e, tool = name, "cache serialise failed"),
            }
        }

        Ok(DispatchOutcome {
            body,
            from_cache: false,
        })
    }

    /// Snapshot the registry's cache stats. Used by the binary's
    /// shutdown log per BUILD_PLAN §3.
    pub fn cache_stats(&self) -> pltl_mcp_shared::cache::CacheStats {
        self.cache.stats()
    }
}

/// Errors that can occur while constructing the registry.
#[derive(Debug, thiserror::Error)]
pub enum RegistryBuildError {
    /// One or more names in `--tools` weren't found in the catalogue.
    #[error("unknown tool(s): {0:?}")]
    UnknownTools(Vec<String>),
    /// `--tools` was given an empty entry (`""` or `,,`).
    #[error("--tools may not contain empty entries")]
    EmptySelector,
    /// `--tools` mixed `all` with one or more named tools — ambiguous.
    #[error("--tools `all` may not be combined with named tools")]
    MixedAllAndNamed,
}

/// Build a stable cache key from `(tool_name, input_json)`.
///
/// `serde_json::to_string` of a `serde_json::Value` is infallible in
/// practice (no IO, no custom Serialize that can fail), so a
/// failure here is a logic bug rather than something the cache
/// layer can swallow. Surface it as a `ToolError::Internal` rather
/// than silently using an empty key — codex Phase B review #6.
///
/// Object keys serialise in `BTreeMap` order (serde_json without
/// the `preserve_order` feature), so equivalent objects always
/// produce identical keys. If `preserve_order` is ever enabled
/// transitively, replace this with an explicit canonicaliser.
fn cache_key(tool_name: &str, input: &serde_json::Value) -> Result<String, ToolError> {
    let canonical = serde_json::to_string(input).map_err(|e| {
        ToolError::Internal(format!("cache_key serialise failed: {e}"))
    })?;
    Ok(format!("{tool_name}|{canonical}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;

    struct Echo;

    #[async_trait]
    impl Tool for Echo {
        fn name(&self) -> &'static str {
            "echo"
        }
        fn description(&self) -> &'static str {
            "echo input"
        }
        fn input_schema(&self) -> serde_json::Value {
            serde_json::json!({"type":"object"})
        }
        async fn call(&self, input: serde_json::Value) -> Result<serde_json::Value, ToolError> {
            Ok(input)
        }
    }

    #[test]
    fn unknown_tool_reported() {
        let err = ToolRegistry::new(
            &["echo".into(), "ghost".into()],
            vec![Arc::new(Echo) as Arc<dyn Tool>],
        )
        .unwrap_err();
        match err {
            RegistryBuildError::UnknownTools(names) => assert_eq!(names, vec!["ghost"]),
            other => panic!("unexpected error: {other:?}"),
        }
    }

    #[test]
    fn empty_selector_rejected() {
        let err =
            ToolRegistry::new(&["".into()], vec![Arc::new(Echo) as Arc<dyn Tool>])
                .unwrap_err();
        assert!(matches!(err, RegistryBuildError::EmptySelector));
    }

    #[test]
    fn all_with_named_rejected() {
        let err = ToolRegistry::new(
            &["all".into(), "echo".into()],
            vec![Arc::new(Echo) as Arc<dyn Tool>],
        )
        .unwrap_err();
        assert!(matches!(err, RegistryBuildError::MixedAllAndNamed));
    }

    #[test]
    fn whitespace_in_selector_trimmed() {
        let r =
            ToolRegistry::new(&[" echo ".into()], vec![Arc::new(Echo) as Arc<dyn Tool>])
                .expect("ok");
        assert_eq!(r.names(), vec!["echo"]);
    }

    #[test]
    fn all_registers_everything() {
        let r = ToolRegistry::new(
            &["all".into()],
            vec![Arc::new(Echo) as Arc<dyn Tool>],
        )
        .expect("ok");
        assert_eq!(r.names(), vec!["echo"]);
    }

    #[tokio::test]
    async fn cache_hits_on_repeat() {
        let r = ToolRegistry::new(
            &["all".into()],
            vec![Arc::new(Echo) as Arc<dyn Tool>],
        )
        .expect("ok");
        let payload = serde_json::json!({"x": 1});
        let first = r.dispatch("echo", payload.clone()).await.expect("dispatch");
        assert!(!first.from_cache);
        let second = r.dispatch("echo", payload).await.expect("dispatch");
        assert!(second.from_cache);
    }
}
