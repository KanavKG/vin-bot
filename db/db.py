"""
Poker Statistics Database
Stores historical poker session data and player aliases
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class PokerStatsDB:
    """Database for tracking poker statistics across sessions"""
    
    def __init__(self, db_path: str = "poker_stats.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
    
    def _create_tables(self):
        """Create database tables if they don't exist"""
        cursor = self.conn.cursor()
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_message_id TEXT,
                session_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_hands INTEGER,
                total_players INTEGER,
                uploaded_by TEXT,
                filename TEXT
            )
        """)
        
        # Player sessions table (one row per player per session)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                player_name TEXT NOT NULL,
                hands_played INTEGER,
                vpip REAL,
                pfr REAL,
                aggression_factor REAL,
                wtsd REAL,
                buy_ins REAL,
                cash_outs REAL,
                profit REAL,
                hands_won INTEGER,
                bets INTEGER,
                raises INTEGER,
                calls INTEGER,
                checks INTEGER,
                folds INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        
        # Player aliases table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL,
                alias TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(alias)
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_player_sessions_name 
            ON player_sessions(player_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_player_aliases_canonical 
            ON player_aliases(canonical_name)
        """)
        
        self.conn.commit()
    
    def add_session(self, parser, discord_message_id: str = None, 
                   uploaded_by: str = None, filename: str = None) -> int:
        """
        Add a poker session to the database
        
        Args:
            parser: PokerLogParser instance with parsed data
            discord_message_id: Discord message ID (optional)
            uploaded_by: Username who uploaded (optional)
            filename: Original filename (optional)
            
        Returns:
            session_id of the newly created session
        """
        cursor = self.conn.cursor()
        
        # Insert session
        cursor.execute("""
            INSERT INTO sessions (discord_message_id, total_hands, total_players, 
                                 uploaded_by, filename)
            VALUES (?, ?, ?, ?, ?)
        """, (
            discord_message_id,
            len(parser.hands),
            len(parser.player_stats),
            uploaded_by,
            filename
        ))
        
        session_id = cursor.lastrowid
        
        # Insert player stats for this session
        for player_name, stats in parser.player_stats.items():
            # Extract just the nickname (before @)
            clean_name = player_name.split('@')[0].strip()
            
            cursor.execute("""
                INSERT INTO player_sessions (
                    session_id, player_name, hands_played, vpip, pfr,
                    aggression_factor, wtsd, buy_ins, cash_outs, profit,
                    hands_won, bets, raises, calls, checks, folds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                clean_name,  # Use clean nickname instead of full "name @ ID"
                stats.hands_played,
                stats.vpip_percentage(),
                stats.pfr_percentage(),
                stats.aggression_factor(),
                stats.wtsd_percentage(),
                sum(stats.buy_ins),
                sum(stats.cash_outs),
                stats.actual_profit(),
                stats.hands_won,
                stats.bets,
                stats.raises,
                stats.calls,
                stats.checks,
                stats.folds
            ))
        
        self.conn.commit()
        return session_id
    
    def get_player_history(self, player_name: str) -> Dict:
        """
        Get historical stats for a player (including aliased names)
        
        Args:
            player_name: Player nickname (e.g., 'dhruv', 'Kaushik')
            
        Returns:
            Dictionary with aggregated stats and session history
        """
        # Resolve aliases (supports exact match or alias lookup)
        all_names = self.get_all_player_names(player_name)
        
        cursor = self.conn.cursor()
        
        # Get all sessions for this player
        placeholders = ','.join('?' * len(all_names))
        cursor.execute(f"""
            SELECT 
                ps.*,
                s.session_date,
                s.total_hands as session_total_hands,
                s.filename
            FROM player_sessions ps
            JOIN sessions s ON ps.session_id = s.session_id
            WHERE ps.player_name IN ({placeholders})
            ORDER BY s.session_date DESC
        """, all_names)
        
        sessions = cursor.fetchall()
        
        if not sessions:
            return None
        
        # Aggregate stats
        total_sessions = len(sessions)
        total_hands = sum(s['hands_played'] for s in sessions)
        total_profit = sum(s['profit'] for s in sessions)
        total_buy_ins = sum(s['buy_ins'] for s in sessions)
        total_cash_outs = sum(s['cash_outs'] for s in sessions)
        
        # Weighted averages for percentages
        if total_hands > 0:
            vpip_weighted = sum(s['vpip'] * s['hands_played'] for s in sessions) / total_hands
            pfr_weighted = sum(s['pfr'] * s['hands_played'] for s in sessions) / total_hands
            wtsd_weighted = sum(s['wtsd'] * s['hands_played'] for s in sessions) / total_hands
        else:
            vpip_weighted = pfr_weighted = wtsd_weighted = 0.0
        
        # Aggression factor (total bets+raises / total calls)
        total_bets = sum(s['bets'] for s in sessions)
        total_raises = sum(s['raises'] for s in sessions)
        total_calls = sum(s['calls'] for s in sessions)
        total_checks = sum(s['checks'] for s in sessions)
        total_folds = sum(s['folds'] for s in sessions)
        total_hands_won = sum(s['hands_won'] for s in sessions)
        
        if total_calls > 0:
            aggression_factor = (total_bets + total_raises) / total_calls
        else:
            aggression_factor = float(total_bets + total_raises) if (total_bets + total_raises) > 0 else 0.0
        
        return {
            'canonical_name': all_names[0] if all_names else player_name,
            'all_aliases': all_names,
            'total_sessions': total_sessions,
            'total_hands': total_hands,
            'total_profit': total_profit,
            'total_buy_ins': total_buy_ins,
            'total_cash_outs': total_cash_outs,
            'vpip': vpip_weighted,
            'pfr': pfr_weighted,
            'aggression_factor': aggression_factor,
            'wtsd': wtsd_weighted,
            'hands_won': total_hands_won,
            'win_rate': (total_hands_won / total_hands * 100) if total_hands > 0 else 0,
            'actions': {
                'bets': total_bets,
                'raises': total_raises,
                'calls': total_calls,
                'checks': total_checks,
                'folds': total_folds
            },
            'sessions': [dict(s) for s in sessions]
        }
    
    def add_alias(self, canonical_name: str, alias: str) -> bool:
        """
        Add an alias for a player
        
        Args:
            canonical_name: The main/canonical player name
            alias: The alias to link to the canonical name
            
        Returns:
            True if successful, False if alias already exists
        """
        cursor = self.conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO player_aliases (canonical_name, alias)
                VALUES (?, ?)
            """, (canonical_name, alias))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Alias already exists
            return False
    
    def get_all_player_names(self, player_name: str) -> List[str]:
        """
        Get all names (canonical + aliases) for a player
        
        Args:
            player_name: Any name or alias
            
        Returns:
            List of all associated names
        """
        cursor = self.conn.cursor()
        
        # Check if this is an alias
        cursor.execute("""
            SELECT canonical_name FROM player_aliases WHERE alias = ?
        """, (player_name,))
        result = cursor.fetchone()
        
        if result:
            canonical = result['canonical_name']
        else:
            # This might be the canonical name, or a name with no aliases
            canonical = player_name
        
        # Get all aliases for the canonical name
        cursor.execute("""
            SELECT alias FROM player_aliases WHERE canonical_name = ?
        """, (canonical,))
        aliases = [row['alias'] for row in cursor.fetchall()]
        
        # Return canonical + all aliases
        return [canonical] + aliases
    
    def merge_players(self, primary_name: str, secondary_name: str) -> bool:
        """
        Merge two player identities by making secondary an alias of primary
        
        Args:
            primary_name: The name to keep
            secondary_name: The name to alias to primary
            
        Returns:
            True if successful
        """
        # Get all names for both players
        primary_names = self.get_all_player_names(primary_name)
        secondary_names = self.get_all_player_names(secondary_name)
        
        # The primary canonical is the first in the list
        primary_canonical = primary_names[0]
        
        cursor = self.conn.cursor()
        
        # Add all secondary names as aliases to primary
        for name in secondary_names:
            if name not in primary_names:
                try:
                    cursor.execute("""
                        INSERT INTO player_aliases (canonical_name, alias)
                        VALUES (?, ?)
                    """, (primary_canonical, name))
                except sqlite3.IntegrityError:
                    # Already exists, skip
                    pass
        
        # Update any existing aliases pointing to secondary to point to primary
        for name in secondary_names:
            cursor.execute("""
                UPDATE player_aliases 
                SET canonical_name = ?
                WHERE canonical_name = ?
            """, (primary_canonical, name))
        
        self.conn.commit()
        return True
    
    def get_leaderboard(self, stat: str = 'profit', limit: int = 10) -> List[Dict]:
        """
        Get top players by a specific stat
        
        Args:
            stat: 'profit', 'hands', 'vpip', 'pfr', 'aggression_factor'
            limit: Number of players to return
            
        Returns:
            List of player stats dictionaries
        """
        cursor = self.conn.cursor()
        
        # Get all unique players
        cursor.execute("""
            SELECT DISTINCT player_name FROM player_sessions
        """)
        all_players = [row['player_name'] for row in cursor.fetchall()]
        
        # Get canonical names (resolve duplicates via aliases)
        canonical_players = set()
        for player in all_players:
            canonical = self.get_all_player_names(player)[0]
            canonical_players.add(canonical)
        
        # Get history for each canonical player
        leaderboard = []
        for player in canonical_players:
            history = self.get_player_history(player)
            if history:
                leaderboard.append(history)
        
        # Sort by requested stat
        stat_map = {
            'profit': 'total_profit',
            'hands': 'total_hands',
            'vpip': 'vpip',
            'pfr': 'pfr',
            'aggression_factor': 'aggression_factor'
        }
        
        sort_key = stat_map.get(stat, 'total_profit')
        leaderboard.sort(key=lambda x: x[sort_key], reverse=True)
        
        return leaderboard[:limit]
    
    def close(self):
        """Close database connection"""
        self.conn.close()


# Convenience context manager
class PokerStatsDBContext:
    """Context manager for PokerStatsDB"""
    
    def __init__(self, db_path: str = "poker_stats.db"):
        self.db_path = db_path
        self.db = None
    
    def __enter__(self):
        self.db = PokerStatsDB(self.db_path)
        return self.db
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.db:
            self.db.close()