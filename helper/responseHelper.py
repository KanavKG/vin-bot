from typing import Any, Dict, List, Optional


class ResponseHelper:
    """Builds formatted bot responses for poker commands."""

    def build_poker_analysis_response(
        self,
        parser: Any,
        player_financials: Optional[Dict[str, float]] = None,
        use_ledger: bool = False,
    ) -> str:
        player_financials = player_financials or {}

        response = "# 🃏 Poker Session Analysis\n\n"
        if use_ledger:
            response += "✅ Using ledger file for accurate profit calculations\n\n"

        player_data = self._build_player_data(parser, player_financials, use_ledger)

        response += self._section_for_players("🏆 Winners", player_data, lambda p: p['profit'] > 0, winners=True)
        response += self._section_for_players("💸 Losers", player_data, lambda p: p['profit'] < 0)
        response += self._section_for_players("🤝 Break Even", player_data, lambda p: abs(p['profit']) < 0.01, break_even=True)

        total_hands = len(getattr(parser, 'hands', []))
        total_money_in = sum(p['total_in'] for p in player_data)
        total_money_out = sum(p['total_out'] for p in player_data)

        response += f"**Total Hands:** {total_hands}\n"
        response += f"**Total Buy-ins:** ${total_money_in:.2f}\n"
        response += f"**Total Cash-outs:** ${total_money_out:.2f}\n"

        return response

    def build_player_history_response(self, history: Dict[str, Any]) -> str:
        canonical = self._clean_name(history.get('canonical_name', 'Unknown'))
        response = f"# 📊 Historical Stats: {canonical}\n\n"

        aliases = history.get('all_aliases', [])
        if len(aliases) > 1:
            alias_list = [self._clean_name(alias) for alias in aliases if self._clean_name(alias) != canonical]
            if alias_list:
                response += f"**Also known as:** {', '.join(alias_list)}\n\n"

        response += "## Overall Performance\n```\n"
        response += f"Sessions Played:  {history.get('total_sessions', 0)}\n"
        response += f"Total Hands:      {history.get('total_hands', 0)}\n"
        response += f"Hands Won:        {history.get('hands_won', 0)} ({history.get('win_rate', 0.0):.1f}%)\n"
        response += f"Total Profit:     ${history.get('total_profit', 0.0):+.2f}\n"
        response += f"Total Buy-ins:    ${history.get('total_buy_ins', 0.0):.2f}\n"
        response += f"Total Cash-outs:  ${history.get('total_cash_outs', 0.0):.2f}\n"
        response += "```\n\n"

        response += "## Playing Style\n```\n"
        response += f"VPIP:              {history.get('vpip', 0.0):.1f}%\n"
        response += f"PFR:               {history.get('pfr', 0.0):.1f}%\n"
        response += f"3-Bet %:           {history.get('three_bet_pct', 0.0):.1f}%\n"
        response += f"Aggression Factor: {history.get('aggression_factor', 0.0):.2f}\n"
        response += f"WTSD:              {history.get('wtsd', 0.0):.1f}%\n"
        response += "```\n\n"

        response += "## Actions\n```\n"
        response += f"Bets:    {history.get('actions', {}).get('bets', 0)}\n"
        response += f"Raises:  {history.get('actions', {}).get('raises', 0)}\n"
        response += f"Calls:   {history.get('actions', {}).get('calls', 0)}\n"
        response += f"Checks:  {history.get('actions', {}).get('checks', 0)}\n"
        response += f"Folds:   {history.get('actions', {}).get('folds', 0)}\n"
        response += "```\n\n"

        response += "## Recent Sessions\n```\n"
        for session in history.get('sessions', [])[:5]:
            date = session.get('session_date', '')[:10]
            profit = session.get('profit', 0.0)
            profit_sign = '+' if profit >= 0 else ''
            response += f"{date}  Hands: {session.get('hands_played', 0):3}  P/L: {profit_sign}${profit:.2f}\n"
        response += "```"

        return response

    def build_leaderboard_response(self, leaderboard: List[Dict[str, Any]], stat: str = 'profit') -> str:
        stat_names = {
            'profit': 'Total Profit',
            'hands': 'Hands Played',
            'vpip': 'VPIP %',
            'pfr': 'PFR %',
            'aggression_factor': 'Aggression Factor'
        }
        title = stat_names.get(stat, 'Total Profit')

        response = f"# 🏆 Poker Leaderboard: {title}\n\n```\n"
        response += f"{'Rank':4} {'Player':20} {'Profit':>12} {'Hands':>8} {'VPIP':>6} {'PFR':>6}\n"
        response += "=" * 60 + "\n"

        for i, player in enumerate(leaderboard, 1):
            name = self._clean_name(player.get('canonical_name', 'Unknown'))
            profit = player.get('total_profit', 0.0)
            hands = player.get('total_hands', 0)
            vpip = player.get('vpip', 0.0)
            pfr = player.get('pfr', 0.0)
            response += f"{i:3}. {name:20} ${profit:>10.2f} {hands:>8} {vpip:>5.1f}% {pfr:>5.1f}%\n"

        response += "```"
        return response

    def build_big_pots_response(self, pots: List[Dict[str, Any]]) -> str:
        response = "# 💰 Biggest Pots\n\n"

        if not pots:
            return (
                response
                + "No saved hand pots yet. Upload and analyze a Poker Now log first with `/analyze`."
            )

        for i, pot in enumerate(pots, 1):
            date = (pot.get('hand_date') or pot.get('session_date') or '')[:10] or 'Unknown date'
            hand_number = pot.get('hand_number', 'Unknown')
            winners = pot.get('winners', [])

            response += f"## {i}. ${pot.get('pot_total', 0.0):.2f} pot\n"
            response += f"**Date:** {date}  |  **Hand:** #{hand_number}\n"

            if winners:
                winner_text = ', '.join(
                    f"{self._clean_name(winner.get('player_name', 'Unknown'))} won ${winner.get('amount', 0.0):.2f}"
                    for winner in winners
                )
                response += f"**Winner:** {winner_text}\n"
            else:
                response += "**Winner:** Unknown\n"

            filename = pot.get('filename')
            if filename:
                response += f"*Source:* `{filename}`\n"
            response += "\n"

        return response.strip()

    def build_players_list_response(self, players: List[Dict[str, Any]]) -> str:
        response = "# 👥 Players in Database\n\n```\n"
        for i, row in enumerate(players, 1):
            player_name = row.get('player_name', 'Unknown')
            response += f"{i:2}. {player_name}\n"
        response += "```\n\n"
        response += f"**Total Players:** {len(players)}\n"
        if players:
            response += f"\n💡 Use `/pokerstats player_name:{players[0].get('player_name', '')}` to view stats"
        return response

    def build_equity_response(self, hero: str, villain: str, board: str, result: Dict[str, float]) -> str:
        board_display = board or 'None'
        win_pct = result.get('win', 0.0)
        bar_length = 20
        win_bars = int((win_pct / 100) * bar_length)
        lose_bars = bar_length - win_bars

        response = "# 🎲 Hand Equity Calculator\n\n"
        response += "## 🃏 Cards\n"
        response += f"**Hero:** {hero}\n"
        response += f"**Villain:** {villain}\n"
        response += f"**Board:** {board_display}\n\n"

        response += "## 📈 Visual\n```\n"
        response += "Hero:    [" + "█" * win_bars + "░" * lose_bars + f"] {win_pct:.2f}%\n"
        response += "Villain: [" + "░" * win_bars + "█" * lose_bars + f"] {result.get('lose', 0.0):.2f}%\n"
        response += f"Tie:  {result.get('tie', 0.0):>6.2f}%\n"
        response += "```\n\n"

        if win_pct > 70:
            interpretation = "🔥 **Strong favorite!**"
        elif win_pct > 55:
            interpretation = "✅ **Ahead**"
        elif win_pct > 45:
            interpretation = "🤝 **Coin Flip**"
        elif win_pct > 30:
            interpretation = "⚠️ **Behind**"
        else:
            interpretation = "❌ **Cooked**"

        response += interpretation + "\n\n"
        response += f"*Based on {result.get('simulations', 0):,} Monte Carlo simulations*"
        return response

    def _build_player_data(
        self,
        parser: Any,
        player_financials: Dict[str, float],
        use_ledger: bool,
    ) -> List[Dict[str, Any]]:
        player_data = []
        for player_name, stats in getattr(parser, 'player_stats', {}).items():
            short_name = self._clean_name(player_name)
            player_id = player_name.split('@')[1].strip() if '@' in player_name else None

            if use_ledger and player_id and player_id in player_financials:
                profit = player_financials[player_id] / 100.0
            else:
                profit = stats.actual_profit() if hasattr(stats, 'actual_profit') else (sum(stats.buy_ins) * -1)

            player_data.append({
                'name': short_name,
                'hands': stats.hands_played,
                'vpip': stats.vpip_percentage(),
                'pfr': stats.pfr_percentage(),
                'af': stats.aggression_factor(),
                'three_bet': stats.three_bet_percentage(),
                'profit': profit,
                'total_in': sum(stats.buy_ins),
                'total_out': sum(stats.cash_outs),
            })

        player_data.sort(key=lambda x: x['profit'], reverse=True)
        return player_data

    def _section_for_players(
        self,
        title: str,
        player_data: List[Dict[str, Any]],
        predicate,
        winners: bool = False,
        break_even: bool = False,
    ) -> str:
        selected = [p for p in player_data if predicate(p)]
        if not selected:
            return ""

        response = f"## {title}\n```\n"
        for p in selected:
            if break_even:
                response += (
                    f"{p['name']:15}   $0.00      VPIP: {p['vpip']:5.1f}%  "
                    f"PFR: {p['pfr']:5.1f}% 3Bet%: {p['three_bet']:5.1f}%  AF: {p['af']:4.2f}\n"
                )
            elif winners:
                response += (
                    f"{p['name']:15} +${p['profit']:7.2f}  VPIP: {p['vpip']:5.1f}%  "
                    f"PFR: {p['pfr']:5.1f}% 3Bet%: {p['three_bet']:5.1f}%  AF: {p['af']:4.2f}\n"
                )
            else:
                response += (
                    f"{p['name']:15}  ${p['profit']:7.2f}  VPIP: {p['vpip']:5.1f}%  "
                    f"PFR: {p['pfr']:5.1f}% 3Bet%: {p['three_bet']:5.1f}%  AF: {p['af']:4.2f}\n"
                )
        response += "```\n\n"
        return response

    def _clean_name(self, name: str) -> str:
        return name.split('@')[0].strip() if name else 'Unknown'
