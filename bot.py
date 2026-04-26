import discord
from discord.ext import commands
from discord import app_commands
from google import genai
import os
from dotenv import load_dotenv
import asyncio
import tempfile
import re

# import the poker parser, database
from parser.parser import PokerLogParser
from db.db import PokerStatsDB
# import helpers
from helper.llmHelper import LLMHelper, LLMHelperError
from helper.equityHelper import EquityHelper
from helper.responseHelper import ResponseHelper

from treys import Card, Evaluator, Deck

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None
    print("Warning: GEMINI_API_KEY not found")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Store active sessions per guild (server)
# Structure: {guild_id: {'players': set(), 'started_by': user_id, 'started_at': timestamp}}
sessions = {}

# Store active polls
# Structure: {message_id: {'votes': {user_id: 'yes'/'no'}, 'eligible_voters': set(), 'question': str}}
polls = {}

# gemini models
models_to_try = [
    'gemini-3-flash-preview',
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite'
]

# helper instances
llm_helper = LLMHelper(gemini_client, models_to_try)
equity_helper = EquityHelper()
response_helper = ResponseHelper()

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guilds')

    # Print all guilds the bot is in
    for guild in bot.guilds:
        print(f'  - {guild.name} (ID: {guild.id})')

    # List all commands before syncing
    print(f'\nCommands registered in bot.tree:')
    for cmd in bot.tree.get_commands():
        print(f'  - /{cmd.name}: {cmd.description}')

    # Sync commands with Discord
    try:
        # # Global sync
        synced = await bot.tree.sync()
        print(f'\nSynced {len(synced)} command(s) globally')

        # for testing
        # guild = discord.Object(id=server-id)
        # bot.tree.copy_global_to(guild=guild)
        # synced = await bot.tree.sync(guild=guild)
        # print(f'Synced {len(synced)} command(s) to test server')

        for cmd in synced:
            print(f'  - /{cmd.name}')

    except Exception as e:
        print(f'Failed to sync commands: {e}')
        import traceback
        traceback.print_exc()


# ==================== SESSION COMMANDS ====================

@bot.tree.command(name="startsession", description="Start a new session")
@app_commands.describe(players="Mention players separated by spaces: @user1 @user2 @user3 (optional)")
async def start_session(interaction: discord.Interaction, players: str = None):
    guild_id = interaction.guild_id

    # Check if session already exists
    if guild_id in sessions:
        await interaction.response.send_message(
            "⚠️ A session is already active! Use `/endSession` first.",
            ephemeral=True
        )
        return

    # Initialize session
    player_set = set()

    # Parse mentions from the string
    if players:
        # Discord mentions format: <@USER_ID> or <@!USER_ID>
        mention_pattern = r'<@!?(\d+)>'
        user_ids = re.findall(mention_pattern, players)

        for user_id in user_ids:
            player_set.add(int(user_id))

    # Create session
    sessions[guild_id] = {
        'players': player_set,
        'started_by': interaction.user.id,
        'started_at': discord.utils.utcnow()
    }

    # Create embed
    embed = discord.Embed(
        title="🎮 Session Started!",
        description=f"Session created by {interaction.user.mention}",
        color=discord.Color.green()
    )

    if player_set:
        player_mentions = ' '.join([f'<@{uid}>' for uid in player_set])
        embed.add_field(name="Players", value=player_mentions, inline=False)
    else:
        embed.add_field(name="Players", value="No players added yet. Use `/addPlayer` to add players.", inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="addplayer", description="Add a player to the current session")
@app_commands.describe(user="The user to add to the session")
async def add_player(interaction: discord.Interaction, user: discord.Member):
    guild_id = interaction.guild_id

    # Check if session exists
    if guild_id not in sessions:
        await interaction.response.send_message(
            "⚠️ No active session! Use `/startSession` first.",
            ephemeral=True
        )
        return

    # Add player
    sessions[guild_id]['players'].add(user.id)

    await interaction.response.send_message(
        f"✅ {user.mention} added to the session!",
        ephemeral=False
    )


