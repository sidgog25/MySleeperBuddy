import os
import sys
import logging
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions
from typing import Any, Dict, List, Optional
import time

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

def get_supabase_credentials():
    """
    Get Supabase credentials from environment variables or Streamlit secrets.
    Streamlit Cloud stores secrets in st.secrets, not environment variables.
    """
    # First try environment variables (works locally with .env file)
    supabase_key = os.getenv("SUPABASE_KEY")
    supabase_url = os.getenv("SUPABASE_API_URL")

    # If not found, try Streamlit secrets (for Streamlit Cloud deployment)
    if not supabase_key or not supabase_url:
        try:
            import streamlit as st
            supabase_key = supabase_key or st.secrets.get("SUPABASE_KEY")
            supabase_url = supabase_url or st.secrets.get("SUPABASE_API_URL")
        except (ImportError, AttributeError, KeyError):
            # Not running in Streamlit or secrets not configured
            pass

    return supabase_key, supabase_url

SUPABASE_KEY, SUPABASE_URL = get_supabase_credentials()



def main(username: str = None, league_id: str = None) -> None:
    """
    Main function to extract and upsert Sleeper data.
    
    Args:
        username: Sleeper username (optional, for future use)
        league_id: Sleeper League ID (required)
    """
    url = "https://api.sleeper.app/v1/"
    
    # If parameters not provided, prompt for them (backward compatibility)
    if league_id is None:
        league_id = input("Enter Sleeper League ID: ")
    if username is None:
        username = input("Enter Sleeper Username (optional): ")
    
    get_league_information(url=url, league_id=league_id)
    get_players(url=url)
    get_state(url=url)
    get_league_rosters(url=url, league_id=league_id)
    get_users(url=url, league_id=league_id)
    get_trending_players(url=url)
    get_player_statistics(url=url)
    get_matchups(url=url, league_id=league_id)
    get_weekly_player_statistics(url=url, league_id=league_id)


def get_players(url:str):
    """
    This functions upserts all current NBA players in the Sleeper database to supabase
    :param url: api endpoint for getting all active players in Sleeper NBA
    :return: None
    """
    resp = requests.get(url=url+"players/nba")
    resp.raise_for_status()
    payload = resp.json()
    rows = transform_players_payload(payload)
    upsert_rows(rows, "players")

def get_state(url: str):
    resp = requests.get(url=url + "state/nba")
    resp.raise_for_status()
    payload = resp.json()
    rows = transform_league_state(payload)
    upsert_rows(rows, "league_state")

def get_league_information(url:str, league_id: str):
    resp = requests.get(url=url + f"league/{league_id}")
    resp.raise_for_status()
    payload = resp.json()
    rows = transform_league_information(payload)
    upsert_rows(rows, "league_information")

def get_league_rosters(url: str, league_id: str):
    resp = requests.get(url=url + f"league/{league_id}/rosters")
    resp.raise_for_status()
    payload = resp.json()
    rows = transform_league_rosters(payload)
    upsert_rows(rows, "league_rosters")

def get_users(url: str, league_id: str):
    resp = requests.get(url=url + f"league/{league_id}/users")
    resp.raise_for_status()
    payload = resp.json()
    rows = transform_league_users(payload, league_id)
    upsert_rows(rows, "league_users")

def get_trending_players(url: str):
    resp = requests.get(url=url + "players/nfl/trending/add")
    resp.raise_for_status()
    payload = resp.json()
    rows = transform_trending_players(payload)
    upsert_rows(rows, "trending_players")

def get_player_statistics(url: str):
    resp = requests.get(url=url + "stats/nba/regular/2025")
    resp.raise_for_status()
    payload = resp.json()
    rows = transform_player_statistics(payload)
    upsert_rows(rows, "aggregated_player_statistics")

