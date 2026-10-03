# Product

<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
Python worker and loopback dashboard; framework-free HTML/CSS/JavaScript. Implementation choice delegated by the user's instruction to implement fully.

## Users
Individual applicants who want to focus on their work rather than repeatedly completing applications. Each runs a private local instance; no shared hosted tenant service.

## Product Purpose
Automatically discover, rank and submit eligible internship/new-grad SWE, ML and research-engineering applications using confirmed personal facts.

## Operating Context
macOS/Linux computer or Pi 4 with 4 GB RAM, accessed locally through Raspberry Pi Connect. Explicit Claude/Codex subscription or paid API choice. Defaults run every six hours with configurable submission, attempt and model-request ceilings. Actual results depend on suitable jobs and access.

## Capabilities and Constraints
Routine applications require no individual approval. CAPTCHA/login/unknown facts and uncertain submissions go to a clickable daily queue. One-time confirmed onboarding and saved answers are reused. No invented facts, duplicate submissions, CAPTCHA bypass or automatic account creation. Remote ATS acceptance remains an external verification requirement.

## Product Principles
- Automation owns routine work; exceptions are specific and actionable.
- Unknown facts remain unknown until the user supplies them.
- Every submitted answer has provenance and a durable record.
- Throughput targets never override eligibility or application limits.
- The selected model recommends; deterministic code owns side effects.