@bot.tree.command(name="removeplayer", description="Remove a player from the current session")
@app_commands.describe(user="The user to remove from the session")
async def remove_player(interaction: discord.Interaction, user: discord.Member):
    guild_id = interaction.guild_id

    # Check if session exists
    if guild_id not in sessions:
        await interaction.response.send_message(
            "⚠️ No active session! Use `/startSession` first.",
            ephemeral=True
        )
        return

    # Remove player
    if user.id in sessions[guild_id]['players']:
        sessions[guild_id]['players'].remove(user.id)
        await interaction.response.send_message(
            f"✅ {user.mention} removed from the session!",
            ephemeral=False
        )
    else:
        await interaction.response.send_message(
            f"⚠️ {user.mention} is not in the session.",
            ephemeral=True
        )


@bot.tree.command(name="endsession", description="End the current session")
async def end_session(interaction: discord.Interaction):
    guild_id = interaction.guild_id

    # Check if session exists
    if guild_id not in sessions:
        await interaction.response.send_message(
            "⚠️ No active session to end!",
            ephemeral=True
        )
        return

    # Get session info
    session = sessions[guild_id]
    player_count = len(session['players'])

    # Delete session
    del sessions[guild_id]

    embed = discord.Embed(
        title="🛑 Session Ended!",
        description=f"Session ended by {interaction.user.mention}",
        color=discord.Color.red()
    )
    embed.add_field(name="Players", value=str(player_count), inline=True)

    await interaction.response.send_message(embed=embed)


# ==================== VIN POLL COMMAND ====================

class VinView(discord.ui.View):
    def __init__(self, eligible_voters: set, question: str):
        super().__init__(timeout=120)  # 2 minute timeout
        self.votes = {}
        self.eligible_voters = eligible_voters
        self.question = question
        self.total_voters = len(eligible_voters)
        self.message = None

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, emoji="👍")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.eligible_voters:
            await interaction.response.send_message(
                "⚠️ You are not in the current session!",
                ephemeral=True
            )
            return

        self.votes[interaction.user.id] = 'yes'
        await interaction.response.send_message("✅ Voted Yes!", ephemeral=True)

        # Check if all voted
        if len(self.votes) == self.total_voters:
            await self.finish_poll()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, emoji="👎")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.eligible_voters:
            await interaction.response.send_message(
                "⚠️ You are not in the current session!",
                ephemeral=True
            )
            return

        self.votes[interaction.user.id] = 'no'
        await interaction.response.send_message("❌ Voted No!", ephemeral=True)

        # Check if all voted
        if len(self.votes) == self.total_voters:
            await self.finish_poll()

    async def finish_poll(self):
        # Count votes
        yes_count = sum(1 for v in self.votes.values() if v == 'yes')
        no_count = sum(1 for v in self.votes.values() if v == 'no')

        # Determine result
        passed = yes_count > no_count

        # Create result embed
        result_embed = discord.Embed(
            title="📊 Vin Poll Results",
            description=self.question,
            color=discord.Color.green() if passed else discord.Color.red()
        )
        result_embed.add_field(name="Yes", value=f"👍 {yes_count}", inline=True)
        result_embed.add_field(name="No", value=f"👎 {no_count}", inline=True)
        result_embed.add_field(
            name="Result",
            value="✅ PASSED" if passed else "❌ FAILED",
            inline=False
        )

        # Try to load and send GIF
        gif_path = f"gifs/thumbs-{'up' if passed else 'down'}.gif"
        if os.path.exists(gif_path):
            file = discord.File(gif_path, filename=f"thumbs-{'up' if passed else 'down'}.gif")
            result_embed.set_image(url=f"attachment://thumbs-{'up' if passed else 'down'}.gif")
            await self.message.edit(embed=result_embed, view=None)
            content = "🎉 Vin has been invoked! 🎉" if passed else None
            await self.message.reply(content=content, file=file)
        else:
            await self.message.edit(embed=result_embed, view=None)

        self.stop()

    async def on_timeout(self):
        if self.message:
            timeout_embed = discord.Embed(
                title="⏰ Vin Poll Timeout",
                description=f"{self.question}\n\nPoll ended due to timeout.",
                color=discord.Color.orange()
            )
            timeout_embed.add_field(
                name="Votes Received",
                value=f"{len(self.votes)}/{self.total_voters}",
                inline=False
            )
            await self.message.edit(embed=timeout_embed, view=None)


