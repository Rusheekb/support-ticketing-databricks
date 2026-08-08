# Support Ticketing App

A small internal support ticketing system built on **Databricks Apps** (Flask) with **Lakebase Postgres** as the data layer, built as Day 1 homework for the DataExpert.io Databricks AI Boot Camp.

**Live app:** https://support-ticketing-7474649209065127.aws.databricksapps.com/

## Features

- View all support tickets, with filtering by status (`open` / `in_progress` / `resolved`)
- Create new tickets
- View a single ticket and its full message thread
- Add messages to an existing ticket
- Update a ticket's status
- Ticket priority (`low` / `medium` / `high`)
- Ticket statistics summary (counts by status)
- Delete a ticket (with confirmation) — cascades to its messages

## Stack

- **App:** Flask, deployed via Databricks Apps
- **Database:** Lakebase Postgres (Autoscaling), accessed via `psycopg` + `psycopg_pool`
- **Auth:** Databricks OAuth token rotation — the app's service principal generates a short-lived credential (`w.postgres.generate_database_credential`) for every new pooled connection. No static passwords or secrets are stored anywhere in the code or config.

## Schema

**tickets**
| Column | Type |
|---|---|
| ticket_id | SERIAL PK |
| title | TEXT |
| status | TEXT (default `open`) |
| priority | TEXT (default `medium`) |
| created_by | TEXT |
| created_at | TIMESTAMPTZ |

**ticket_messages**
| Column | Type |
|---|---|
| message_id | SERIAL PK |
| ticket_id | INTEGER, FK → tickets(ticket_id), `ON DELETE CASCADE` |
| message_text | TEXT |
| author | TEXT |
| created_at | TIMESTAMPTZ |

## Project structure

```
support-ticketing/
├── app.py            # routes + Lakebase connection setup
├── app.yaml           # Databricks Apps entrypoint + env vars
├── requirements.txt
└── templates/
    ├── index.html      # ticket list, filters, stats, create form
    └── ticket.html      # ticket detail, messages, status/priority update, delete
```

## Running locally

Requires a Databricks CLI profile authenticated to the workspace hosting the Lakebase project, since the app authenticates as your own Databricks user identity when run outside of Databricks Apps.

```bash
pip install -r requirements.txt
python app.py
```

## Notes

- Environment variables (`PGUSER`, `PGHOST`, `PGDATABASE`, `LAKEBASE_ENDPOINT_NAME`) are declared in `app.yaml` rather than hardcoded, since this workspace's UI doesn't expose a manual "add environment variable" option for Databricks Apps.
- `LAKEBASE_ENDPOINT_NAME` must be the full Lakebase endpoint resource path — `projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}` — not just the project name.
