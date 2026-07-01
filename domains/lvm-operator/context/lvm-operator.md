<!-- Supplemental context for LVM Operator dev environment. Repo's native CLAUDE.md (if any) takes priority. -->

# lvm-operator — LVMS Context

**Category**: Development

**Purpose**: Core LVM Operator (LVMS) — manages local storage volumes on OpenShift using LVM thin provisioning, exposed via the TopoLVM CSI driver.

**What LVMS does**:
- Provides `LVMCluster` CRD for declaring storage configurations
- Manages LVM Volume Groups and thin pools on cluster nodes
- Integrates TopoLVM as the CSI driver for dynamic PV provisioning
- Provides `StorageClass` and `VolumeSnapshotClass` resources automatically
- Supports single-node (SNO), compact, and standard OpenShift topologies

**Key paths**:
- `.tekton/` — Konflux pipeline definitions for building and testing operator components
- `api/` — LVM operator API definitions (`LVMCluster`, `LVMVolumeGroup`, `LVMVolumeGroupNodeStatus`)
- `bundle/` — Auto-generated OLM bundle manifests (CSV, CRDs, RBAC)
- `catalog/` — Catalog definitions for testing in Prow
- `cmd/` — Primary entrypoints for the operator binaries
- `config/` — Manifest definitions for the operator and bundle
- `internal/` — The primary source code of the operator
- `must-gather/` — Source code for the must-gather diagnostic image
- `release/` — Containerfiles and related pieces for generating a release-ready bundle and catalog
- `test/` — Unit tests, integration tests, and QE end-to-end tests

**Build chain**:
- **Konflux** builds container images from `.tekton/` pipelines
- OLM bundle is generated from `bundle/` manifests
- The operator manages TopoLVM deployment as a sub-component

**Development commands**:
```bash
make build                    # Build operator binary
make test                     # Run unit tests
make bundle                   # Regenerate OLM bundle
make generate                 # Run code generators (deepcopy, CRDs)
make manifests                # Generate CRD manifests
make lint                     # Run linters
```

**Testing**:
- Unit tests: `make test`
- E2E tests run in CI via Prow jobs (see `release` repo)
- Local testing requires an OpenShift cluster with available block devices

**Key concepts**:
- **LVMCluster** is the primary user-facing API — one per cluster
- **vgmanager** runs as a DaemonSet on storage nodes, managing actual LVM operations
- **Thin provisioning** is used by default for efficient storage allocation
- The operator auto-discovers available block devices (can be filtered via `LVMCluster` spec)
