---
name: boomi-component-audit
description: Audits Boomi component usage across processes, sub-processes, process routes, maps, and connectors. Performs dynamic recursive hierarchy discovery (Main Process -> Process Call / Process Route -> Subprocess -> Audited Component) and validates active environment deployment status via the Boomi AtomSphere Platform API.
---

# Boomi Component Audit & Impact Analysis Skill

## Purpose
This skill enables an agent to take any Boomi `ComponentId` (and an optional `EnvironmentId` or `EnvironmentName`) and dynamically inspect:
1. **Audited Component Metadata**: Component Name, Type, Subtype, and Folder path.
2. **Recursive Parent Hierarchy**: Traces all inbound references upward to root processes:
   - **`DEPENDENT` references**: Subprocesses invoked via standard **Process Call** shapes, Maps, Profiles, or Connectors.
   - **`INDEPENDENT` references**: Subprocesses or processes linked through **Process Route** tables (`type="processroute"`).
3. **Environment Deployment Status**: Verifies against `DeployedPackage` records for a target environment to report whether the component or its calling process hierarchy is actively deployed.
4. **Consolidated Reporting**: Generates a unified audit record output (JSON, CSV, or formatted Excel `.xlsx`).

---

## Required Environment Variables
Ensure the following variables are defined in your `.env` or agent environment:
- `BOOMI_API_URL` (e.g., `https://api.boomi.com`)
- `BOOMI_ACCOUNT_ID`
- `BOOMI_USERNAME`
- `BOOMI_API_TOKEN`
- `BOOMI_ENVIRONMENT_ID` *(optional, for environment deployment verification)*

---

## Core Discovery & Auditing Rules

### 1. API Query Endpoints
All operations interact with the Boomi AtomSphere REST API v1:
- **Component Metadata**: `POST /api/rest/v1/{accountId}/ComponentMetadata/query`
- **Inbound References**: `POST /api/rest/v1/{accountId}/ComponentReference/query`
- **Active Deployments**: `POST /api/rest/v1/{accountId}/DeployedPackage/query`

### 2. Reference Classification Matrix
Use the `type` attribute returned by `ComponentReference` to categorize invocation types:
| Component Type | Reference Attribute `type` | Classification | Hierarchy Representation |
| :--- | :--- | :--- | :--- |
| `process` | `DEPENDENT` | Process Call Subprocess | `Parent Process -> [Process Call] -> Subprocess` |
| `processroute` | `INDEPENDENT` | Process Route Component | `Main Process -> [Process Route: Name] -> Audited Component` |
| `process` | `INDEPENDENT` | Routed Subprocess | `[Process Route: Name] -> Subprocess -> Audited Component` |
| `transform.map` | Any | Map Step Reference | `Process -> [Map: Name] -> Audited Component` |
| *(None found)* | N/A | Root Process | `Main Process [Root]` |

### 3. XML Shape Deep Inspection
When inspecting process XML definitions directly:
- **`documentproperties`**: Detects references inside `<sourcevalues><parametervalue>` (Set Properties / Lookups).
- **`map`**: Identifies maps, source/target profiles, and lookup functions (`CrossReferenceLookup`, `SqlLookup`, `DocumentCacheLookup`, `ConnectorCall`).
- **`connector`**: Identifies referenced Connection or Operation IDs.
- **`processcall`**: Identifies direct subprocess dependencies.
- **`processroute`**: Identifies route table links.

---

## Standard Workflow for Agents

When an audit request is received, follow this procedure:

1. **Resolve Audited Component Details**:
   - Query `ComponentMetadata/query` with `componentId = <targetComponentId>`.
   - Store Name, Type, Subtype, and Folder.

2. **Retrieve Active Environment Packages**:
   - If an `EnvironmentId` or `EnvironmentName` is specified, query `DeployedPackage/query` where `environmentId = <targetEnv>` and `active = true`.
   - Build a dictionary of active deployed components: `componentId -> {version, packageId, packageVersion}`.

3. **Traverse Inbound References Recursively**:
   - Query `ComponentReference/query` where `componentId = <targetComponentId>`.
   - For every parent:
     - Check if it is a `process`, `processroute`, or intermediate object (e.g. `transform.map`).
     - Record the reference mechanism (`DEPENDENT` vs `INDEPENDENT`).
     - Recurse upward until the root (Main Process) with no further parent callers is reached.

4. **Correlate Deployment Status**:
   - If the audited component ID is in the active packages list, mark as `ACTIVE DEPLOYED`.
   - If any parent Main Process in the hierarchy path is deployed, mark as `ACTIVE IN ENVIRONMENT via: <MainProcessName>`.
   - Otherwise, mark as `BUILD ONLY (Not active in environment)`.

5. **Emit the Report**:
   - Assemble the findings into a consolidated single audit record containing:
     - `Audited Component ID`
     - `Audited Component Name`
     - `Audited Component Type`
     - `Audited Component Folder`
     - `Target Environment`
     - `Deployment Status`
     - `Main Process(es)`
     - `Process Call Subprocess(es)`
     - `Process Route(s)`
     - `Process Route Subprocess(es)`
     - `Reference Hierarchy Path(s)`
     - `Invocation Mechanism(s)`
     - `Immediate Referencing Component(s)`

---

## CLI & Execution Reference

To run the audit directly via the bundled Python script:

python scripts/audit_component.py \
  --component-id "<TARGET_COMPONENT_ID>" \
  --environment-id "<TARGET_ENVIRONMENT_ID>"