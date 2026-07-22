# Docker Environment

Generated at: 2026-07-22T23:02:12+08:00

## Docker

| Field | Value |
| --- | --- |
| Docker client | `25.0.3` |
| Docker server | `25.0.3` |
| Docker Compose | `v2.24.6-desktop.1` |
| Engine state | running |
| Operating system | Docker Desktop |
| Kernel | `5.15.133.1-microsoft-standard-WSL2` |

Docker access from the unprivileged sandbox returned `Access is denied`, but
the approved escalated Docker calls succeeded. This is a Codex sandbox access
boundary, not a Docker daemon failure.

## PostgreSQL Container

| Field | Value |
| --- | --- |
| Service | `postgres` |
| Container | `cloud_expert-postgres-1` |
| Container ID | `e6dcd73052da` |
| Image | `postgres:16` |
| State | `running` |
| Health | `healthy` |
| Ports | `0.0.0.0:54329->5432/tcp` |
| Created at | `2026-07-21 23:19:07 +0800 CST` |
| Running for | `24 hours ago` |

`docker compose exec -T postgres pg_isready` returned:

```text
/var/run/postgresql:5432 - accepting connections
```

## PostgreSQL Server

```text
PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1) on x86_64-pc-linux-gnu
```

Connection identity from `cloud_expert_r011_fresh`:

| Field | Value |
| --- | --- |
| Database | `cloud_expert_r011_fresh` |
| User | `cloud_expert` |
| Schema | `public` |
| Timezone | `Etc/UTC` |

## Configuration Notes

The current Compose service pins `postgres:16`, exposes `54329`, and uses
UTF-8 initialization. Docker logs showed:

```text
locale "en_US.utf8"
default database encoding ... "UTF8"
default time zone ... Etc/UTC
```

The service currently uses a Docker-managed local volume created by Compose.
The Compose file does not explicitly declare a named volume or parameterized
environment-variable placeholders; this remains a non-blocking reproducibility
improvement for a later config cleanup, not a failure of this R011 run.
