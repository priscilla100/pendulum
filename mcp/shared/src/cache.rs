//! Generic in-process LRU cache for analysis results.
//!
//! Every MCP server gets one of these. Keys are typically the canonical
//! pretty-printed form of the input formula (`format!("{formula}")`),
//! or — for tools that take traces or multi-formula input — a stable
//! hash of the request JSON. Choosing the key is each tool's job; this
//! module just wraps the [`lru`] crate behind an async-safe surface.
//!
//! ## Capacity
//!
//! Default is **1024 entries**, overridable via the `MCP_CACHE_CAPACITY`
//! env var (read once at construction). The value must parse to a
//! positive `usize`; invalid values fall back to the default and emit a
//! `tracing::warn`.
//!
//! ## When to bypass the cache
//!
//! For LLM-backed tools (`extract_ap_mapping`, `ltl_to_nl`,
//! `nl_to_ltl_via_python`), only cache when the call is deterministic
//! (`temperature == 0` AND `seed` is set).
//! Otherwise insertion would pollute the cache with non-reproducible
//! answers. Call [`AnalysisCache::should_cache`] to apply this policy
//! consistently.

use lru::LruCache;
use std::num::NonZeroUsize;
use std::sync::Mutex;

/// Default cache capacity if `MCP_CACHE_CAPACITY` is unset or invalid.
pub const DEFAULT_CAPACITY: usize = 1024;

/// Read [`DEFAULT_CAPACITY`] from the environment, with logging on
/// invalid input.
pub fn capacity_from_env() -> NonZeroUsize {
    let raw = std::env::var("MCP_CACHE_CAPACITY").ok();
    let parsed = raw
        .as_deref()
        .and_then(|s| s.parse::<usize>().ok())
        .and_then(NonZeroUsize::new);

    match parsed {
        Some(n) => n,
        None => {
            if let Some(bad) = raw {
                tracing::warn!(
                    invalid_value = bad.as_str(),
                    default = DEFAULT_CAPACITY,
                    "MCP_CACHE_CAPACITY ignored; using default",
                );
            }
            NonZeroUsize::new(DEFAULT_CAPACITY).unwrap_or(NonZeroUsize::MIN)
        }
    }
}

/// Decision policy: should an analysis result be cached at all?
///
/// Returns `true` for deterministic analyses and for LLM-backed tools
/// only when called with `temperature == 0.0` and a fixed `seed`.
pub fn should_cache(temperature: Option<f32>, seed: Option<u64>) -> bool {
    match (temperature, seed) {
        (None, _) => true, // deterministic analysis
        (Some(t), Some(_)) if t.abs() < f32::EPSILON => true,
        _ => false,
    }
}

/// Cache hit/miss statistics. Mutated atomically under the same mutex
/// that protects the underlying LRU.
#[derive(Debug, Default, Clone, Copy)]
pub struct CacheStats {
    /// Number of `get` calls that returned a value.
    pub hits: u64,
    /// Number of `get` calls that returned `None`.
    pub misses: u64,
    /// Current number of entries in the cache.
    pub size: usize,
}

/// Thread-safe LRU cache for analysis results.
///
/// `K` is the cache key (typically a `String` of the canonical pretty-
/// printed formula). `V` is the result type — kept generic so the same
/// cache impl serves boolean, integer, string-formula, and JSON-blob
/// results.
pub struct AnalysisCache<K, V>
where
    K: std::hash::Hash + Eq,
{
    inner: Mutex<LruInner<K, V>>,
}

struct LruInner<K, V>
where
    K: std::hash::Hash + Eq,
{
    cache: LruCache<K, V>,
    hits: u64,
    misses: u64,
}

impl<K, V> AnalysisCache<K, V>
where
    K: std::hash::Hash + Eq,
    V: Clone,
{
    /// Construct an empty cache with the given capacity.
    pub fn new(capacity: NonZeroUsize) -> Self {
        Self {
            inner: Mutex::new(LruInner {
                cache: LruCache::new(capacity),
                hits: 0,
                misses: 0,
            }),
        }
    }

    /// Construct an empty cache using [`capacity_from_env`].
    pub fn from_env() -> Self {
        Self::new(capacity_from_env())
    }

    /// Look up a key. Returns `Some(value.clone())` on hit, `None`
    /// on miss; updates hit/miss counters.
    ///
    /// Lock is held only for the duration of the `get`. A poisoned
    /// lock is treated as a miss (the cache is best-effort).
    pub fn get(&self, key: &K) -> Option<V> {
        let mut g = match self.inner.lock() {
            Ok(g) => g,
            Err(_) => return None,
        };
        if let Some(v) = g.cache.get(key) {
            let v = v.clone();
            g.hits += 1;
            Some(v)
        } else {
            g.misses += 1;
            None
        }
    }

    /// Insert a value. A poisoned lock silently drops the insert —
    /// the cache is advisory; correctness must not depend on it.
    pub fn put(&self, key: K, value: V) {
        if let Ok(mut g) = self.inner.lock() {
            g.cache.put(key, value);
        }
    }

    /// Snapshot the current statistics.
    pub fn stats(&self) -> CacheStats {
        self.inner
            .lock()
            .map(|g| CacheStats {
                hits: g.hits,
                misses: g.misses,
                size: g.cache.len(),
            })
            .unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn put_then_get_hits() {
        let cache: AnalysisCache<String, u32> =
            AnalysisCache::new(NonZeroUsize::new(4).unwrap());
        cache.put("p U q".into(), 42);
        assert_eq!(cache.get(&"p U q".to_string()), Some(42));
        assert_eq!(cache.stats().hits, 1);
        assert_eq!(cache.stats().misses, 0);
    }

    #[test]
    fn miss_increments_counter() {
        let cache: AnalysisCache<String, u32> =
            AnalysisCache::new(NonZeroUsize::new(4).unwrap());
        assert_eq!(cache.get(&"absent".to_string()), None);
        assert_eq!(cache.stats().misses, 1);
    }

    #[test]
    fn should_cache_policy() {
        assert!(should_cache(None, None));
        assert!(should_cache(Some(0.0), Some(7)));
        assert!(!should_cache(Some(0.0), None));
        assert!(!should_cache(Some(0.5), Some(7)));
    }
}
