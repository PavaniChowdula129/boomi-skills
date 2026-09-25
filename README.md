# Boomi Agent Skills Collection

A comprehensive suite of Boomi skills and automation tooling for AI assistants, engineers, and architects working with the Boomi Enterprise Platform.

## Included Skills

| Skill | Description |
| :--- | :--- |
| **[`boomi-excel-audit`](./boomi-excel-audit)** | Generates multi-tab Excel audit reports for Boomi components supporting `BUILD`, `ENVIRONMENT`, and `ALL_ENVIRONMENTS` modes with hierarchy tracing. |
| **[`boomi-component-audit`](./boomi-component-audit)** | Inspects component references, dependency hierarchies, and audit metadata. |
| **[`boomi-integration`](./boomi-integration)** | Full-lifecycle Boomi integration development, deployment, CLI tools, and platform service automation. |
| **[`boomi-agentstudio`](./boomi-agentstudio)** | Author, deploy, and operate Boomi Agentstudio AI agents, tools, guardrails, and runtime packages. |
| **[`boomi-bdi`](./boomi-bdi)** | ELT data pipelines, CDC replication, and reverse-ETL activation via Boomi Data Integration. |
| **[`boomi-datahub`](./boomi-datahub)** | Master data management (MDM), model/source definitions, and golden record lifecycle stewardship. |
| **[`boomi-marketplace`](./boomi-marketplace)** | Browse, discover, and install integration recipes from the Boomi Marketplace. |

## Requirements & Setup

- **Python**: 3.10+ (using `uv` or `pip`)
- **Git**: For version control
- **Boomi Platform API**: Account ID, Username, and API Token configured via environment variables (see individual skill folders for details).

## Security Note

Credentials and environment configuration (`.env`) as well as runtime output reports are excluded via `.gitignore`.
