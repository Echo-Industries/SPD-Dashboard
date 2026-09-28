# Seattle Police Department Operations Dashboard

A real-time law enforcement operations and incident management system for the Seattle Police Department, built with Flask and designed for ER:LC (Emergency Response: Liberty County) gameplay.

## Features

- **Arrest Logging**: Document arrests, charges, and detainee information
- **Citation Management**: Record traffic citations and citations for other violations
- **Incident Reports**: Comprehensive incident documentation and investigation tracking
- **BOLO & Warrant System**: Manual logging combined with automatic ERLC MDT warrant/BOLO pull
  - Auto-remove warrants/BOLOs when suspects leave the game
  - Track logging source (Manual vs ERLC automatic)
  - Active warrants dashboard with real-time status
- **Live Operations Hub**: Real-time synchronization with active SPD personnel and units
- **Incident Analytics**: Interactive charts and metrics for arrest patterns and response rates
- **Multi-User Support**: Roblox OAuth2 authentication for secure access
- **Record Management**: Search, filter, and manage all historical incident reports

## Technology Stack

- **Backend**: Python Flask 3.0.2
- **Frontend**: HTML5, Tailwind CSS, Chart.js
- **Database**: SQLite3
- **Authentication**: Roblox OAuth2
- **API Integration**: ER:LC API for live server data and MDT warrant/BOLO syncing

## Prerequisites

- Python 3.8+
- Roblox Developer Credentials (OAuth2 application)
- ER:LC Server Access with API key

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Echo-Industries/Seattle-PD-Dashboard.git
   cd Seattle-PD-Dashboard
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your Roblox OAuth credentials and ER:LC server key

5. **Run the application**:
   ```bash
   python app.py
   ```
   Navigate to `http://localhost:5000` in your browser

## API Endpoints

### Authentication
- `GET /auth/roblox/login` - Initiate Roblox OAuth2 flow
- `GET /auth/roblox/callback` - Handle OAuth2 callback
- `GET /auth/logout` - Clear user session
- `GET /api/auth/me` - Get current user info

### Records Management
- `GET /api/records` - Fetch all incident records
- `POST /api/records` - Publish new arrest, citation, or incident report
- `DELETE /api/records/<record_id>` - Delete a record (owner only)

### Warrants & BOLOs
- `GET /api/warrants` - Fetch all active warrants (manual + ERLC)
- `POST /api/warrants` - Log new manual warrant/BOLO
- `DELETE /api/warrants/<warrant_id>` - Remove warrant/BOLO
- `GET /api/erlc/mdt` - Sync and retrieve current ERLC MDT warrants/BOLOs

### Live Operations
- `GET /api/erlc/status` - Get live player lists and active units from ER:LC

## Database Schema

### Records Table
- `id` - Unique record identifier
- `category` - Type of record (arrest, citation, incident, warrant, bolo)
- `payload` - Full JSON record data
- `published_by_id` - Roblox user ID of creator
- `published_by_name` - Roblox username of creator
- `created_at` - Timestamp of creation

### Warrants Table
- `id` - Unique warrant identifier
- `suspect_name` - Name of suspect
- `suspect_id` - Roblox user ID if known
- `charges` - Charges associated with warrant
- `source` - "manual" or "erlc"
- `status` - "active" or "inactive"
- `published_by_id` - Creator user ID
- `created_at` - Timestamp
- `updated_at` - Last update timestamp

## Team Verification

Users must be on the configured SPD team in ER:LC to log arrests, citations, and incidents. Team verification is performed via the ER:LC API on each action.

## License

MIT