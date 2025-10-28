# Part 3 - Phase 3 Issue List (22 items)

This list translates Part-3 (production-grade DevOps, observability, security, HA/DR, cost) into actionable issues. Each item includes acceptance criteria and tests/checks suitable for CI.

## Global Definition of Done (applies to all issues)
- CI runs on PRs and default branch; all checks pass.
- Manifests/Charts/Rules linted (helm lint/kubeval/promtool) and policy-checked (conftest/OPA) when applicable.
- Logs remain structured JSON; no secrets/PII; configs contain no hardcoded secrets.

## 1) Hardened Multi-stage Dockerfile
- Description: Create a small, secure image with a multi-stage build and least privilege.
- Acceptance Criteria:
  - Non-root user, `readOnlyRootFilesystem: true`; minimal base image; pinned digests.
  - Final image size baseline recorded in README.
  - `.dockerignore` present; no dev artifacts in image.
- Tests:
  - CI builds image; hadolint (if available) passes.
  - Note: Security scans are covered in Issue #11 (Pipeline Security and Secret Scanning).

## 2) Helm Chart: App Skeleton
- Description: Scaffold a Helm chart for the app.
- Acceptance Criteria:
  - `Chart.yaml`, `values.yaml`, templates for Deployment, Service, Ingress, ConfigMap, Secret, HPA.
  - Resource requests/limits and env var injection are configurable via values.
  - Ingress TLS configured via cert-manager annotations; configurable issuer (e.g., Let's Encrypt) in `values.yaml`.
- Tests:
  - `helm lint` passes; `helm template` outputs expected K8s objects.

## 3) Kubernetes Deployment Hardening
- Description: Add probes, disruption and placement guardrails, and network security.
- Acceptance Criteria (Mandatory):
  - Liveness/Readiness/Startup probes defined; PodDisruptionBudget present.
  - SecurityContext runs as non-root, drops capabilities; resource requests/limits set.
  - NetworkPolicy default-deny; explicit egress only to Slack API and DB.
- Acceptance Criteria (Optional, portfolio-friendly):
  - TopologySpreadConstraints or simple anti-affinity (if multiple nodes available).
  - Admission policies via conftest (advisory) or Gatekeeper (enforcing) for non-root/limits/probes.
  - WAF/DDoS notes: document integration at ingress or upstream platform; no hard requirement in manifests.
- Tests:
  - Mandatory: `kubeval` (or kubeconform) passes; conftest checks verify non-root, probes, and limits.
  - Optional: conftest advisory suite includes policies for spread/affinity and ingress hardening (does not fail CI by default).

## 4) External Secrets + Workload Identity
- Description: Use External Secrets Operator and cloud workload identity (e.g., IRSA) for secret delivery.
- Acceptance Criteria:
  - ServiceAccount annotated/bound; SecretStore/ExternalSecret resources defined.
  - No static Kubernetes Secret with plaintext credentials in repo.
- Tests:
  - conftest verifies SA annotations and absence of hardcoded secrets; manifests validate.

## 5) Database Migration Job (Zero-downtime Friendly)
- Description: Run Alembic migrations as a K8s Job with safe patterns.
- Acceptance Criteria:
  - Job manifest defined; pre/post hooks in deployment reference it.
  - Migration guidance documented (expand -> backfill -> enforce).
- Tests:
  - Alembic test applies up/down locally; Job manifest included and linted.

## 6) Supply Chain: SBOM and Image Signing
- Description: Produce SBOM and sign images; verify in CI.
- Acceptance Criteria:
  - SBOM (CycloneDX or SPDX) generated and stored as artifact.
  - Image signed with Cosign; verification step in CI.
  - Admission/policy enforcement verifies signatures before deploy (e.g., cosign-policy-controller or Gatekeeper policy).
- Tests:
  - CI job runs syft/cosign; verification succeeds for built image tag.

## 7) CI Pipeline Stages and Caching
- Description: Add jobs for lint/test/build/scan/push with sensible caching.
- Acceptance Criteria:
  - Separate steps for tests and image build; pip cache enabled.
  - Artifacts archived; security scans integrated via Issue #11.
- Tests:
  - CI pipeline run evidence; all stages green on PR.

## 8) GitOps Bootstrap (Argo CD or Flux)
- Description: Define GitOps app(s) and environment overlays.
- Acceptance Criteria:
  - Argo Application(s) (or Flux Kustomizations) for dev/stage/prod.
  - Sync policy and health checks configured; app-of-apps pattern documented.
- Tests:
  - Manifests linted; conftest ensures sync options/policies present.

## 9) Promotion + Progressive Delivery
- Description: Define dev→staging→prod promotion with canary/blue-green and rollback gates.
- Acceptance Criteria:
  - Canary/blue-green strategy via Istio/Argo Rollouts; rollback on SLO breach documented.
  - Manual approval gates between environments.
- Tests:
  - Rollout/VirtualService manifests linted; policy tests ensure rollout strategy fields exist.

## 10) Terraform Baseline (Infra as Code)
- Description: Add Terraform modules for core infra (e.g., registry, cluster, DB) with remote state.
- Acceptance Criteria:
  - Modules structured; remote state backend configured with locking.
  - `terraform fmt`/`validate` clean; example `plan` job in CI.
- Tests:
  - CI validates Terraform; conftest checks tags and required settings.

## 11) Pipeline Security and Secret Scanning
- Description: Add SAST/dependency/container scans and secret scanning to CI.
- Acceptance Criteria:
  - Semgrep/Bandit run; trivy fs and image scans; secret scanning enabled.
  - Fail thresholds documented; false positives triaged.
  - DAST baseline (e.g., OWASP ZAP) runs against a test deployment or mocked endpoint.
- Tests:
  - CI shows scans executed; baseline rules committed.

## 12) Prometheus Operator + ServiceMonitor
- Description: Deploy Prometheus Operator (or wire existing) and scrape app metrics.
- Acceptance Criteria:
  - ServiceMonitor selects app Service; scrape interval configurable.
  - Recording rules added for key rates/latencies.
  - Optional long-term storage via Thanos sidecar or remote write is configurable and documented.
- Tests:
  - `promtool check` on rules; ServiceMonitor manifest present and valid.

## 13) SLOs and Burn-rate Alerts
- Description: Define SLOs and alerting for errors/latency with multi-window burn rates.
- Acceptance Criteria:
  - SLO objectives documented; Alertmanager routes wired.
  - Alerts include links to dashboards/runbooks and integrate with PagerDuty/OpsGenie for on-call.
- Tests:
  - `promtool test rules` passes for sample series; alert labels validated.

## 14) OpenTelemetry Tracing
- Description: Instrument app with OTel; export to Jaeger/Tempo.
- Acceptance Criteria:
  - Tracer configured; spans created on request/handler boundaries; sampling rate configurable.
  - Trace-id correlation with logs preserved.
  - OpenTelemetry Collector (or equivalent) configured (in-cluster or remote) as the export target.
- Tests:
  - Unit test asserts tracer init and span creation; integration test fakes OTLP exporter.

## 15) Log Aggregation Refinement
- Description: Improve log context, redaction, sampling, and retention.
- Acceptance Criteria:
  - Redaction filter for secrets/PII; sampling policy documented; retention policy noted.
  - Logs include request/team/workspace IDs for correlation.
- Tests:
  - Redaction unit tests; structure/correlation fields asserted.

## 16) Service Mesh Baseline with mTLS
- Description: Install and configure Istio/Linkerd with strict mTLS.
- Acceptance Criteria:
  - Mesh installed; PeerAuthentication mTLS STRICT; DestinationRules present.
  - Sidecar auto-injection enabled for app namespace.
- Tests:
  - conftest ensures mTLS strict; manifests linted.

## 17) Advanced Traffic Management
- Description: Add retries/timeouts, circuit breakers, rate limiting, and canary routes.
- Acceptance Criteria:
  - VirtualService/Gateway define timeouts/retries; DestinationRule defines connection/breaker settings.
  - Rate limiting policy configured.
- Tests:
  - Manifests validated; policy tests check specific fields (timeouts, retries, limits).

## 18) Backup and Restore (HA/DR)
- Description: Configure Velero (or cloud-native) backups and database backup/PITR.
- Acceptance Criteria:
  - Backup schedules defined; restore procedure documented and tested in staging.
  - Critical namespaces and PVCs included.
  - Periodic restore drills (at least quarterly) and chaos tests (e.g., pod/node failure) validate recovery steps.
- Tests:
  - Manifests present and linted; scripted dry-run of restore plan included.
  - Chaos test script (or plan) demonstrates recovery success criteria.

## 19) Multi-Region and DNS Failover Plan
- Description: Document and partially automate multi-region deployment and failover.
- Acceptance Criteria:
  - Health checks and DNS failover policy defined; region-specific configs identified.
  - Runbook for failover/failback procedures.
- Tests:
  - Policy manifests (where applicable) linted; runbook passes review checklist.

## 20) Secrets Management and Rotation
- Description: Centralize secrets in Vault/KMS and automate rotation for tokens/keys/certs.
- Acceptance Criteria:
  - Rotation cadence documented; job/workflow automates rotation where possible.
  - mTLS certificate rotation process automated.
- Tests:
  - Rotation script/unit tests; conftest ensures no static long-lived secrets in manifests.

## 21) Access Governance and Auditing
- Description: Implement JIT privileged access, break-glass accounts, periodic access reviews, and audit trails.
- Acceptance Criteria:
  - Policies documented and enforced; break-glass process tested; audit log coverage improved.
  - Compliance checklist mapping to SOC2/ISO controls created; periodic audit trail export procedure documented.
- Tests:
  - Policy-as-code tests (conftest) and a checklist-based test case for break-glass workflow.

## 22) FinOps Guardrails and Autoscaling Optimization
- Description: Apply ResourceQuota/LimitRange, set HPA/VPA targets, and tune autoscaling/capacity.
- Acceptance Criteria:
  - Namespace quotas and limits defined; HPA tuned to metrics; (optional) Karpenter config for spot.
  - Budget/alerts documented; cost tags applied in Terraform.
  - Load testing baseline (k6/JMeter) informs capacity plan; results recorded and reviewed.
- Tests:
  - Manifests linted; conftest checks quotas/limits present; CI includes a cost-policy check (if available).
