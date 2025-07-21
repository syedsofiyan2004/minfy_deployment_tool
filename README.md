# Minfy CLI

Minfy CLI is a Vercel-like tool for deploying static front-end apps (React, Vite, Angular, Next.js) to AWS S3 with built-in monitoring via Prometheus and Grafana.

## Features

- Project initialization (`minfy init`)
- Auto-detection of app framework and build plan (`minfy detect`)
- Build & deploy (host or Docker) to AWS S3 with versioning (`minfy deploy`)
- View deployment status & rollback (`minfy status`, `minfy rollback`)
- Provision, inspect, and tear down a monitoring stack (Prometheus/Grafana) on AWS via Terraform (`minfy monitor`)

## Prerequisites

- Python 3.12+
- Node.js & npm (for host builds)
- Docker (for containerized builds)
- Terraform CLI in your PATH (for provisioning monitoring infra)

## Installation

```shell
# Clone repo
git clone <repo-url>
cd minfy-cli

# Install package and entrypoint
pip install .
```

## Usage

```shell
# 1. Initialize project directory
minfy init

# 2. Detect build plan
minfy detect

# 3. Build & deploy to AWS
minfy deploy [--env-file path/to/.env]

# 4. Check current site & versions
minfy status

# 5. Roll back to a previous version
minfy rollback

# 6. Set up monitoring
minfy monitor init         # locally generate compose & prom config
minfy monitor enable       # provision on AWS via Terraform
minfy monitor status       # show URLs for Grafana & Prometheus
minfy monitor dashboard    # import & open dashboards
minfy monitor disable      # destroy monitoring stack

# 7. Manage config variables
minfy config set KEY=VALUE
minfy config list
minfy config env <env>
```

## Project Structure

```
minfy-cli/
├── src/minfy/commands  # CLI command implementations
├── src/minfy/config     # Global config loader
├── tests/               # pytest suites
├── .github/workflows/ci.yml
├── pyproject.toml
└── README.md
```

## Aligning with Capstone Requirements

- **CLI core**: init, detect, deploy, status, rollback, monitor
- **Framework support**: CRA, Vite, Angular, Next.js
- **Infrastructure as Code**: Terraform modules under monitor
- **Monitoring**: Prometheus and Grafana with real metrics
- **CI/CD**: GitHub Actions pipeline included
- **Documentation**: This README provides install & usage

---

Build static sites to AWS as simply as `minfy deploy` no AWS knowledge required!
