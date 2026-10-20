# Engineering Practices

## Deployments

We deploy to production at any time on Monday to Thursday. There is a deploy freeze on Fridays after 14:00 and on days before a company holiday. Emergency fixes during a freeze need approval from the on-call engineering manager.

## Testing

New code should have automated tests. The target for unit test coverage is 80 percent for backend services. Flaky tests must be fixed or quarantined within one week.

## Feature flags

Risky changes ship behind a feature flag and are enabled for 5 percent of customers first. Flags that have been fully enabled for 30 days must be removed.

## Architecture decisions

Significant design choices are recorded as short architecture decision records (ADRs) in the repository. An ADR states the context, the decision and the consequences.

## Languages

New backend services are written in Python 3.12. Frontend code uses TypeScript in strict mode. Exceptions need approval from the architecture group.
