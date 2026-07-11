# LVMS — LVM Storage for OpenShift

LVMS (Logical Volume Manager Storage) provides local persistent storage for
OpenShift clusters using Linux LVM, exposed through the TopoLVM CSI driver.
It is the default storage solution for single-node and resource-constrained
deployments where external storage (Ceph, NFS) is impractical.

## Core concept

The LVM Operator reconciles `LVMCluster` CRs to manage volume groups and thin
pools on node-local block devices, then exposes them as `StorageClass` resources
for dynamic PVC provisioning.

## Architecture

1. **lvm-operator** (Deployment) — reconciles LVMCluster CRs, manages VGs and
   StorageClasses
2. **topolvm-controller** (Deployment) — CSI controller for provisioning and
   scheduling
3. **topolvm-node** (DaemonSet) — per-node CSI agent running `lvmd` to manage
   LVM operations on local disks

## Build and release

Builds go through Konflux pipelines (`.tekton/` in each repo). The NUDGE
mechanism triggers downstream rebuilds when upstream images change:
topolvm → lvm-operator → bundle → catalog.

Release gating uses Enterprise Contract policies and `ReleasePlanAdmission`
in the `konflux-release-data` repo, with version approval in
`product-definitions`.

## Constraints

- Storage is **node-local** — no replication across nodes
- Requires available block devices (unpartitioned disks or free VG space)

See `docs/architecture.md` for component and build chain diagrams.