@bot.tree.command(name="vin", description="Start a vin poll for session players")
async def vin(interaction: discord.Interaction):
    guild_id = interaction.guild_id

    # Check if session exists
    if guild_id not in sessions:
        await interaction.response.send_message(
            "⚠️ No active session! Use `/startSession` first.",
            ephemeral=True
        )
        return

    # Check if there are players
    session_players = sessions[guild_id]['players']
    if not session_players:
        await interaction.response.send_message(
            "⚠️ No players in the session! Add players first with `/addPlayer`.",
            ephemeral=True
        )
        return

    # Create poll view
    view = VinView(
        eligible_voters=session_players,
        question="Should we vin?"
    )

    # Create poll embed
    embed = discord.Embed(
        title="🗳️ Vin Poll Started!",
        description="Should we vin?",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Eligible Voters",
        value=f"{len(session_players)} players",
        inline=False
    )
    embed.set_footer(text="Poll ends in 2 minutes or when all players vote")

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()
    view.message = message

# ==================== POKER ANALYSIS COMMAND ====================

@bot.tree.command(name="analyze", description="Analyze a Poker Now hand history log and ledger")
@app_commands.describe(
    log_file="Upload the poker_now_log_*.csv file",
    ledger_file="(Optional) Upload the ledger_*.csv file for accurate profit tracking"
)
async def analyze_poker(interaction: discord.Interaction,
                        log_file: discord.Attachment,
                        ledger_file: discord.Attachment = None):
    """
    Analyze a Poker Now hand history CSV file

    Parameters:
    -----------
    log_file: discord.Attachment
        The poker_now_log_*.csv file to analyze
    ledger_file: discord.Attachment (optional)
        The ledger_*.csv file for accurate profit calculations
    """

    # Check file extension
    if not log_file.filename.endswith('.csv'):
        await interaction.response.send_message(
            "❌ Please upload a .csv file (poker_now_log_*.csv)",
            ephemeral=True
        )
        return

    if ledger_file and not ledger_file.filename.endswith('.csv'):
        await interaction.response.send_message(
            "❌ Ledger file must be a .csv file",
            ephemeral=True
        )
        return

    # Defer response since processing might take a moment
    await interaction.response.defer()

    try:
        # Download the log file to a temporary location
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as tmp_file:
            await log_file.save(tmp_file.name)
            log_temp_path = tmp_file.name

        # Parse the log file for stats
        parser = PokerLogParser(log_temp_path)
        parser.parse_log()

        # If ledger provided, parse it for accurate financials
        player_financials = {}
        if ledger_file:
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as tmp_file:
                await ledger_file.save(tmp_file.name)
                ledger_temp_path = tmp_file.name

            # Parse ledger file
            import csv
            with open(ledger_temp_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row.get('player_id'):
                        continue

                    player_id = row['player_id']
                    net = int(row['net']) if row['net'] else 0

                    if player_id not in player_financials:
                        player_financials[player_id] = 0
                    player_financials[player_id] += net

            # Clean up ledger temp file
            os.unlink(ledger_temp_path)

        response = response_helper.build_poker_analysis_response(
            parser,
            player_financials=player_financials,
            use_ledger=bool(ledger_file)
        )

        message = await interaction.followup.send(response)

        # Save to database (with ledger profits if available)
        try:
            db = PokerStatsDB("poker_stats.db")

            # Update parser stats with ledger profits before saving
            if ledger_file:
                for player_name, stats in parser.player_stats.items():
                    player_id = player_name.split('@')[1].strip() if '@' in player_name else None
                    if player_id and player_id in player_financials:
                        # Override the buy_ins/cash_outs to reflect ledger profit
                        ledger_profit = player_financials[player_id] / 100.0
                        # Set cash_outs to match the ledger profit
                        stats.cash_outs = [sum(stats.buy_ins) + ledger_profit]

            db.add_session(
                parser,
                discord_message_id=str(message.id),
                uploaded_by=str(interaction.user),
                filename=log_file.filename
            )
            db.close()
        except Exception as db_error:
            print(f"Warning: Failed to save to database: {db_error}")

        # Clean up temp file
        os.unlink(log_temp_path)

    except Exception as e:
        await interaction.followup.send(
            f"❌ Error analyzing poker log: {str(e)}",
            ephemeral=True
        )
        # Clean up on error
        if 'log_temp_path' in locals() and os.path.exists(log_temp_path):
            os.unlink(log_temp_path)
        if 'ledger_temp_path' in locals() and os.path.exists(ledger_temp_path):
            os.unlink(ledger_temp_path)


# ==================== POKER HISTORY COMMANDS ====================

@bot.tree.command(name="stats", description="View historical poker stats for a player")
@app_commands.describe(player_name="Player name")
async def poker_stats(interaction: discord.Interaction, player_name: str):
    """
    View historical poker statistics for a player across all sessions

    Parameters:
    -----------
    player_name: str
        The player name to look up (handles aliases automatically)
    """
    await interaction.response.defer()

    try:
        db = PokerStatsDB("poker_stats.db")
        history = db.get_player_history(player_name)
        db.close()

        if not history:
            await interaction.followup.send(
                f"❌ No historical data found for player: **{player_name}**\n"
                f"Make sure the name matches a player from uploaded logs.",
                ephemeral=True
            )
            return

        response = response_helper.build_player_history_response(history)
        await interaction.followup.send(response)

    except Exception as e:
        await interaction.followup.send(
            f"❌ Error retrieving stats: {str(e)}",
            ephemeral=True
        )


@bot.tree.command(name="alias", description="Link player names as aliases")
@app_commands.describe(
    primary_name="Primary player name to keep",
    alias_name="Name to link as an alias"
)
async def poker_alias(interaction: discord.Interaction, primary_name: str, alias_name: str):
    """
    Create an alias linking two player names

    Parameters:
    -----------
    primary_name: str
        The main name to use
    alias_name: str
        The name to alias to the primary name
    """
    try:
        db = PokerStatsDB("poker_stats.db")
        success = db.merge_players(primary_name, alias_name)
        db.close()

        if success:
            await interaction.response.send_message(
                f"✅ Linked **{alias_name}** → **{primary_name}**\n"
                f"All stats for both names will now appear under **{primary_name}**",
                ephemeral=False
            )
        else:
            await interaction.response.send_message(
                f"⚠️ Could not create alias. This may already exist.",
                ephemeral=True
            )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error creating alias: {str(e)}",
            ephemeral=True
        )


