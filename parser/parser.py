"""
Poker Now Log Parser
Parses poker hand histories and generates per-player statistics
"""

import csv
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class PlayerStats:
    """Statistics for a single player"""
    name: str
    hands_played: int = 0
    vpip_count: int = 0  # Voluntarily Put money In Pot
    pfr_count: int = 0   # Pre-Flop Raise
    three_bet_count: int = 0
    hands_won: int = 0
    hands_shown: int = 0
    folds_preflop: int = 0
    folds_postflop: int = 0
    
    # Buy-ins and cash-outs (ACCURATE profit tracking)
    buy_ins: List[float] = field(default_factory=list)
    cash_outs: List[float] = field(default_factory=list)
    
    # Positional stats
    button_hands: int = 0
    bb_hands: int = 0
    sb_hands: int = 0
    
    # Aggression
    bets: int = 0
    raises: int = 0
    calls: int = 0
    checks: int = 0
    folds: int = 0
    
    # Street-specific
    preflop_actions: List[str] = field(default_factory=list)
    flop_actions: List[str] = field(default_factory=list)
    turn_actions: List[str] = field(default_factory=list)
    river_actions: List[str] = field(default_factory=list)
    
    def vpip_percentage(self) -> float:
        """VPIP = % of hands where player voluntarily put money in"""
        if self.hands_played == 0:
            return 0.0
        return (self.vpip_count / self.hands_played) * 100
    
    def pfr_percentage(self) -> float:
        """PFR = % of hands where player raised preflop"""
        if self.hands_played == 0:
            return 0.0
        return (self.pfr_count / self.hands_played) * 100
    
    def aggression_factor(self) -> float:
        """AF = (Bets + Raises) / Calls"""
        if self.calls == 0:
            return float(self.bets + self.raises) if (self.bets + self.raises) > 0 else 0.0
        return (self.bets + self.raises) / self.calls
    
    def actual_profit(self) -> float:
        """Actual profit/loss based on buy-ins and cash-outs"""
        total_bought_in = sum(self.buy_ins)
        total_cashed_out = sum(self.cash_outs)
        return total_cashed_out - total_bought_in
    
    def wtsd_percentage(self) -> float:
        """Went To ShowDown %"""
        if self.hands_played == 0:
            return 0.0
        return (self.hands_shown / self.hands_played) * 100


@dataclass
class Hand:
    """Represents a single poker hand"""
    hand_number: int
    hand_id: str
    dealer: str
    players: List[str] = field(default_factory=list)
    stacks: Dict[str, float] = field(default_factory=dict)
    actions: List[Tuple[str, str, str]] = field(default_factory=list)  # (player, action, street)
    winners: List[Tuple[str, float]] = field(default_factory=list)
    showdowns: Dict[str, str] = field(default_factory=dict)  # player -> cards shown


