from typing import Any, Dict, List, Optional


class LLMHelperError(Exception):
    """Raised when AI content generation fails."""


class LLMHelper:
    """Helper for building prompts, generating LLM content, and formatting responses."""

    def __init__(self, gemini_client: Any, models_to_try: Optional[List[str]] = None):
        self.gemini_client = gemini_client
        self.models_to_try = models_to_try or []

    def generate_content(self, prompt: str) -> str:
        if not self.gemini_client:
            raise LLMHelperError("AI client is not configured.")

        last_exception = None
        for model in self.models_to_try:
            try:
                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                if response and getattr(response, 'text', None):
                    return response.text
                last_exception = LLMHelperError(f"{model} returned an empty response.")
            except Exception as exc:
                message = str(exc).lower()
                is_fallback_error = any(
                    token in message
                    for token in [
                        'quota',
                        'rate limit',
                        'resource exhausted',
                        'unavailable',
                        'high demand',
                        '503'
                    ]
                )
                if is_fallback_error:
                    last_exception = exc
                    continue
                raise

        raise LLMHelperError(
            "All AI models are currently unavailable. Please try again later."
        ) from last_exception

    def build_player_profile_prompt(self, history: Dict) -> str:
        canonical_name = self._clean_name(history.get('canonical_name', 'Unknown'))
        stats_summary = self._player_stats_summary(history)

        return f"""
        You are a sharp, witty poker analyst profiling a player in a short-handed cash game (typically 5 to 6 players, ranging from 4 to 8).

        Goal:
        Produce an entertaining but statistically grounded player profile using the data provided.

        Table Context:
        - The game is usually 5 to 6 handed, but can be as short as 4 or as full as 8
        - Expect wider ranges and more aggression than full-ring
        - Adjust expectations dynamically based on player count (looser when short-handed, tighter when closer to full table)
        - Do not mislabel standard short-handed play as loose or overly aggressive

        Guidelines:
        - Anchor observations explicitly to the provided stats
        - Interpret what the numbers imply about playstyle
        - Be clever, slightly ruthless, and humorous — but not nonsensical
        - Criticize clearly if stats indicate leaks, but include praise if warranted
        - Avoid generic statements; every claim should tie back to a stat
        - No fluff or filler

        Player stats:
        {stats_summary}

        Output format:
        1. A single paragraph (~50 words) with a vivid, memorable player profile
        2. One concise sentence of actionable advice targeting the biggest area of improvement

        Style reference:
        Think poker Twitter meets professional HUD analysis — cutting, insightful, and grounded in short-handed dynamics.
        """

    def format_player_profile_message(self, history: Dict, profile_text: str) -> str:
        canonical_name = self._clean_name(history.get('canonical_name', 'Unknown'))
        response = f"# 🎭 Player Profile: {canonical_name}\n\n"

        aliases = history.get('all_aliases', [])
        if len(aliases) > 1:
            alias_list = [self._clean_name(alias) for alias in aliases if self._clean_name(alias) != canonical_name]
            if alias_list:
                response += f"*Also known as: {', '.join(alias_list)}*\n\n"

        response += "## 📊 Quick Stats\n"
        response += f"**Sessions:** {history.get('total_sessions', 0)} | "
        response += f"**Hands:** {history.get('total_hands', 0)} | "
        response += f"**Profit:** ${history.get('total_profit', 0.0):+.2f}\n\n"

        response += "## 🎪 AI Analysis\n"
        response += f"{profile_text}\n\n"

        response += "## 🎲 Playing Style\n```\n"
        response += f"VPIP: {history.get('vpip', 0.0):.1f}%  |  "
        response += f"PFR: {history.get('pfr', 0.0):.1f}%  |  "
        response += f"3-Bet: {history.get('three_bet_pct', 0.0):.1f}%  |  "
        response += f"AF: {history.get('aggression_factor', 0.0):.2f}\n"
        response += "```\n"

        return response

    def build_session_summary_prompt(self, session_data: Dict) -> str:
        session_info = self._session_info_summary(session_data)

        return f"""
        You are a witty poker session recap narrator. Analyze this poker session and write an entertaining 3-4 paragraph summary, MUST BE less than 1700 characters.

        Guidelines:
        - Start with an engaging headline about the session
        - Highlight the big winner(s) and what made them successful
        - Call out interesting playing styles (tight/loose/aggressive/passive)
        - Mention notable patterns (who was the nit? who was the maniac? who got unlucky?)
        - Include specific stats when they tell a story
        - Keep it fun and slightly roasting but friendly
        - Use poker terminology naturally

        Session Data:

        {session_info}

        Write an entertaining session recap (3-4 paragraphs):
        """

    def format_session_summary_message(self, session_data: Dict, summary_text: str, requested_session_id: Optional[int] = None) -> str:
        response = "# 🎲 Session Recap"
        if requested_session_id:
            response += f" (Session #{requested_session_id})"
        response += "\n\n"

        session_date = session_data.get('session_date', '')
        response += f"**Date:** {session_date[:10]}\n"
        response += f"**Hands:** {session_data.get('total_hands', 0)} | "
        response += f"**Players:** {session_data.get('total_players', 0)}\n\n"
        response += "---\n\n"
        response += summary_text
        response += "\n\n---\n\n"
        return response

    def _player_stats_summary(self, history: Dict) -> str:
        return (
            f"Player: {self._clean_name(history.get('canonical_name', 'Unknown'))}\n"
            f"Total Sessions: {history.get('total_sessions', 0)}\n"
            f"Total Hands Played: {history.get('total_hands', 0)}\n"
            f"Total Profit/Loss: ${history.get('total_profit', 0.0):.2f}\n\n"
            f"Playing Style Stats:\n"
            f"- VPIP (Voluntarily Put $ In Pot): {history.get('vpip', 0.0):.1f}%\n"
            f"- PFR (Pre-Flop Raise): {history.get('pfr', 0.0):.1f}%\n"
            f"- 3-Bet Percentage: {history.get('three_bet_pct', 0.0):.1f}%\n"
            f"- Aggression Factor: {history.get('aggression_factor', 0.0):.2f}\n"
            f"- Went To Showdown: {history.get('wtsd', 0.0):.1f}%\n\n"
            f"Win Rate: {history.get('win_rate', 0.0):.1f}% of hands won\n\n"
            f"Action Breakdown:\n"
            f"- Bets: {history.get('actions', {}).get('bets', 0)}\n"
            f"- Raises: {history.get('actions', {}).get('raises', 0)}\n"
            f"- Calls: {history.get('actions', {}).get('calls', 0)}\n"
            f"- Checks: {history.get('actions', {}).get('checks', 0)}\n"
            f"- Folds: {history.get('actions', {}).get('folds', 0)}\n"
        )

    def _session_info_summary(self, session_data: Dict) -> str:
        players = session_data.get('players', [])
        uploaded_by = session_data.get('uploaded_by', 'Unknown')

        session_info = (
            f"Session ID: {session_data.get('session_id', '')}\n"
            f"Session Date: {session_data.get('session_date', '')}\n"
            f"Total Hands: {session_data.get('total_hands', 0)}\n"
            f"Total Players: {session_data.get('total_players', 0)}\n"
            f"Uploaded by: {uploaded_by}\n\n"
            f"Player Statistics:\n"
        )

        for player in players:
            session_info += (
                f"Player: {player.get('player_name', 'Unknown')}\n"
                f"- Hands Played: {player.get('hands_played', 0)}\n"
                f"- VPIP: {player.get('vpip', 0.0):.1f}%\n"
                f"- PFR: {player.get('pfr', 0.0):.1f}%\n"
                f"- 3-Bet: {player.get('three_bet_pct', 0.0):.1f}%\n"
                f"- Aggression Factor: {player.get('aggression_factor', 0.0):.2f}\n"
                f"- Went to Showdown: {player.get('wtsd', 0.0):.1f}%\n"
                f"- Profit/Loss: ${player.get('profit', 0.0):+.2f}\n"
                f"- Buy-ins: ${player.get('buy_ins', 0.0):.2f}\n"
                f"- Cash-outs: ${player.get('cash_outs', 0.0):.2f}\n"
                f"- Hands Won: {player.get('hands_won', 0)}\n"
                f"- Actions: {player.get('bets', 0)} bets, {player.get('raises', 0)} raises, {player.get('calls', 0)} calls, {player.get('checks', 0)} checks, {player.get('folds', 0)} folds\n\n"
            )

        return session_info

    def _clean_name(self, name: str) -> str:
        return name.split('@')[0].strip() if name else 'Unknown'