@bot.tree.command(name="leaderboard", description="View top players by profit")
@app_commands.describe(
    stat="Stat to rank by (profit, hands, vpip, pfr)",
    limit="Number of players to show (default: 10)"
)
async def poker_leaderboard(interaction: discord.Interaction,
                            stat: str = "profit",
                            limit: int = 10):
    """
    Display leaderboard of top players

    Parameters:
    -----------
    stat: str
        Which stat to rank by
    limit: int
        How many players to show
    """
    await interaction.response.defer()

    try:
        db = PokerStatsDB("poker_stats.db")
        leaderboard = db.get_leaderboard(stat=stat, limit=limit)
        db.close()

        if not leaderboard:
            await interaction.followup.send(
                "❌ No players found in database. Upload some poker logs first!",
                ephemeral=True
            )
            return

        response = response_helper.build_leaderboard_response(leaderboard, stat)
        await interaction.followup.send(response)

    except Exception as e:
        await interaction.followup.send(
            f"❌ Error generating leaderboard: {str(e)}",
            ephemeral=True
        )


@bot.tree.command(name="players", description="List all players in the database")
async def poker_players(interaction: discord.Interaction):
    """List all unique players in the poker database"""
    try:
        db = PokerStatsDB("poker_stats.db")
        cursor = db.conn.cursor()

        cursor.execute("""
            SELECT DISTINCT player_name
            FROM player_sessions
            ORDER BY player_name
        """)

        players = cursor.fetchall()
        db.close()

        if not players:
            await interaction.response.send_message(
                "❌ No players found in database. Upload some poker logs first!",
                ephemeral=True
            )
            return

        response = response_helper.build_players_list_response(players)
        await interaction.response.send_message(response, ephemeral=False)

    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error listing players: {str(e)}",
            ephemeral=True
        )

