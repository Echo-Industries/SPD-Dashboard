import os
import re
import secrets
import sqlite3
from functools import wraps
from datetime import datetime

from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
import requests

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

ERLC_API_KEY = os.getenv("ERLC_SERVER_KEY")
PORT = int(os.getenv("PORT", 5000))
DATABASE_PATH = os.getenv("DATABASE_PATH", "spd_operations.db")
ROBLOX_CLIENT_ID = os.getenv("ROBLOX_CLIENT_ID")
ROBLOX_CLIENT_SECRET = os.getenv("ROBLOX_CLIENT_SECRET")
ROBLOX_REDIRECT_URI = os.getenv("ROBLOX_REDIRECT_URI")
SPD_TEAM_NAME = os.getenv("SPD_TEAM_NAME", "SPD")
CASE_PREFIXES = {"arrest": "ARR", "citation": "CIT", "incident": "INC"}


def get_db():
    """Initialize and return SQLite database connection."""
    database = sqlite3.connect(DATABASE_PATH)
    database.row_factory = sqlite3.Row
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            payload TEXT NOT NULL,
            published_by_id TEXT NOT NULL,
            published_by_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS warrants (
            id TEXT PRIMARY KEY,
            suspect_name TEXT NOT NULL,
            suspect_id TEXT,
            charges TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            published_by_id TEXT NOT NULL,
            published_by_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS case_sequences (
            category TEXT PRIMARY KEY,
            last_value INTEGER NOT NULL
        )
        """
    )
    return database


def current_user():
    """Retrieve the current authenticated Roblox user from session."""
    return session.get("roblox_user")


def login_required(handler):
    """Decorator to enforce Roblox authentication on route handlers."""
    @wraps(handler)
    def wrapped(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "Sign in with Roblox first."}), 401
        return handler(*args, **kwargs)

    return wrapped


def is_spd_team_member(user, players):
    user_id = str(user.get("id", ""))
    user_name = str(user.get("name", "")).casefold()
    configured_team = "".join(character for character in SPD_TEAM_NAME.casefold() if character.isalnum())
    accepted_teams = {configured_team, "police", "spd"}
    for player in players:
        if not isinstance(player, dict):
            continue

        player_team = "".join(
            character for character in str(player.get("Team", "")).casefold() if character.isalnum()
        )
        if player_team not in accepted_teams:
            continue

        player_value = str(player.get("Player") or player.get("Username") or player.get("Name") or "")
        player_name, _, player_id = player_value.partition(":")
        known_id = str(player.get("UserId") or player.get("UserID") or player.get("id") or player_id)
        if (known_id and known_id == user_id) or player_name.casefold() == user_name:
            return True
    return False


def spd_team_member(user):
    """Verify that the user is a member of the SPD team in ER:LC."""
    if not ERLC_API_KEY or ERLC_API_KEY == "server_key_here":
        return False, "ER:LC server verification is not configured."

    try:
        response = requests.get(
            "https://api.erlc.gg/v2/server?Players=true",
            headers={"server-key": ERLC_API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        players = response.json().get("Players", [])
    except (requests.RequestException, ValueError, AttributeError):
        return False, "Unable to verify your current ER:LC team membership."

    if is_spd_team_member(user, players):
        return True, None

    return False, f"You must be on the {SPD_TEAM_NAME} team in ER:LC to publish a record."


def police_team_required(handler):
    """Restrict dashboard data endpoints to currently verified police team members."""
    @wraps(handler)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            response = make_response(jsonify({"error": "Sign in with Roblox first."}), 401)
        else:
            is_member, _ = spd_team_member(user)
            if not is_member:
                response = make_response(jsonify({"error": "Access is restricted to current police team members."}), 403)
            else:
                response = make_response(handler(*args, **kwargs))
        response.headers["Cache-Control"] = "no-store"
        return response

    return wrapped


@app.route("/")
def index():
    """Serves the main Seattle PD Operations dashboard."""
    if not current_user():
        return redirect(url_for("login"))
    is_member, _ = spd_team_member(current_user())
    if not is_member:
        response = make_response(render_template("access_denied.html"), 403)
    else:
        response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/login")
def login():
    """Serves the Roblox OAuth login page."""
    if current_user():
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/auth/roblox/login")
def roblox_login():
    """Initiates Roblox OAuth2 authentication flow."""
    if not all((ROBLOX_CLIENT_ID, ROBLOX_CLIENT_SECRET, ROBLOX_REDIRECT_URI)):
        return jsonify({
            "error": "Configure ROBLOX_CLIENT_ID, ROBLOX_CLIENT_SECRET, and ROBLOX_REDIRECT_URI in your .env file."
        }), 500

    state = secrets.token_urlsafe(32)
    session["roblox_oauth_state"] = state
    params = {
        "client_id": ROBLOX_CLIENT_ID,
        "redirect_uri": ROBLOX_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
    }
    authorization_url = requests.Request(
        "GET", "https://apis.roblox.com/oauth/v1/authorize", params=params
    ).prepare().url
    return redirect(authorization_url)


@app.route("/auth/roblox/callback")
def roblox_callback():
    """Handles the Roblox OAuth2 callback and user session setup."""
    if request.args.get("state") != session.pop("roblox_oauth_state", None):
        return "Invalid Roblox OAuth state.", 400

    code = request.args.get("code")
    if not code:
        return f"Roblox sign-in failed: {request.args.get('error_description', 'No authorization code returned.')}", 400

    try:
        token_response = requests.post(
            "https://apis.roblox.com/oauth/v1/token",
            data={
                "client_id": ROBLOX_CLIENT_ID,
                "client_secret": ROBLOX_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": ROBLOX_REDIRECT_URI,
            },
            timeout=10,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        user_response = requests.get(
            "https://apis.roblox.com/oauth/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        user_response.raise_for_status()
        user_data = user_response.json()
    except (requests.RequestException, KeyError) as error:
        return f"Roblox sign-in failed: {error}", 502

    user_id = str(user_data["sub"])
    avatar_url = None
    try:
        avatar_response = requests.get(
            "https://thumbnails.roblox.com/v1/users/avatar-headshot",
            params={"userIds": user_id, "size": "150x150", "format": "Png", "isCircular": "false"},
            timeout=10,
        )
        avatar_response.raise_for_status()
        avatar_data = avatar_response.json().get("data", [])
        if avatar_data:
            avatar_url = avatar_data[0].get("imageUrl")
    except (requests.RequestException, ValueError):
        pass

    session["roblox_user"] = {
        "id": user_id,
        "name": user_data.get("preferred_username") or user_data.get("name") or "Roblox user",
        "avatarUrl": avatar_url,
    }
    return redirect(url_for("index"))


@app.route("/auth/logout")
def logout():
    """Clears user session and redirects to login."""
    session.pop("roblox_user", None)
    return redirect(url_for("login"))


@app.route("/api/auth/me")
def auth_me():
    """Returns the current authenticated user information."""
    return jsonify({"user": current_user()})


@app.route("/api/records", methods=["GET"])
@police_team_required
def list_records():
    """Fetches all incident records from the database."""
    database = get_db()
    rows = database.execute("SELECT payload FROM records ORDER BY created_at DESC").fetchall()
    database.close()
    import json
    return jsonify([json.loads(row["payload"]) for row in rows])


@app.route("/api/records", methods=["POST"])
@police_team_required
def publish_record():
    """Publishes a new arrest, citation, or incident report."""
    import json

    record = request.get_json(silent=True) or {}
    if not isinstance(record, dict) or "category" not in record:
        return jsonify({"error": "Record category is required."}), 400
    if not isinstance(record["category"], str) or record["category"] not in {"arrest", "citation", "incident"}:
        return jsonify({"error": "Record category must be arrest, citation, or incident."}), 400

    user = current_user()
    record["publishedById"] = user["id"]
    record["publishedByName"] = user["name"]
    prefix = CASE_PREFIXES[record["category"]]
    database = get_db()
    try:
        database.execute("BEGIN IMMEDIATE")
        sequence = database.execute(
            "SELECT last_value FROM case_sequences WHERE category = ?",
            (record["category"],),
        ).fetchone()
        if sequence:
            next_value = sequence["last_value"] + 1
        else:
            existing_ids = database.execute(
                "SELECT id FROM records WHERE category = ?",
                (record["category"],),
            ).fetchall()
            existing_values = [
                int(match.group(1))
                for row in existing_ids
                if (match := re.fullmatch(rf"{prefix}-(\d+)", row["id"]))
            ]
            next_value = max(existing_values, default=0) + 1
        database.execute(
            "INSERT INTO case_sequences (category, last_value) VALUES (?, ?) "
            "ON CONFLICT(category) DO UPDATE SET last_value = excluded.last_value",
            (record["category"], next_value),
        )
        record["id"] = f"{prefix}-{next_value:05d}"
        database.execute(
            "INSERT INTO records (id, category, payload, published_by_id, published_by_name, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (record["id"], record["category"], json.dumps(record), user["id"], user["name"]),
        )
        database.commit()
    except sqlite3.IntegrityError:
        database.rollback()
        return jsonify({"error": "Unable to assign a unique case number."}), 409
    finally:
        database.close()
    return jsonify(record), 201


@app.route("/api/records/<record_id>", methods=["DELETE"])
@police_team_required
def delete_record(record_id):
    """Deletes a record if the requester is the publisher."""
    database = get_db()
    result = database.execute(
        "DELETE FROM records WHERE id = ? AND published_by_id = ?",
        (record_id, current_user()["id"]),
    )
    database.commit()
    database.close()
    if result.rowcount == 0:
        return jsonify({"error": "You can only delete records you published."}), 403
    return jsonify({"deleted": record_id})


@app.route("/api/warrants", methods=["GET"])
@police_team_required
def list_warrants():
    """Fetches all active warrants from database."""
    database = get_db()
    rows = database.execute("SELECT payload FROM warrants WHERE status = 'active' ORDER BY created_at DESC").fetchall()
    database.close()
    import json
    return jsonify([json.loads(row["payload"]) for row in rows])


@app.route("/api/warrants", methods=["POST"])
@police_team_required
def publish_warrant():
    """Publishes a new manual warrant or BOLO."""
    import json

    warrant = request.get_json(silent=True) or {}
    required_fields = {"id", "suspect_name", "charges"}
    if not required_fields.issubset(warrant):
        return jsonify({"error": "ID, suspect name, and charges are required."}), 400

    user = current_user()
    warrant["publishedById"] = user["id"]
    warrant["publishedByName"] = user["name"]
    warrant["source"] = "manual"
    warrant["status"] = "active"
    warrant["timestamp"] = datetime.now().isoformat()
    
    database = get_db()
    try:
        database.execute(
            "INSERT INTO warrants (id, suspect_name, suspect_id, charges, source, status, published_by_id, published_by_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (warrant["id"], warrant["suspect_name"], warrant.get("suspect_id"), warrant["charges"], warrant["source"], warrant["status"], user["id"], user["name"]),
        )
        database.commit()
    except sqlite3.IntegrityError:
        database.close()
        return jsonify({"error": "That warrant ID has already been published."}), 409
    database.close()
    return jsonify(warrant), 201


@app.route("/api/warrants/<warrant_id>", methods=["DELETE"])
@police_team_required
def delete_warrant(warrant_id):
    """Marks a warrant/BOLO as inactive."""
    database = get_db()
    result = database.execute(
        "UPDATE warrants SET status = 'inactive', updated_at = datetime('now') WHERE id = ? AND published_by_id = ?",
        (warrant_id, current_user()["id"]),
    )
    database.commit()
    database.close()
    if result.rowcount == 0:
        return jsonify({"error": "You can only remove warrants you created."}), 403
    return jsonify({"removed": warrant_id})


@app.route("/api/erlc/mdt", methods=["GET"])
@police_team_required
def get_erlc_mdt():
    """Pulls current warrants and BOLOs from ERLC MDT system."""
    if not ERLC_API_KEY or ERLC_API_KEY == "server_key_here":
        return jsonify({
            "error": "ERLC_SERVER_KEY is not configured in your .env file."
        }), 500

    try:
        headers = {"server-key": ERLC_API_KEY}
        response = requests.get(
            "https://api.erlc.gg/v2/server?Players=true&Warrants=true",
            headers=headers,
            timeout=10
        )

        if response.status_code != 200:
            return jsonify({
                "error": f"ER:LC API returned status code {response.status_code}",
                "details": response.text
            }), response.status_code

        data = response.json()
        warrants = data.get("Warrants", [])
        players = data.get("Players", [])
        
        # Auto-clean expired warrants (suspects no longer in game)
        database = get_db()
        active_player_ids = {str(p.get("UserId", p.get("UserID", ""))) for p in players if isinstance(p, dict)}
        database.execute(
            "UPDATE warrants SET status = 'inactive', updated_at = datetime('now') WHERE source = 'erlc' AND suspect_id NOT IN ({}) AND status = 'active'".format(
                ",".join(["'" + pid + "'" for pid in active_player_ids]) if active_player_ids else "''"
            )
        )
        database.commit()
        database.close()
        
        return jsonify({
            "warrants": warrants,
            "playerCount": len(players),
            "syncTime": datetime.now().isoformat()
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to connect to ER:LC API: {str(e)}"}), 500


@app.route("/api/erlc/status", methods=["GET"])
@police_team_required
def get_erlc_status():
    """Proxy endpoint to fetch live player lists, active units, and emergency calls from ER:LC."""
    if not ERLC_API_KEY or ERLC_API_KEY == "server_key_here":
        return jsonify({
            "error": "ERLC_SERVER_KEY is not configured in your .env file."
        }), 500

    try:
        headers = {"server-key": ERLC_API_KEY}
        response = requests.get(
            "https://api.erlc.gg/v2/server?Players=true&Vehicles=true&EmergencyCalls=true",
            headers=headers,
            timeout=10
        )

        if response.status_code != 200:
            return jsonify({
                "error": f"ER:LC API returned status code {response.status_code}",
                "details": response.text
            }), response.status_code

        data = response.json()
        data["isSpdMember"] = is_spd_team_member(current_user(), data.get("Players", []))
        data["spdTeamName"] = SPD_TEAM_NAME
        return jsonify(data)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to connect to ER:LC API: {str(e)}"}), 500


if __name__ == "__main__":
    print(f"[*] Starting Seattle PD Operations Dashboard on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True)