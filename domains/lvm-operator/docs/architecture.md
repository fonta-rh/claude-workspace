# LVMS Architecture

## Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     OpenShift Cluster                           │
│                                                                 │
│  ┌──────────────────────┐    ┌──────────────────────────────┐  │
│  │   lvm-operator       │    │   TopoLVM (CSI Driver)       │  │
│  │   (Deployment)       │    │                              │  │
│  │                      │    │  ┌─────────────────────┐     │  │
│  │  - LVMCluster CR     │───>│  │ topolvm-controller  │     │  │
│  │  - Reconciliation    │    │  │ (Deployment)        │     │  │
│  │  - VG management     │    │  └─────────────────────┘     │  │
│  │  - StorageClass      │    │                              │  │
│  │    creation           │    │  ┌─────────────────────┐     │  │
│  └──────────────────────┘    │  │ topolvm-node        │     │  │
│                              │  │ (DaemonSet)         │     │  │
│                              │  │                     │     │  │
│                              │  │  ┌──────────────┐   │     │  │
│                              │  │  │    lvmd       │   │     │  │
│                              │  │  │ (LVM daemon)  │   │     │  │
│                              │  │  └──────┬───────┘   │     │  │
│                              │  └─────────┼───────────┘     │  │
│                              └────────────┼─────────────────┘  │
│                                           │                     │
│                              ┌────────────▼───────────────┐    │
│                              │  LVM (Logical Volume Mgr)  │    │
│                              │  - Volume Groups            │    │
│                              │  - Thin Pools               │    │
│                              │  - Logical Volumes          │    │
│                              └────────────┬───────────────┘    │
│                                           │                     │
│                              ┌────────────▼───────────────┐    │
│                              │    Block Devices            │    │
│                              │    (disks, partitions)      │    │
│                              └────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## Konflux Build Chain

The NUDGE mechanism is Konflux's dependency-driven rebuild system — when an upstream component image changes, it automatically triggers a rebuild of downstream components that depend on it.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           BUILD CHAIN DIAGRAM                                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌───────────────────┐   ┌─────────────┐                  │
│  │   topolvm    │   │   lvm-operator    │   │ must-gather │                  │
│  │  (topolvm    │   │  (lvm-operator    │   │(lvm-operator│                  │
│  │    repo)     │   │     repo)         │   │    repo)    │                  │
│  └──────┬───────┘   └────────┬──────────┘   └──────┬──────┘                  │
│         │                    │                     │                         │
│         │    NUDGE           │    NUDGE            │   NUDGE                 │
│         └────────────────────┼─────────────────────┘                         │
│                              ▼                                               │
│                   ┌────────────────────┐                                     │
│                   │ lvm-operator-bundle│  ◄── Single Arch Build!             │
│                   │  (lvm-operator     │                                     │
│                   │      repo)         │                                     │
│                   └─────────┬──────────┘                                     │
│                             │                                                │
│                             │    NUDGE                                       │
│                             ▼                                                │
│                   ┌────────────────────┐                                     │
│                   │lvm-operator-catalog│                                     │
│                   │  (lvm-operator     │                                     │
│                   │      repo)         │                                     │
│                   └────────────────────┘                                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Release Pipeline

```
Konflux Build ──► Enterprise Contract (EC) ──► ReleasePlanAdmission ──► Product Definitions ──► OLM Catalog (FBC)
                  (policy validation)          (promotion gates)        (version approval)      (distribution)
                  konflux-release-data          konflux-release-data     product-definitions
```

## Data Flow

1. **Development**: Engineers work on `lvm-operator` and `topolvm` repos
2. **CI Testing**: PRs trigger Prow jobs configured in the `release` repo
3. **Build**: Merged code triggers Konflux pipelines (`.tekton/` in each repo)
4. **Validation**: Enterprise Contract policies in `konflux-release-data` validate artifacts
5. **Release Gating**: `ReleasePlanAdmission` controls promotion through environments
6. **Product Approval**: `product-definitions` must have matching version entries
7. **Distribution**: Approved builds are published as OLM bundles in FBC catalogs