def get_weekly_player_statistics(url: str, league_id: str):
    league_state = requests.get(url=url + "state/nba").json()
    current_week = league_state.get("week")
    season = league_state.get("season")
    resp = requests.get(url=url + f"stats/nba/regular/2025/{current_week}")
    payload = resp.json()
    rows = transform_weekly_player_statistics(payload, league_id, season, current_week)
    upsert_rows(rows, "weekly_player_statistics")

def get_matchups(url: str, league_id:str):
    week = 13
    resp = requests.get(url=url + f"league/{league_id}/matchups/{week}")
    resp.raise_for_status()
    payload = resp.json()
    rows = transform_matchups(payload, league_id)
    upsert_rows(rows, "matchups")

def transform_players_payload(payload: Dict[str, Dict[str, Any]]):
    """
    Transform the raw players dict (keyed by player_id) into a flat list of row dicts
    suitable for inserting into a relational table (e.g., Supabase).

    Expected input shape (per player_id):
      {
        "first_name": str,
        "last_name": str,
        "full_name": str,
        "player_id": str,
        "status": str,
        "team": str or None,
        "team_abbr": str or None,
        "position": str,
        "fantasy_positions": list[str],
        "age": int or None,
        "birth_date": "YYYY-MM-DD" or None,
        "height": str or None,
        "weight": str or None,
        "years_exp": int or None,
        "college": str or None,
        "sport": str,
        "metadata": {"channel_id": str} or {},
        ...
      }
    """
    rows = []

    for pid, p in payload.items():
        # Some fields may be missing; use .get with defaults
        fantasy_positions = p.get("fantasy_positions") or []
        metadata = p.get("metadata") or {}

        row = {
            "player_id": p.get("player_id") or pid,
            "first_name": p.get("first_name"),
            "last_name": p.get("last_name"),
            "full_name": p.get("full_name"),
            "status": p.get("status"),
            "team": p.get("team"),
            "team_abbr": p.get("team_abbr"),
            "position": p.get("position"),
            "fantasy_positions": fantasy_positions,                   # keep as array
            "primary_fantasy_position": fantasy_positions[0] if fantasy_positions else None,
            "age": p.get("age"),
            "birth_date": p.get("birth_date"),
            "height_inches": p.get("height"),                         # still string; cast if you prefer int
            "weight_lbs": p.get("weight"),
            "years_exp": p.get("years_exp"),
            "college": (p.get("college") or "").strip() or None,
            "sport": p.get("sport"),
            "injury_status": p.get("injury_status"),
            "injury_body_part": p.get("injury_body_part"),
            "injury_notes": p.get("injury_notes"),
            "injury_start_date": p.get("injury_start_date"),
            "active": p.get("active"),
            "depth_chart_position": p.get("depth_chart_position"),
            "depth_chart_order": p.get("depth_chart_order"),
            "hashtag": p.get("hashtag"),
            "team_changed_at": p.get("team_changed_at"),
            "news_updated": p.get("news_updated"),
            "channel_id": metadata.get("channel_id"),
        }

        rows.append(row)

    return rows

