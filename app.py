import os

import psycopg
from databricks.sdk import WorkspaceClient
from flask import Flask, flash, redirect, render_template, request, url_for
from psycopg_pool import ConnectionPool

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")

VALID_STATUSES = ["open", "in_progress", "resolved"]

# ---------------------------------------------------------------------------
# Lakebase connection setup
#
# Databricks Apps authenticate to Lakebase using short-lived OAuth tokens
# (1 hour lifetime). Rather than a static password, every new pooled
# connection calls generate_database_credential() to fetch a fresh token.
# When deployed, this runs as the app's service principal. When run locally,
# it runs as your own Databricks user identity. No credentials are ever
# hardcoded or stored in this file.
# ---------------------------------------------------------------------------

w = WorkspaceClient()

LAKEBASE_ENDPOINT_NAME = os.environ["LAKEBASE_ENDPOINT_NAME"]
# Expected format: projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}
PGUSER = os.environ["PGUSER"]
PGHOST = os.environ["PGHOST"]
PGPORT = os.environ.get("PGPORT", "5432")
PGDATABASE = os.environ.get("PGDATABASE", "databricks_postgres")
PGSSLMODE = os.environ.get("PGSSLMODE", "require")


class OAuthConnection(psycopg.Connection):
    """A psycopg Connection that fetches a fresh Databricks OAuth token
    as its password on every new connection, instead of using a static
    password."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        credential = w.postgres.generate_database_credential(
            endpoint=LAKEBASE_ENDPOINT_NAME
        )
        kwargs["password"] = credential.token
        return super().connect(conninfo, **kwargs)


pool = ConnectionPool(
    conninfo=(
        f"dbname={PGDATABASE} user={PGUSER} host={PGHOST} "
        f"port={PGPORT} sslmode={PGSSLMODE}"
    ),
    connection_class=OAuthConnection,
    min_size=1,
    max_size=5,
    open=True,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    """View all support tickets, optionally filtered by status."""
    status_filter = request.args.get("status")

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Get ticket counts by status
            cur.execute(
                """
                SELECT status, COUNT(*) as count
                FROM tickets
                GROUP BY status
                """
            )
            status_counts = {row[0]: row[1] for row in cur.fetchall()}
            total_count = sum(status_counts.values())
            
            if status_filter in VALID_STATUSES:
                cur.execute(
                    """
                    SELECT ticket_id, title, status, created_by, created_at, priority
                    FROM tickets
                    WHERE status = %s
                    ORDER BY created_at DESC
                    """,
                    (status_filter,),
                )
            else:
                status_filter = None
                cur.execute(
                    """
                    SELECT ticket_id, title, status, created_by, created_at, priority
                    FROM tickets
                    ORDER BY created_at DESC
                    """
                )
            tickets = cur.fetchall()

    return render_template(
        "index.html",
        tickets=tickets,
        statuses=VALID_STATUSES,
        current_filter=status_filter,
        status_counts=status_counts,
        total_count=total_count,
    )


@app.route("/tickets/new", methods=["POST"])
def create_ticket():
    """Create a new support ticket."""
    title = request.form.get("title", "").strip()
    created_by = request.form.get("created_by", "").strip()
    priority = request.form.get("priority", "medium").strip()

    if not title:
        flash("Title is required.")
        return redirect(url_for("index"))
    if not created_by:
        flash("Your name or email is required.")
        return redirect(url_for("index"))

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tickets (title, status, created_by, priority)
                VALUES (%s, 'open', %s, %s)
                """,
                (title, created_by, priority),
            )

    flash(f'Ticket "{title}" created.')
    return redirect(url_for("index"))


@app.route("/tickets/<int:ticket_id>")
def view_ticket(ticket_id):
    """View a single ticket and all its messages."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticket_id, title, status, created_by, created_at, priority
                FROM tickets
                WHERE ticket_id = %s
                """,
                (ticket_id,),
            )
            ticket = cur.fetchone()

            if ticket is None:
                flash(f"Ticket #{ticket_id} was not found.")
                return redirect(url_for("index"))

            cur.execute(
                """
                SELECT message_id, message_text, author, created_at
                FROM ticket_messages
                WHERE ticket_id = %s
                ORDER BY created_at ASC
                """,
                (ticket_id,),
            )
            messages = cur.fetchall()

    return render_template(
        "ticket.html", ticket=ticket, messages=messages, statuses=VALID_STATUSES
    )


@app.route("/tickets/<int:ticket_id>/messages", methods=["POST"])
def add_message(ticket_id):
    """Add a new message to an existing ticket."""
    message_text = request.form.get("message_text", "").strip()
    author = request.form.get("author", "").strip()

    if not message_text:
        flash("Message text is required.")
        return redirect(url_for("view_ticket", ticket_id=ticket_id))
    if not author:
        flash("Author is required.")
        return redirect(url_for("view_ticket", ticket_id=ticket_id))

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Confirm the ticket exists before inserting, so we can give a
            # clear error instead of a silent orphaned-looking insert.
            cur.execute("SELECT 1 FROM tickets WHERE ticket_id = %s", (ticket_id,))
            if cur.fetchone() is None:
                flash(f"Ticket #{ticket_id} was not found.")
                return redirect(url_for("index"))

            cur.execute(
                """
                INSERT INTO ticket_messages (ticket_id, message_text, author)
                VALUES (%s, %s, %s)
                """,
                (ticket_id, message_text, author),
            )

    return redirect(url_for("view_ticket", ticket_id=ticket_id))


@app.route("/tickets/<int:ticket_id>/status", methods=["POST"])
def update_status(ticket_id):
    """Update a ticket's status."""
    new_status = request.form.get("status", "")

    if new_status not in VALID_STATUSES:
        flash(f"'{new_status}' is not a valid status.")
        return redirect(url_for("view_ticket", ticket_id=ticket_id))

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tickets SET status = %s WHERE ticket_id = %s",
                (new_status, ticket_id),
            )
            if cur.rowcount == 0:
                flash(f"Ticket #{ticket_id} was not found.")
                return redirect(url_for("index"))

    flash(f"Status updated to '{new_status}'.")
    return redirect(url_for("view_ticket", ticket_id=ticket_id))


@app.route("/tickets/<int:ticket_id>/delete", methods=["POST"])
def delete_ticket(ticket_id):
    """Delete a ticket and all its messages."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # First, check if the ticket exists
            cur.execute("SELECT title FROM tickets WHERE ticket_id = %s", (ticket_id,))
            ticket = cur.fetchone()
            
            if ticket is None:
                flash(f"Ticket #{ticket_id} was not found.")
                return redirect(url_for("index"))
            
            # Delete messages first (foreign key constraint)
            cur.execute(
                "DELETE FROM ticket_messages WHERE ticket_id = %s",
                (ticket_id,)
            )
            
            # Then delete the ticket
            cur.execute(
                "DELETE FROM tickets WHERE ticket_id = %s",
                (ticket_id,)
            )
    
    flash(f'Ticket #{ticket_id} "{ticket[0]}" deleted.')
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