@bot.tree.command(name="profile", description="Get an AI-generated profile of a player")
@app_commands.describe(player_name="Player name")
async def poker_profile(interaction: discord.Interaction, player_name: str):
    if not gemini_client:
        await interaction.response.send_message(
            "❌ AI profiles are not available. GEMINI_API_KEY not configured.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        db = PokerStatsDB("poker_stats.db")
        history = db.get_player_history(player_name)
        db.close()

        if not history:
            await interaction.followup.send(
                f"❌ No historical data found for player: **{player_name}**\n"
                f"Make sure the name matches a player from uploaded logs.",
                ephemeral=True
            )
            return

        prompt = llm_helper.build_player_profile_prompt(history)
        profile_text = llm_helper.generate_content(prompt)
        response_msg = llm_helper.format_player_profile_message(history, profile_text)

        await interaction.followup.send(response_msg)

    except LLMHelperError as e:
        await interaction.followup.send(str(e), ephemeral=True)
    except Exception as e:
        error_msg = f"❌ Error generating profile: {str(e)}"
        print(f"Error in poker_profile: {e}")
        await interaction.followup.send(error_msg, ephemeral=True)

@bot.tree.command(name="equity", description="Calculate poker hand equity")
@app_commands.describe(
    hero="Your hand (e.g., AhKh)",
    villain="Opponent's hand (e.g., QdQc)",
    board="Board cards - optional (e.g., Ah9h3c)"
)
async def equity(interaction: discord.Interaction, hero: str, villain: str, board: str = ""):
    """
    Calculate equity of hero's hand vs villain's hand
    """

    await interaction.response.defer()

    try:
        result = equity_helper.calculate(hero, villain, board)
        response = response_helper.build_equity_response(hero, villain, board, result)
        await interaction.followup.send(response)

    except Exception as e:
        await interaction.followup.send(
            f"❌ Error calculating equity: {str(e)}",
            ephemeral=True
        )

@bot.tree.command(name="sessionsummary", description="Get an AI-generated summary of a poker session")
@app_commands.describe(session_id="Session ID (optional - defaults to the latest session)")
async def session_summary(interaction: discord.Interaction, session_id: int = None):
    """
    Generate an AI summary of a poker session

    Parameters:
    -----------
    session_id: int (optional)
        Specific session ID to summarize, or None for most recent
    """

    if not gemini_client:
        await interaction.response.send_message(
            "❌ AI summaries are not available. GEMINI_API_KEY not configured.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        db = PokerStatsDB("poker_stats.db")
        session_data = db.get_session_summary(session_id)
        db.close()

        if not session_data:
            if session_id:
                await interaction.followup.send(
                    f"❌ Session ID {session_id} not found in database.\n"
                    f"Use `/sessions` to see available sessions.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "❌ No sessions found in database",
                    ephemeral=True
                )
            return

        prompt = llm_helper.build_session_summary_prompt(session_data)
        summary_text = llm_helper.generate_content(prompt)
        response_msg = llm_helper.format_session_summary_message(session_data, summary_text, session_id)

        await interaction.followup.send(response_msg)

    except LLMHelperError as e:
        await interaction.followup.send(str(e), ephemeral=True)
    except Exception as e:
        error_msg = f"❌ Error generating summary: {str(e)}"
        print(f"Error in session_summary: {e}")
        await interaction.followup.send(error_msg, ephemeral=True)

# ==================== RUN BOT ====================

if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN not found in environment variables!")
        print("Please set DISCORD_TOKEN in your .env file or environment")
        exit(1)

    bot.run(TOKEN)