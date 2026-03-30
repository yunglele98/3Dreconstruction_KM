# Routing Rules

## Objective

Maximize throughput while minimizing merge conflicts.

## Assignment Strategy

1. Filter to `available` agents with free capacity.
2. Score by:
- skill overlap with task requirements
- remaining capacity
- missing required skills (penalty)
3. Assign highest score.

## Write-Scope Safety

1. Every routed task must include `write_scope`.
2. Router writes lock files in `coordination/locks`.
3. New task touching locked paths must wait or be split.

## Escalation Rules

1. No available capacity:
- keep task in backlog with `status=queued`.
2. Missing specialized skill:
- assign to `claude-1` for decomposition or route to best partial-fit plus review requirement.
3. High-risk tasks (`priority=high` + `estimate_points>=5`):
- force review by separate owner in `40_reviews`.
