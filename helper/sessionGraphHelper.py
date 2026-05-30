from io import BytesIO
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator, StrMethodFormatter


class SessionGraphHelper:
    """Builds stack progression charts from parsed Poker Now logs."""

    def render_stack_graph(self, session_data: Dict[str, Any]) -> BytesIO:
        hands = [hand for hand in session_data.get("hands", []) if hand.get("stacks")]
        if not hands:
            raise ValueError("No stack snapshots found for that session.")

        players = self._players_in_first_seen_order(hands)
        if not players:
            raise ValueError("No players found for that session.")

        x_values = [hand["hand_number"] for hand in hands]

        fig, ax = plt.subplots(figsize=(12, 7), dpi=160)
        fig.patch.set_facecolor("#ffffff")
        ax.set_facecolor("#ffffff")

        colors = plt.get_cmap("tab20").colors
        for index, player in enumerate(players):
            y_values = [hand["stacks"].get(player) for hand in hands]
            ax.plot(
                x_values,
                y_values,
                color=colors[index % len(colors)],
                linewidth=2.2,
                marker="o",
                markersize=3.5,
                label=self._clean_name(player),
            )

        title = "Session Stack Progression"
        if session_data.get("session_id"):
            title += f" #{session_data['session_id']}"
        ax.set_title(title, fontsize=18, fontweight="bold", pad=16)
        ax.set_xlabel("Hand", fontsize=12, labelpad=10)
        ax.set_ylabel("Stack Size", fontsize=12, labelpad=10)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.yaxis.set_major_formatter(StrMethodFormatter("${x:,.0f}"))
        ax.grid(axis="y", color="#d6dde5", linewidth=0.8, alpha=0.8)
        ax.grid(axis="x", color="#eef2f6", linewidth=0.6, alpha=0.7)

        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        for spine in ["left", "bottom"]:
            ax.spines[spine].set_color("#9aa6b2")

        ax.tick_params(colors="#334155")
        legend_columns = 1 if len(players) <= 10 else 2
        ax.legend(
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            frameon=False,
            fontsize=9,
            ncol=legend_columns,
        )

        buffer = BytesIO()
        fig.savefig(buffer, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        buffer.seek(0)
        return buffer

    def render_player_profit_graph(self, history: Dict[str, Any]) -> BytesIO:
        sessions = history.get("sessions", [])
        if not sessions:
            raise ValueError("No saved sessions found for that player.")

        player_name = self._clean_name(history.get("canonical_name", "Unknown"))
        x_values = list(range(1, len(sessions) + 1))
        y_values = [float(session.get("profit") or 0.0) for session in sessions]

        fig, ax = plt.subplots(figsize=(11, 6.5), dpi=160)
        fig.patch.set_facecolor("#ffffff")
        ax.set_facecolor("#ffffff")

        point_colors = [
            "#16a34a" if profit > 0 else "#dc2626" if profit < 0 else "#64748b"
            for profit in y_values
        ]

        ax.plot(x_values, y_values, color="#2563eb", linewidth=2.0, alpha=0.75)
        ax.scatter(
            x_values,
            y_values,
            color=point_colors,
            edgecolor="#ffffff",
            linewidth=1.2,
            s=58,
            zorder=3,
        )
        ax.axhline(0, color="#0f172a", linewidth=1.0, alpha=0.7)

        ax.set_title(f"{player_name} P/L Over Time", fontsize=18, fontweight="bold", pad=16)
        ax.set_xlabel("Session", fontsize=12, labelpad=10)
        ax.set_ylabel("Profit / Loss", fontsize=12, labelpad=10)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.yaxis.set_major_formatter(FuncFormatter(self._format_dollars))
        ax.grid(axis="y", color="#d6dde5", linewidth=0.8, alpha=0.8)
        ax.grid(axis="x", color="#eef2f6", linewidth=0.6, alpha=0.7)

        tick_indexes = self._tick_indexes(len(sessions))
        ax.set_xticks([x_values[i] for i in tick_indexes])
        ax.set_xticklabels(
            [self._session_label(sessions[i]) for i in tick_indexes],
            rotation=35,
            ha="right",
        )

        total_profit = sum(y_values)
        ax.text(
            0.99,
            0.98,
            f"Total: {self._format_dollars(total_profit)}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=11,
            color="#334155",
            bbox={"boxstyle": "round,pad=0.3", "facecolor": "#f8fafc", "edgecolor": "#cbd5e1"},
        )

        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        for spine in ["left", "bottom"]:
            ax.spines[spine].set_color("#9aa6b2")

        ax.tick_params(colors="#334155")
        fig.tight_layout()

        buffer = BytesIO()
        fig.savefig(buffer, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        buffer.seek(0)
        return buffer

    def _players_in_first_seen_order(self, hands: List[Any]) -> List[str]:
        players: Dict[str, None] = {}
        for hand in hands:
            for player in hand["stacks"]:
                players.setdefault(player, None)
        return list(players.keys())

    def _clean_name(self, name: str) -> str:
        return name.split("@")[0].strip() if name else "Unknown"

    def _tick_indexes(self, count: int) -> List[int]:
        if count <= 12:
            return list(range(count))

        step = max(1, count // 12)
        indexes = list(range(0, count, step))
        if indexes[-1] != count - 1:
            indexes.append(count - 1)
        return indexes

    def _session_label(self, session: Dict[str, Any]) -> str:
        session_date = str(session.get("session_date") or "")
        if session_date:
            return session_date[:10]
        return f"#{session.get('session_id', '')}"

    def _format_dollars(self, value: float, _position: Any = None) -> str:
        if value < 0:
            return f"-${abs(value):,.0f}"
        return f"${value:,.0f}"