class PokerLogParser:
    """Parse Poker Now CSV logs"""
    
    def __init__(self, csv_file_path: str):
        self.csv_file_path = csv_file_path
        self.hands: List[Hand] = []
        self.player_stats: Dict[str, PlayerStats] = {}
        self.sit_backs: Dict[str, float] = {}  # Track sit-back amounts to avoid double-counting
        self.final_stacks: Dict[str, float] = {}  # Track final stack amounts for players still in game
        self.captured_final_stacks = False  # Flag to capture only the LAST game state
        
    def extract_player_name(self, text: str) -> Optional[str]:
        """Extract player name from quoted text like 'Player @ ABC123'"""
        match = re.search(r'\"([^"]+@[^"]+)\"', text)
        if match:
            return match.group(1)
        return None
    
    def extract_amount(self, text: str) -> Optional[float]:
        """Extract monetary amount from text"""
        # Look for patterns like "stack of 50.00" or "calls 5.50" or "raises to 10"
        # Try specific patterns first to avoid matching player IDs
        patterns = [
            r'stack of (\d+\.?\d*)',  # "stack of 50.00"
            r'(?:calls|bets|raises to|collected) (\d+\.?\d*)',  # action amounts
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        
        # Fallback: just find any number
        match = re.search(r'(\d+\.?\d*)', text)
        if match:
            return float(match.group(1))
        return None
    
    def parse_log(self):
        """Parse the entire log file"""
        with open(self.csv_file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            current_hand = None
            current_street = "preflop"
            
            # Read all rows
            rows = list(reader)
            
            # Capture final stacks from the FIRST row (newest, before reversing)
            # This is the true end state of the game
            for row in rows:
                if 'Player stacks:' in row['entry']:
                    players = re.findall(r'#\d+\s+"([^"]+)"\s+\(([^)]+)\)', row['entry'])
                    for player_name, stack in players:
                        self.final_stacks[player_name] = float(stack)
                    break  # Only capture the first (most recent) Player stacks entry
            
            # Now reverse for chronological processing
            rows.reverse()
            
            for row in rows:
                entry = row['entry']
                
                # Starting a new hand
                if '-- starting hand' in entry:
                    # Process previous hand if exists
                    if current_hand and current_hand.players:
                        self._process_hand(current_hand)
                    
                    match = re.search(r'hand #(\d+) \(id: ([^)]+)\)', entry)
                    if match:
                        hand_num = int(match.group(1))
                        hand_id = match.group(2)
                        
                        # Extract dealer
                        dealer_match = re.search(r'dealer: "([^"]+)"', entry)
                        dealer = dealer_match.group(1) if dealer_match else "Unknown"
                        
                        current_hand = Hand(
                            hand_number=hand_num,
                            hand_id=hand_id,
                            dealer=dealer
                        )
                        current_street = "preflop"
                        self.hands.append(current_hand)
                
                # Player stacks at start of hand
                elif 'Player stacks:' in entry and current_hand:
                    # Parse player stacks
                    # Format after CSV parsing: #1 "Player @ ID" (stack)
                    players = re.findall(r'#\d+\s+"([^"]+)"\s+\(([^)]+)\)', entry)
                    for player_name, stack in players:
                        current_hand.players.append(player_name)
                        current_hand.stacks[player_name] = float(stack)
                        
                        # Initialize player stats if not exists
                        if player_name not in self.player_stats:
                            self.player_stats[player_name] = PlayerStats(name=player_name)
                
                # Street changes
                elif 'Flop:' in entry:
                    current_street = "flop"
                elif 'Turn:' in entry:
                    current_street = "turn"
                elif 'River:' in entry:
                    current_street = "river"
                
                # Player actions and events
                else:
                    player_name = self.extract_player_name(entry)
                    if player_name:
                        # Initialize player if needed
                        if player_name not in self.player_stats:
                            self.player_stats[player_name] = PlayerStats(name=player_name)
                        
                        # Admin updated stack (chip additions during play)
                        if 'The admin updated the player' in entry and 'stack from' in entry:
                            # Format: "stack from X to Y." (may have trailing period)
                            match = re.search(r'stack from ([\d.]+) to ([\d.]+)', entry)
                            if match:
                                old_stack = float(match.group(1))
                                new_stack = float(match.group(2).rstrip('.'))
                                chips_added = new_stack - old_stack
                                if chips_added > 0:
                                    self.player_stats[player_name].buy_ins.append(chips_added)
                        
                        # Sit back (returning from sitting out)
                        elif ' sit back with the stack of ' in entry:
                            amount = self.extract_amount(entry)
                            if amount is not None:
                                self.sit_backs[player_name] = amount
                        
                        # Buy-ins (joined game) - THIS IS THE ONLY BUY-IN EVENT
                        elif ' joined the game with a stack of ' in entry:
                            amount = self.extract_amount(entry)
                            if amount:
                                # Check if this is a sit-back return (same amount as recent sit-back)
                                if player_name in self.sit_backs and abs(self.sit_backs[player_name] - amount) < 0.01:
                                    # This is returning from sit-out, not a new buy-in
                                    del self.sit_backs[player_name]
                                else:
                                    # This is a real buy-in
                                    self.player_stats[player_name].buy_ins.append(amount)
                        
                        # Cash-outs (quit game)
                        elif ' quits the game with a stack of ' in entry:
                            amount = self.extract_amount(entry)
                            if amount is not None:
                                self.player_stats[player_name].cash_outs.append(amount)
                        
                        # Actions only tracked if in a current hand
                        elif current_hand:
                            # Calls
                            if ' calls ' in entry:
                                amount = self.extract_amount(entry)
                                current_hand.actions.append((player_name, f"call {amount}", current_street))
                            
                            # Raises
                            elif ' raises to ' in entry:
                                amount = self.extract_amount(entry)
                                current_hand.actions.append((player_name, f"raise {amount}", current_street))
                            
                            # Bets
                            elif ' bets ' in entry:
                                amount = self.extract_amount(entry)
                                current_hand.actions.append((player_name, f"bet {amount}", current_street))
                            
                            # Folds
                            elif ' folds' in entry:
                                current_hand.actions.append((player_name, "fold", current_street))
                            
                            # Checks
                            elif ' checks' in entry:
                                current_hand.actions.append((player_name, "check", current_street))
                            
                            # Shows cards
                            elif ' shows a ' in entry:
                                cards_match = re.search(r'shows a ([^.]+)', entry)
                                if cards_match:
                                    current_hand.showdowns[player_name] = cards_match.group(1)
                            
                            # Collected pot
                            elif ' collected ' in entry:
                                amount = self.extract_amount(entry)
                                if amount:
                                    current_hand.winners.append((player_name, amount))
            
            # Process final hand
            if current_hand and current_hand.players:
                self._process_hand(current_hand)
            
            # Add final stacks as cash-outs for players who are still in the game
            # Final stacks only contains players who were IN the last hand
            for player_name, final_stack in self.final_stacks.items():
                if player_name in self.player_stats:
                    # If they have cash-outs but are in final stacks, replace with final stack
                    # (they quit and rejoined, or the quit amount is outdated)
                    if self.player_stats[player_name].cash_outs:
                        # Replace the last cash-out with final stack (they're still playing)
                        self.player_stats[player_name].cash_outs[-1] = final_stack
                    else:
                        # No cash-out recorded, add final stack
                        self.player_stats[player_name].cash_outs.append(final_stack)
    
    def _process_hand(self, hand: Hand):
        """Process a completed hand and update player statistics"""
        # Track which players were dealt in
        for player in hand.players:
            stats = self.player_stats[player]
            stats.hands_played += 1
            
            # Check if player is dealer (button)
            if player == hand.dealer:
                stats.button_hands += 1
        
        # Track VPIP and PFR
        preflop_actions_by_player = defaultdict(list)
        for player, action, street in hand.actions:
            if street == "preflop":
                preflop_actions_by_player[player].append(action)
        
        for player in hand.players:
            stats = self.player_stats[player]
            player_pf_actions = preflop_actions_by_player.get(player, [])
            
            # VPIP: voluntarily put money in (not BB)
            vpip_actions = [a for a in player_pf_actions if any(x in a for x in ['call', 'raise', 'bet'])]
            if vpip_actions:
                stats.vpip_count += 1
            
            # PFR: raised preflop
            if any('raise' in a for a in player_pf_actions):
                stats.pfr_count += 1
            
            # Preflop fold
            if any('fold' in a for a in player_pf_actions):
                stats.folds_preflop += 1
        
        # Track all actions
        for player, action, street in hand.actions:
            stats = self.player_stats[player]
            
            # Count action types
            if 'call' in action:
                stats.calls += 1
            elif 'raise' in action:
                stats.raises += 1
            elif 'bet' in action:
                stats.bets += 1
            elif 'check' in action:
                stats.checks += 1
            elif 'fold' in action:
                stats.folds += 1
                if street != "preflop":
                    stats.folds_postflop += 1
        
        # Track showdowns
        for player in hand.showdowns:
            if player in self.player_stats:
                self.player_stats[player].hands_shown += 1
        
        # Track wins
        for player, amount in hand.winners:
            if player in self.player_stats:
                self.player_stats[player].hands_won += 1
    
    def get_player_summary(self, player_name: str) -> Dict:
        """Get comprehensive statistics for a player"""
        if player_name not in self.player_stats:
            return {}
        
        stats = self.player_stats[player_name]
        
        return {
            "name": stats.name,
            "hands_played": stats.hands_played,
            "vpip": round(stats.vpip_percentage(), 1),
            "pfr": round(stats.pfr_percentage(), 1),
            "aggression_factor": round(stats.aggression_factor(), 2),
            "wtsd": round(stats.wtsd_percentage(), 1),
            "profit": round(stats.actual_profit(), 2),
            "total_buy_ins": round(sum(stats.buy_ins), 2),
            "total_cash_outs": round(sum(stats.cash_outs), 2),
            "buy_in_count": len(stats.buy_ins),
            "hands_won": stats.hands_won,
            "stats": {
                "bets": stats.bets,
                "raises": stats.raises,
                "calls": stats.calls,
                "checks": stats.checks,
                "folds": stats.folds,
                "folds_preflop": stats.folds_preflop,
                "folds_postflop": stats.folds_postflop,
            }
        }
    
    def get_all_players_summary(self) -> Dict[str, Dict]:
        """Get summary for all players"""
        return {
            player: self.get_player_summary(player)
            for player in self.player_stats.keys()
        }
    
    def print_player_report(self, player_name: str):
        """Print a formatted report for a player"""
        summary = self.get_player_summary(player_name)
        if not summary:
            print(f"Player {player_name} not found")
            return
        
        print(f"\n{'='*60}")
        print(f"PLAYER REPORT: {summary['name']}")
        print(f"{'='*60}")
        print(f"Hands Played: {summary['hands_played']}")
        print(f"\nKEY STATS:")
        print(f"  VPIP (Voluntarily Put In Pot): {summary['vpip']}%")
        print(f"  PFR (Pre-Flop Raise): {summary['pfr']}%")
        print(f"  Aggression Factor: {summary['aggression_factor']}")
        print(f"  WTSD (Went To Showdown): {summary['wtsd']}%")
        print(f"\nFINANCIALS:")
        print(f"  Buy-ins: ${summary['total_buy_ins']} ({summary['buy_in_count']} times)")
        print(f"  Cash-outs: ${summary['total_cash_outs']}")
        print(f"  Net Profit/Loss: ${summary['profit']}")
        print(f"  Hands Won: {summary['hands_won']}")
        print(f"\nACTIONS:")
        print(f"  Bets: {summary['stats']['bets']}")
        print(f"  Raises: {summary['stats']['raises']}")
        print(f"  Calls: {summary['stats']['calls']}")
        print(f"  Checks: {summary['stats']['checks']}")
        print(f"  Folds: {summary['stats']['folds']} (PF: {summary['stats']['folds_preflop']}, Postflop: {summary['stats']['folds_postflop']})")
        print(f"{'='*60}\n")


def main():
    """Example usage"""
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python poker_parser.py <poker_log.csv> [--json output.json]")
        sys.exit(1)
    
    log_file = sys.argv[1]
    
    print(f"Parsing poker log: {log_file}")
    parser = PokerLogParser(log_file)
    parser.parse_log()
    
    print(f"\nFound {len(parser.hands)} hands")
    print(f"Found {len(parser.player_stats)} players\n")
    
    # Check if JSON export requested
    if "--json" in sys.argv:
        json_idx = sys.argv.index("--json")
        if json_idx + 1 < len(sys.argv):
            json_file = sys.argv[json_idx + 1]
            all_summaries = parser.get_all_players_summary()
            with open(json_file, 'w') as f:
                json.dump(all_summaries, f, indent=2)
            print(f"Exported player stats to {json_file}\n")
    
    # Print all players
    all_summaries = parser.get_all_players_summary()
    for player_name in sorted(all_summaries.keys()):
        parser.print_player_report(player_name)


if __name__ == "__main__":
    main()