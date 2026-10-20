# Code Review Guidelines

## Approvals

Every pull request needs at least one approval from a teammate who is not the author. Changes to infrastructure, authentication or payment code need two approvals. Nobody may merge their own change into the main branch.

## Size and scope

Keep pull requests under 400 changed lines when possible. Split larger work into a stack of smaller pull requests so that reviewers can follow it.

## Response time

Reviewers respond to a review request within 1 business day. If you cannot review in time, tell the author and suggest another reviewer.

## Continuous integration

A pull request can only be merged when the CI pipeline is green. Do not disable or skip tests to get a change through.

## What to look for

Reviewers check correctness first, then tests, then readability. Style issues that a linter can catch should not be raised by hand.

## Giving feedback

Comments should be specific and kind. Mark optional suggestions with the prefix "nit:" so that the author knows they are not blocking.
