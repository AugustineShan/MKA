# ADR-0001: Use Business Fact Matrix for YAML1 Display

## Status
Accepted

## Context
MKA supports non-standard business splits across companies: business lines, products, regions, channels, customers, unit economics, and industry-specific KPIs. Historically, `yaml1` facts were projected into hand-written workbench fields and then partly re-derived in the frontend. This created two failure modes:

- New `history.series.*` keys could die at the yaml1 -> workbench -> frontend boundary.
- The same business fact could have multiple representations, such as direct margin versus margin derived from revenue and cost.

The platform needs to list many companies without making each new split shape a frontend branch or a new manually synchronized field.

## Decision
Introduce a canonical `yaml1_business_facts_view` built by `src.yaml1_business_facts`.

`yaml1` remains flexible and source-shaped, but workbench normalizes displayable facts into typed `BusinessFactBlock` and `BusinessFactRow` objects. `display` decides placement and role only. Metric aliases, labels, formats, and fallback policy live in `src/business_metric_registry.yaml`.

The frontend renders `yaml1_business_facts_view` first and uses legacy `yaml1_revenue_view` only as a compatibility fallback.

## Consequences

### Positive
- New business split metrics are preserved as rows or explicit warnings instead of disappearing silently.
- Metric semantics become centralized and testable.
- Frontend rendering becomes table-driven rather than business-shape-driven.
- Existing yaml1 files remain valid; no migration is required.

### Negative
- Workbench now has an additional canonical view alongside legacy views during the transition.
- Registry maintenance becomes part of adding new common metrics.

### Neutral
- Some unknown metrics will appear as `custom:*` until promoted into the registry.

## Alternatives Considered

**Keep adding explicit fields to `yaml1_revenue_view`**
- Rejected: repeats the original failure pattern and relies on humans remembering to update backend, TypeScript, and frontend rendering in lockstep.

**Force `/comp` to emit a rigid display schema**
- Rejected for now: it would reduce yaml1 flexibility and require historical yaml1 migration. Workbench can canonicalize old and new yaml1 shapes without changing source files.

**Rewrite the whole core assumptions frontend at once**
- Rejected: too much risk. The chosen approach uses a strangler migration with legacy fallback.

## References
- `src/yaml1_business_facts.py`
- `src/business_metric_registry.yaml`
- `tests/test_yaml1_business_facts.py`
- `docs/yaml1前端展示契约.md`
