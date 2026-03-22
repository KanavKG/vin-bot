import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
import asyncio
import tempfile
import re

# Import the poker parser and database
from parser.parser import PokerLogParser
from db.db import PokerStatsDB

# Load environment variables
load_dotenv()

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
        
        # Build response message
        response = "# 🃏 Poker Session Analysis\n\n"
        
        if ledger_file:
            response += "✅ Using ledger file for accurate profit calculations\n\n"
        
        # Sort players by profit (descending)
        player_data = []
        for player_name, stats in parser.player_stats.items():
            short_name = player_name.split('@')[0].strip()
            player_id = player_name.split('@')[1].strip() if '@' in player_name else None
            
            # Use ledger profit if available, otherwise fall back to parser
            if ledger_file and player_id and player_id in player_financials:
                profit = player_financials[player_id] / 100.0  # Convert cents to dollars
            else:
                total_in = sum(stats.buy_ins)
                total_out = sum(stats.cash_outs)
                profit = total_out - total_in
            
            player_data.append({
                'name': short_name,
                'hands': stats.hands_played,
                'vpip': stats.vpip_percentage(),
                'pfr': stats.pfr_percentage(),
                'af': stats.aggression_factor(),
                'three_bet': stats.three_bet_percentage(),
                'profit': profit,
                'total_in': sum(stats.buy_ins),
                'total_out': sum(stats.cash_outs)
            })
        
        # Sort by profit
        player_data.sort(key=lambda x: x['profit'], reverse=True)
        
        # Winners
        winners = [p for p in player_data if p['profit'] > 0]
        if winners:
            response += "## 🏆 Winners\n```\n"
            for p in winners:
                response += f"{p['name']:15} +${p['profit']:7.2f}  VPIP: {p['vpip']:5.1f}%  PFR: {p['pfr']:5.1f}% 3Bet%: {p['three_bet']:5.1f}%  AF: {p['af']:4.2f}\n"
            response += "```\n\n"
        
        # Losers
        losers = [p for p in player_data if p['profit'] < 0]
        if losers:
            response += "## 💸 Losers\n```\n"
            for p in losers:
                response += f"{p['name']:15}  ${p['profit']:7.2f}  VPIP: {p['vpip']:5.1f}%  PFR: {p['pfr']:5.1f}% 3Bet%: {p['three_bet']:5.1f}%  AF: {p['af']:4.2f}\n"
            response += "```\n\n"
        
        # Break even
        break_even = [p for p in player_data if abs(p['profit']) < 0.01]
        if break_even:
            response += "## 🤝 Break Even\n```\n"
            for p in break_even:
                response += f"{p['name']:15}   $0.00      VPIP: {p['vpip']:5.1f}%  PFR: {p['pfr']:5.1f}% 3Bet%: {p['three_bet']:5.1f}%  AF: {p['af']:4.2f}\n"
            response += "```\n\n"
        
        # Summary stats
        total_hands = len(parser.hands)
        total_money_in = sum(p['total_in'] for p in player_data)
        total_money_out = sum(p['total_out'] for p in player_data)
        
        response += f"**Total Hands:** {total_hands}\n"
        response += f"**Total Buy-ins:** ${total_money_in:.2f}\n"
        response += f"**Total Cash-outs:** ${total_money_out:.2f}\n"
        
        # Send response
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
@app_commands.describe(player_name="Player name (e.g., 'dhruv' or 'Kaushik')")
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
        
        # Build response
        canonical = history['canonical_name'].split('@')[0].strip()
        response = f"# 📊 Historical Stats: {canonical}\n\n"
        
        # Show aliases if any
        if len(history['all_aliases']) > 1:
            aliases = [name.split('@')[0].strip() for name in history['all_aliases'][1:]]
            response += f"**Also known as:** {', '.join(aliases)}\n\n"
        
        # Overall stats
        response += "## Overall Performance\n```\n"
        response += f"Sessions Played:  {history['total_sessions']}\n"
        response += f"Total Hands:      {history['total_hands']}\n"
        response += f"Hands Won:        {history['hands_won']} ({history['win_rate']:.1f}%)\n"
        response += f"Total Profit:     ${history['total_profit']:+.2f}\n"
        response += f"Total Buy-ins:    ${history['total_buy_ins']:.2f}\n"
        response += f"Total Cash-outs:  ${history['total_cash_outs']:.2f}\n"
        response += "```\n\n"
        
        # Playing style
        response += "## Playing Style\n```\n"
        response += f"VPIP:              {history['vpip']:.1f}%\n"
        response += f"PFR:               {history['pfr']:.1f}%\n"
        response += f"3-Bet %:           {history['three_bet_pct']:.1f}%\n"
        response += f"Aggression Factor: {history['aggression_factor']:.2f}\n"
        response += f"WTSD:              {history['wtsd']:.1f}%\n"
        response += "```\n\n"
        
        # Action breakdown
        response += "## Actions\n```\n"
        response += f"Bets:    {history['actions']['bets']}\n"
        response += f"Raises:  {history['actions']['raises']}\n"
        response += f"Calls:   {history['actions']['calls']}\n"
        response += f"Checks:  {history['actions']['checks']}\n"
        response += f"Folds:   {history['actions']['folds']}\n"
        response += "```\n\n"
        
        # Recent sessions (last 5)
        response += "## Recent Sessions\n```\n"
        for session in history['sessions'][:5]:
            date = session['session_date'][:10]  # Just the date part
            profit_sign = '+' if session['profit'] >= 0 else ''
            response += f"{date}  Hands: {session['hands_played']:3}  P/L: {profit_sign}${session['profit']:.2f}\n"
        response += "```"
        
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
        
        # Build response
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
            name = player['canonical_name'].split('@')[0].strip()
            profit = player['total_profit']
            hands = player['total_hands']
            vpip = player['vpip']
            pfr = player['pfr']
            
            response += f"{i:3}. {name:20} ${profit:>10.2f} {hands:>8} {vpip:>5.1f}% {pfr:>5.1f}%\n"
        
        response += "```"
        
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
        
        response = "# 👥 Players in Database\n\n```\n"
        for i, row in enumerate(players, 1):
            player_name = row['player_name']
            response += f"{i:2}. {player_name}\n"
        response += "```\n\n"
        response += f"**Total Players:** {len(players)}\n"
        response += f"\n💡 Use `/pokerstats player_name:{players[0]['player_name']}` to view stats"
        
        await interaction.response.send_message(response, ephemeral=False)
        
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error listing players: {str(e)}",
            ephemeral=True
        )


# ==================== RUN BOT ====================

if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN not found in environment variables!")
        print("Please set DISCORD_TOKEN in your .env file or environment")
        exit(1)
    
    bot.run(TOKEN)