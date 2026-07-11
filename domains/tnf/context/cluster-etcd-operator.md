<!-- TNF context: repo's role in the TNF ecosystem. Always distributed as DOMAIN-CONTEXT.md. -->

# cluster-etcd-operator — TNF Context

**Category**: Development

**Purpose**: Manages etcd scaling during cluster bootstrap and operation, provisions TLS certificates

**TNF Relevance**: **This is the heart of TNF**. Contains the TNF controller code that runs on the cluster after installation and orchestrates the transition to Pacemaker-managed etcd:
- Initializes the Pacemaker cluster configuration
- Transitions etcd management from CEO to RHEL-HA
- Configures fencing using BMC credentials
- Handles the handover of etcd to the podman-etcd OCF agent

**Key paths**:
- `pkg/tnf/` - TNF-specific controllers and utilities
  - `pkg/tnf/operator/starter.go` - TNF operator entry point
  - `pkg/tnf/auth/runner.go` - Authentication phase
  - `pkg/tnf/setup/runner.go` - Setup phase
  - `pkg/tnf/fencing/runner.go` - Fencing configuration phase
  - `pkg/tnf/after-setup/runner.go` - Post-setup phase
  - `pkg/tnf/pkg/pcs/` - Pacemaker integration
    - `cluster.go` - Cluster initialization
    - `etcd.go` - etcd resource configuration
    - `fencing.go` - STONITH/fencing setup
    - `types.go` - Type definitions
  - `pkg/tnf/pkg/config/` - Cluster configuration
  - `pkg/tnf/pkg/etcd/` - etcd management
  - `pkg/tnf/pkg/jobs/` - Job controller
  - `pkg/tnf/pkg/tools/` - Utilities (conditions, secrets, redact, etc.)
- `docs/HACKING.md` - Development guide

**TNF controller phases** (executed in order):
1. **auth** - Handles Pacemaker authentication between nodes (pcsd tokens)
2. **setup** - Initializes Pacemaker cluster, configures resources
3. **fencing** - Configures STONITH with BMC credentials
4. **after-setup** - Post-setup tasks, hands etcd management to Pacemaker

**TNF-related test files**:
- `pkg/tnf/operator/starter_test.go`
- `pkg/tnf/pkg/pcs/fencing_test.go`
- `pkg/tnf/pkg/pcs/types_test.go`
- `pkg/tnf/pkg/config/cluster_test.go`
- `pkg/tnf/pkg/etcd/etcd_test.go`
- `pkg/tnf/pkg/jobs/jobcontroller_test.go`
- `pkg/tnf/pkg/tools/redact_test.go`

## etcd TLS Certificate Handling

etcd 3.6+ reloads TLS certificates from disk on every new TLS handshake via Go's `GetCertificate` / `GetClientCertificate` callbacks ([PR #7829](https://github.com/etcd-io/etcd/pull/7829)). No `--tls-reload-interval` flag exists — it's automatic.

**Known issue**: [etcd #9541](https://github.com/etcd-io/etcd/issues/9541) — certs with IP-only SANs (no DNS names) may not trigger reload. OCP 4.22+ certs include DNS names (`etcd.kube-system.svc`, `localhost`, etc.) alongside IPs, so this does not apply.

**Implication for TNF**: The podman-etcd monitor does not need to trigger a restart on cert file changes. Updating the stored hash and returning SUCCESS is sufficient. Real TLS failures are caught by `monitor_cmd_exec`. Certs are bind-mounted from host `/etc/kubernetes/static-pod-resources/etcd-certs/` into the podman container at `/etc/kubernetes/static-pod-certs/`.

**Commands**:
```bash
make build                    # Build binaries
hack/generate.sh              # Regenerate alerts from jsonnet
make test                     # Run tests

# OTE (OpenShift Tests Extension) framework
./cluster-etcd-operator-tests-ext run-suite openshift/cluster-etcd-operator/all
./cluster-etcd-operator-tests-ext run-test "test-name"
./cluster-etcd-operator-tests-ext list suites
```
