<!-- Supplemental context for LVM Operator dev environment. Repo's native CLAUDE.md (if any) takes priority. -->

# release — LVMS Context

**Category**: Testing

**Purpose**: OpenShift CI/CD configuration repository for Prow jobs and test workflows

**LVMS Relevance**: Contains all Prow CI job configurations for LVMS testing:
- Presubmit jobs (run on PRs)
- Periodic jobs (run on schedule)
- Postsubmit jobs (run after merge)

**How OpenShift CI works**:
- **Prow**: Kubernetes-based CI system that runs jobs
- **ci-operator**: OpenShift-specific test orchestrator
- **Step registry**: Reusable test steps, chains, and workflows
- Workflows compose steps for full test scenarios

**Key LVMS paths**:
- `ci-operator/config/openshift/lvm-operator/` — PR and periodic LVMS job definitions for building and testing the operator in Prow
- `ci-operator/config/openshift/topolvm/` — ci-operator configs for topolvm
- `ci-operator/jobs/openshift/lvm-operator/` — Generated Prow job definitions (presubmit, periodic, postsubmit)
- `ci-operator/jobs/openshift/topolvm/` — Prow job definitions for topolvm
- `ci-operator/step-registry/` — Reusable step definitions (shared across projects)

**Common tasks**:
```bash
# Find all LVMS-related CI configs
find ci-operator/config/openshift/lvm-operator/ -name "*.yaml"

# Find all LVMS Prow jobs
find ci-operator/jobs/openshift/lvm-operator/ -name "*.yaml"

# Check step registry for LVMS-specific steps
find ci-operator/step-registry/ -name "*lvm*"
```

**CI job naming convention**:
- `pull-ci-openshift-lvm-operator-<branch>-<test>` — Presubmit jobs
- `periodic-ci-openshift-lvm-operator-<branch>-<test>` — Periodic jobs
- `branch-ci-openshift-lvm-operator-<branch>-<target>` — Postsubmit jobs