def transform_league_state(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    raw example:
    {
      "week": 2,
      "season_type": "regular",
      "season_start_date": "2020-09-10",
      "season": "2020",
      "previous_season": "2019",
      "leg": 2,
      "league_season": "2021",
      "league_create_season": "2021",
      "display_week": 3
    }
    """
    row = {
        "season": raw.get("season"),
        "week": raw.get("week"),
        "season_type": raw.get("season_type"),
        "season_start_date": raw.get("season_start_date"),
        "previous_season": raw.get("previous_season"),
        "leg": raw.get("leg"),
        "league_season": raw.get("league_season"),
        "league_create_season": raw.get("league_create_season"),
        "display_week": raw.get("display_week"),
    }

    return [row]

def transform_league_information(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    raw: single league JSON object, e.g.:
         {
           "total_rosters": 12,
           "status": "in_season",
           "sport": "nfl",
           "settings": {...},
           "season_type": "regular",
           "season": "2018",
           "scoring_settings": {...},
           "roster_positions": [...],
           "previous_league_id": "1989...",
           "name": "Sleeperbot Dynasty",
           "league_id": "2896...",
           "draft_id": "2896...",
           "avatar": "efaefa..."
         }
    returns: [row_dict] ready for upsert
    """
    row = {
        "league_id": raw.get("league_id"),
        "name": raw.get("name"),
        "status": raw.get("status"),
        "sport": raw.get("sport"),
        "season_type": raw.get("season_type"),
        "season": raw.get("season"),

        "total_rosters": raw.get("total_rosters"),
        "draft_id": raw.get("draft_id"),
        "previous_league_id": raw.get("previous_league_id"),
        "avatar": raw.get("avatar"),

        # nested / array fields as jsonb
        "settings": raw.get("settings") or {},
        "scoring_settings": raw.get("scoring_settings") or {},
        "roster_positions": raw.get("roster_positions") or [],
    }

    return [row]

def transform_league_rosters(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    raw: the JSON-decoded response from the league rosters API,
         e.g. a list of dicts like in your example.
    returns: list of row dicts suitable for supabase.table("league_rosters").upsert(...)
    """
    rows: List[Dict[str, Any]] = []

    for roster in raw:
        settings = roster.get("settings", {}) or {}

        row = {
            "league_id": roster.get("league_id"),
            "roster_id": roster.get("roster_id"),
            "owner_id": roster.get("owner_id"),

            # arrays stored as jsonb in Postgres
            "starters": roster.get("starters", []),
            "players": roster.get("players", []),
            "reserve": roster.get("reserve", []),

            # flattened settings
            "wins": settings.get("wins"),
            "losses": settings.get("losses"),
            "ties": settings.get("ties"),
            "waiver_position": settings.get("waiver_position"),
            "waiver_budget_used": settings.get("waiver_budget_used"),
            "total_moves": settings.get("total_moves"),
            "fpts": settings.get("fpts"),
            "fpts_decimal": settings.get("fpts_decimal"),
            "fpts_against": settings.get("fpts_against"),
            "fpts_against_decimal": settings.get("fpts_against_decimal"),
        }

        rows.append(row)

    return rows

def transform_league_users(raw: List[Dict[str, Any]], league_id: str) -> List[Dict[str, Any]]:
    """
    raw: list of user objects like:
         {
           "user_id": "<user_id>",
           "username": "<username>",
           "display_name": "<display_name>",
           "avatar": "1233456789",
           "metadata": {
             "team_name": "Dezpacito"
           },
           "is_owner": true
         }
    league_id: league identifier you already know from context.
    """
    rows: List[Dict[str, Any]] = []

    for u in raw:
        row = {
            "league_id": league_id,
            "user_id": u.get("user_id"),
            "username": u.get("username"),
            "display_name": u.get("display_name"),
            "avatar": u.get("avatar"),
            "metadata": u.get("metadata") or {},
            "is_owner": bool(u.get("is_owner")),
        }
        rows.append(row)

    return rows

def transform_trending_players(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    raw example:
    [
      { "player_id": "1111", "count": 45 },
      ...
    ]
    """
    rows: List[Dict[str, Any]] = []

    for item in raw:
        row = {
            "player_id": item.get("player_id"),
            "add_count": item.get("count"),
        }
        rows.append(row)

    return rows

def transform_player_statistics(raw: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    raw example:
    {
      "1658": {
        "reb": 389.0,
        "plus_minus": 0.0,
        "bonus_pt_50p": 1.0,
        "pos_rank_std": 1.0,
        "gp": 32.0,
        "blk_stl": 69.0,
        "fga": 560.0,
        "oreb": 97.0,
        "fgmi": 221.0,
        "pts": 948.0,
        "rank_std": 1.0,
        "tpa": 154.0,
        "dreb": 292.0,
        "fgm": 339.0,
        "pts_std": 1336.5,
        "bonus_ast_15p": 1.0,
        "pts_reb": 1337.0,
        "ff": 2.0,
        "tf": 0.0,
        "dd": 28.0,
        "ftmi": 35.0,
        "stl": 44.0,
        "reb_ast": 740.0,
        "fta": 238.0,
        "to": 113.0,
        "gs": 32.0,
        "ast": 351.0,
        "blk": 25.0,
        "pf": 89.0,
        "sp": 66360.0,
        "tpm": 67.0,
        "bonus_pt_40p": 1.0,
        "bonus_reb_20p": 1.0,
        "pts_reb_ast": 1688.0,
        "td": 16.0,
        "pts_std_dfs": 2035.3,
        "tpmi": 87.0,
        "pts_ast": 1299.0,
        "ftm": 203.0
      },
      ...
    }
    """
    rows: List[Dict[str, Any]] = []

    for player_id, stats in raw.items():
        row: Dict[str, Any] = {
            "player_id": player_id,
            "reb":            stats.get("reb"),
            "plus_minus":     stats.get("plus_minus"),
            "bonus_pt_50p":   stats.get("bonus_pt_50p"),
            "pos_rank_std":   stats.get("pos_rank_std"),
            "gp":             stats.get("gp"),
            "blk_stl":        stats.get("blk_stl"),
            "fga":            stats.get("fga"),
            "oreb":           stats.get("oreb"),
            "fgmi":           stats.get("fgmi"),
            "pts":            stats.get("pts"),
            "rank_std":       stats.get("rank_std"),
            "tpa":            stats.get("tpa"),
            "dreb":           stats.get("dreb"),
            "fgm":            stats.get("fgm"),
            "pts_std":        stats.get("pts_std"),
            "bonus_ast_15p":  stats.get("bonus_ast_15p"),
            "pts_reb":        stats.get("pts_reb"),
            "ff":             stats.get("ff"),
            "tf":             stats.get("tf"),
            "dd":             stats.get("dd"),
            "ftmi":           stats.get("ftmi"),
            "stl":            stats.get("stl"),
            "reb_ast":        stats.get("reb_ast"),
            "fta":            stats.get("fta"),
            "turnovers":      stats.get("to"),
            "gs":             stats.get("gs"),
            "ast":            stats.get("ast"),
            "blk":            stats.get("blk"),
            "pf":             stats.get("pf"),
            "sp":             stats.get("sp"),
            "tpm":            stats.get("tpm"),
            "bonus_pt_40p":   stats.get("bonus_pt_40p"),
            "bonus_reb_20p":  stats.get("bonus_reb_20p"),
            "pts_reb_ast":    stats.get("pts_reb_ast"),
            "td":             stats.get("td"),
            "pts_std_dfs":    stats.get("pts_std_dfs"),
            "tpmi":           stats.get("tpmi"),
            "pts_ast":        stats.get("pts_ast"),
            "ftm":            stats.get("ftm"),
        }
        rows.append(row)

    return rows

def transform_weekly_player_statistics(raw: Dict[str, Dict[str, Any]],league_id: str,season: str,week: int) -> List[Dict[str, Any]]:
    """
    raw: dict keyed by player_id with per-player weekly stats.
         Example entry (keys vary by player):
         {
           "2125": {
             "reb": 5.0,
             "plus_minus": 20.0,
             "q4_pts": 2.0,
             "h1_reb": 3.0,
             "h2_pts": 7.0,
             "tpa": 4.0,
             "pts": 19.0,
             "pts_reb_ast": 27.0,
             "pts_std_dfs": 30.4,
             ...
           },
           ...
         }
    league_id: string league identifier.
    season: string season, e.g. "2024".
    week: integer week.
    """
    rows: List[Dict[str, Any]] = []

    for player_id, stats in raw.items():
        # Helper to read a stat safely and default to None (NULL in Postgres)
        def s(key: str) -> Optional[Any]:
            return stats.get(key) if stats is not None else None

        row: Dict[str, Any] = {
            "league_id": league_id,
            "season": season,
            "week": week,
            "player_id": player_id,

            # Explicit per-stat features – make sure these match your table columns
            "reb": s("reb"),
            "plus_minus": s("plus_minus"),
            "bonus_pt_50p": s("bonus_pt_50p"),
            "pos_rank_std": s("pos_rank_std"),
            "gp": s("gp"),
            "blk_stl": s("blk_stl"),
            "fga": s("fga"),
            "oreb": s("oreb"),  #removed gp
            "fgmi": s("fgmi"),
            "pts": s("pts"),
            "rank_std": s("rank_std"),
            "tpa": s("tpa"),
            "dreb": s("dreb"),
            "fgm": s("fgm"),
            "pts_std": s("pts_std"),
            "bonus_ast_15p": s("bonus_ast_15p"),
            "pts_reb": s("pts_reb"),
            "ff": s("ff"),
            "tf": s("tf"),
            "dd": s("dd"),
            "ftmi": s("ftmi"),
            "stl": s("stl"),
            "reb_ast": s("reb_ast"),
            "fta": s("fta"),
            "turnovers": s("to"),  # JSON key "to" -> DB column "turnovers"
            "gs": s("gs"),
            "ast": s("ast"),
            "blk": s("blk"),
            "pf": s("pf"),
            "sp": s("sp"),
            "tpm": s("tpm"),
            "bonus_pt_40p": s("bonus_pt_40p"),
            "bonus_reb_20p": s("bonus_reb_20p"),
            "pts_reb_ast": s("pts_reb_ast"),
            "td": s("td"),
            "pts_std_dfs": s("pts_std_dfs"),
            "tpmi": s("tpmi"),
            "pts_ast": s("pts_ast"),
            "ftm": s("ftm"),

            # Quarter/half split stats from weekly JSON sample
            "q1_pts": s("q1_pts"),
            "q2_pts": s("q2_pts"),
            "q3_pts": s("q3_pts"),
            "q4_pts": s("q4_pts"),
            "q1_reb": s("q1_reb"),
            "q2_reb": s("q2_reb"),
            "q3_reb": s("q3_reb"),
            "q4_reb": s("q4_reb"),
            "q1_ast": s("q1_ast"),
            "q2_ast": s("q2_ast"),
            "q3_ast": s("q3_ast"),
            "q4_ast": s("q4_ast"),
            "h1_pts": s("h1_pts"),
            "h2_pts": s("h2_pts"),
            "h1_reb": s("h1_reb"),
            "h2_reb": s("h2_reb"),
            "h1_ast": s("h1_ast"),
            "h2_ast": s("h2_ast"),
        }

        rows.append(row)

    return rows

def transform_matchups(raw: List[Dict[str, Any]], league_id: str) -> List[Dict[str, Any]]:
    """
    raw: list of matchup objects like:
         [
           {
             "starters": ["421", "4035", ...],
             "roster_id": 1,
             "players": ["1352", "1387", ...],
             "matchup_id": 2,
             "points": 20.0,
             "custom_points": null
           },
           ...
         ]
    league_id: league identifier from context
    """
    rows: List[Dict[str, Any]] = []

    for matchup in raw:
        row = {
            "league_id": league_id,
            "roster_id": matchup.get("roster_id"),
            "matchup_id": matchup.get("matchup_id"),

            "starters": matchup.get("starters", []),
            "players": matchup.get("players", []),
            "points": matchup.get("points"),
            "custom_points": matchup.get("custom_points"),
        }
        rows.append(row)

    return rows

def upsert_rows(rows, table_name):
    logging.info("Job started")

    if not SUPABASE_URL or not SUPABASE_KEY:
        logging.error("Supabase key not set")
        sys.exit(1)

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    res = supabase.table(table_name).upsert(rows).execute()

    logging.info("Upserted %d rows", len(rows))

    logging.info(f"Finished upserting for {table_name}")
    time.sleep(5)

if __name__ == "__main__":
    main()