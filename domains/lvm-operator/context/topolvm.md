<!-- Supplemental context for LVM Operator dev environment. Repo's native CLAUDE.md (if any) takes priority. -->

# topolvm — LVMS Context

**Category**: Development

**Purpose**: CSI (Container Storage Interface) driver that provides dynamic provisioning of LVM logical volumes as Kubernetes persistent volumes.

**Relationship to lvm-operator**:
- TopoLVM is the **underlying storage driver** that LVMS deploys and manages
- The `lvm-operator` deploys TopoLVM components (controller, node plugin) as part of `LVMCluster` reconciliation
- TopoLVM handles the actual CSI RPCs (CreateVolume, DeleteVolume, NodeStageVolume, etc.)
- The `openshift/topolvm` fork carries downstream patches on top of the upstream `topolvm/topolvm`

**Key components**:
- **topolvm-controller** — CSI controller plugin (runs as Deployment):
  - Handles `CreateVolume`/`DeleteVolume` CSI calls
  - Schedules volumes to nodes based on available capacity
- **topolvm-node** — CSI node plugin (runs as DaemonSet):
  - Handles `NodeStageVolume`/`NodePublishVolume` CSI calls
  - Manages LVM logical volumes on each node
  - Reports node capacity via `Node` annotations
- **lvmd** — Local LVM daemon:
  - Runs on each node, wraps LVM CLI commands
  - Provides gRPC API for volume group operations

**Key paths**:
- `cmd/` — Entry points for controller, node plugin, and lvmd
- `pkg/` — Core logic packages
  - `pkg/controller/` — CSI controller service
  - `pkg/driver/` — CSI node service
  - `pkg/lvmd/` — LVM daemon implementation
- `deploy/` — Deployment manifests
- `e2e/` — End-to-end test suite

**Downstream differences**:
- The `openshift/topolvm` fork may carry patches for OpenShift-specific integration
- Build images are produced by Konflux pipelines
- The upstream `topolvm/topolvm` repo is the canonical reference for CSI driver behavior
