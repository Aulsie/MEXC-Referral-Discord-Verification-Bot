# =============================================================================
# IMPORTS
# =============================================================================
import discord
from discord.ext import commands
from discord import app_commands
import json
import aiohttp
import asyncio
import time
import hmac
import hashlib
import datetime
import csv
import io
import os
import sys
from dotenv import load_dotenv
import sqlite3

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database_controller import *

# =============================================================================
# CONFIG MANAGEMENT
# =============================================================================
CONFIG_PATH = "config.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load {CONFIG_PATH}: {e}")
        return {}

def save_config(key, value):
    config_data = load_config()
    config_data[key] = value
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)
    os.environ[str(key)] = str(value)
    return config_data

def set_env_from_config(config_data):
    for key, value in config_data.items():
        if value is None:
            continue
        if isinstance(value, list):
            os.environ[str(key)] = ",".join(str(item) for item in value)
        else:
            os.environ[str(key)] = str(value)

def write_env(key, value):
    save_config(key, value)

# =============================================================================
# INITIALIZATION
# =============================================================================
config = load_config()
load_dotenv()
set_env_from_config(config)
init_db()

# Load environment variables
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
VERIFIED_ROLE = int(os.getenv("VERIFIED_ROLE", 0))
STAFF_ROLES = [int(x) for x in os.getenv("STAFF_ROLES", "").split(",") if x.strip()]
VERIFICATION_CHANNEL = int(os.getenv("VERIFICATION_CHANNEL", 0))
PENDING_CHANNEL = int(os.getenv("PENDING_CHANNEL", 0))
APPROVED_CHANNEL = int(os.getenv("APPROVED_CHANNEL", 0))
DENIED_CHANNEL = int(os.getenv("DENIED_CHANNEL", 0))
VC_CATEGORY = int(os.getenv("VC_CATEGORY", 0))
VDMSG_ENABLED = os.getenv("VDMSG_ENABLED", "false").lower() == "true"
AUTO_APPROVE = os.getenv("VAUTO_APPROVE", "false").lower() == "true"
INVALID_UID_COOLDOWN = int(os.getenv("INVALID_UID_COOLDOWN", 300))
API_KEY = os.getenv("MEXC_API_KEY")
API_SECRET = os.getenv("MEXC_SECRET")
ACTIVE_SPAN = os.getenv("ACTIVE_SPAN", "month")
ACTIVE_VALUE = int(os.getenv("ACTIVE_VALUE", 1))
ACTIVE_PERIOD = int(os.getenv("ACTIVE_PERIOD", 2592000))
PANEL_CHANNEL_ID = int(os.getenv("PANEL_CHANNEL_ID", 0))
PANEL_MESSAGE_ID = int(os.getenv("PANEL_MESSAGE_ID", 0))

GUILD = discord.Object(id=GUILD_ID)

# Verification tracking
pending_verifications = {}
invalid_uid_cooldowns = {}
COOLDOWN_SECONDS = int(os.getenv("INVALID_UID_COOLDOWN", 300))
DATABASE = "database.db"
user_vc_map = {}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
async def send_verify_result(user, guild, status, uid, staff=None, trading_status=None, last_trade_time=None, reason=None):
    if status == "approved":
        embed = discord.Embed(
            title="✅ Verification Approved",
            description="Your **Discord UID** is now linked to your **MEXC account.**",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="MEXC UID", value=f"`{uid}`")
        embed.add_field(name="Approved by", value=staff.mention if staff else "Unknown")
        embed.add_field(name="Trading Status", value=trading_status if trading_status else "Unknown")
        embed.add_field(name="Last Trade", value=format_last_trade(last_trade_time), inline=True)
        embed.add_field(name="Timestamp", value=f"<t:{int(datetime.datetime.now(datetime.UTC).timestamp())}:F>")
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
    else:
        embed = discord.Embed(
            title="❌ Verification Denied",
            description="Your verification request has been **denied**.",
            color=discord.Color.red()
        )
        embed.add_field(name="MEXC UID", value=f"`{uid}`")
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        print(f"Could not DM user {user}")

def set_active_period(**kwargs):
    """kwargs example: {'days': 1} or {'weeks':1}, etc."""
    global ACTIVE_PERIOD
    seconds = 0
    if 'days' in kwargs:
        seconds = kwargs['days'] * 86400
    elif 'weeks' in kwargs:
        seconds = kwargs['weeks'] * 7 * 86400
    elif 'months' in kwargs:
        seconds = kwargs['months'] * 30 * 86400
    elif 'years' in kwargs:
        seconds = kwargs['years'] * 365 * 86400
    ACTIVE_PERIOD = seconds

# =============================================================================
# MEXC API
# =============================================================================
async def get_referrals():
    if not API_KEY or not API_SECRET:
        return {"success": False, "msg": "MEXC API key not configured."}

    async with aiohttp.ClientSession() as session:
        try:
            # Get server time
            async with session.get("https://api.mexc.com/api/v3/time") as resp:
                server_data = await resp.json()
                server_time = server_data.get("serverTime")

            if not server_time:
                return {"success": False, "msg": "Failed to get server time."}

            timestamp = str(server_time)
            recv_window = "5000"
            headers = {"X-MEXC-APIKEY": API_KEY}
            page = 1
            page_size = 50
            all_referrals = []

            while True:
                query = f"page={page}&pageSize={page_size}&timestamp={timestamp}&recvWindow={recv_window}"
                signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
                url = f"https://api.mexc.com/api/v3/rebate/affiliate/referral?{query}&signature={signature}"

                async with session.get(url, headers=headers) as resp:
                    data = await resp.json()
                    if not data.get("success"):
                        return data

                    result = data.get("data", {}).get("resultList", [])
                    if not result:
                        break

                    all_referrals.extend(result)
                    if len(result) < page_size:
                        break
                    page += 1

            return {"success": True, "data": {"resultList": all_referrals}}

        except Exception as e:
            print("MEXC API ERROR:", e)
            return {"success": False, "msg": str(e)}

# =============================================================================
# BOT SETUP
# =============================================================================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
init_db()
bot = commands.Bot(command_prefix="/", intents=intents)


# ==========================================================================
#                                 PANEL VIEW
# ==========================================================================

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify with MEXC", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifyModal())





# =============================================================================
# TIME HELPERS
# =============================================================================
MANILA_TZ = datetime.timezone(datetime.timedelta(hours=8))

def manila_now():
    return datetime.datetime.now(MANILA_TZ)

def format_last_trade(last_trade_time):
    if not last_trade_time:
        return "No trades"
    try:
        dt = datetime.datetime.fromtimestamp(int(last_trade_time) / 1000, tz=datetime.UTC).astimezone(MANILA_TZ)
        return dt.strftime("%Y-%m-%d %H:%M Manila")
    except:
        return "No trades"

def format_full_datetime(dt):
    dt = dt.astimezone(MANILA_TZ)
    formatted = dt.strftime("%A, %d %B %Y %I:%M %p")
    formatted = formatted.replace(" 0", " ").replace("AM", "am").replace("PM", "pm")
    return formatted

def utc_from_ms(ms):
    if not ms:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000, datetime.UTC)
    except:
        return None

def format_time(ms):
    dt = utc_from_ms(ms)
    if not dt:
        return "N/A"
    local_dt = dt.astimezone()
    return local_dt.strftime("%Y-%m-%d %I:%M %p").lstrip("0")

# =============================================================================
# MEXC DATA & TRADING STATUS
# =============================================================================
def extract_mexc_data(user):
    return {
        "asset": user.get("asset"),
        "commission": user.get("commission"),
        "depositAmount": user.get("depositAmount"),
        "email": user.get("email"),
        "firstDepositTime": user.get("firstDepositTime"),
        "firstTradeTime": user.get("firstTradeTime"),
        "identification": user.get("identification"),
        "inviteCode": user.get("inviteCode"),
        "lastDepositTime": user.get("lastDepositTime"),
        "lastTradeTime": user.get("lastTradeTime"),
        "nickName": user.get("nickName"),
        "registerTime": user.get("registerTime"),
        "tradingAmount": user.get("tradingAmount"),
        "uid": user.get("uid"),
        "withdrawAmount": user.get("withdrawAmount")
    }

def get_trading_status(last_trade_time):
    if not last_trade_time:
        return "Inactive"
    dt = utc_from_ms(last_trade_time)
    if not dt:
        return "Inactive"
    now = datetime.datetime.now(datetime.UTC)
    delta = now - dt
    return "Active" if delta.total_seconds() <= ACTIVE_PERIOD else "Inactive"

async def cleanup_verification(guild, user_id):
    vc_id = user_vc_map.pop(user_id, None)
    if vc_id:
        vc = guild.get_channel(vc_id)
        if vc:
            try:
                await vc.delete()
            except:
                pass
    pending_verifications.pop(user_id, None)

def build_staff_embed(title, color, user, staff, mexc, reason=None):
    embed = discord.Embed(title=title, color=color)
    embed.set_thumbnail(url=user.display_avatar.url)
    trading_status = get_trading_status(mexc["lastTradeTime"])
    embed.add_field(name="User", value=user.mention)
    if staff:
        if "Approved" in title:
            embed.add_field(name="Approved by", value=staff.mention)
        elif "Denied" in title:
            embed.add_field(name="Denied by", value=staff.mention)
    embed.add_field(name="MEXC UID", value=f"`{mexc['uid']}`")
    embed.add_field(name="MEXC Nickname", value=f"`{mexc['nickName']}`")
    embed.add_field(name="Trading Status", value=f"`{trading_status}`")
    embed.add_field(name="Last Trade", value=f"`{format_last_trade(mexc['lastTradeTime'])}`", inline=True)
    try:
        dt = datetime.datetime.fromtimestamp(int(mexc["registerTime"]) / 1000, tz=datetime.UTC)
        embed.add_field(name="MEXC Registration Time", value=f"*{format_full_datetime(dt)}*", inline=True)
    except:
        embed.add_field(name="MEXC Registration Time", value="Unknown", inline=True)
    embed.add_field(name="Timestamp", value=f"*{format_full_datetime(manila_now())}*")
    if reason:
        embed.add_field(name="Reason", value=f"*{reason}*", inline=False)
    return embed


# ================================================================
# STAFF REVIEW VIEW
# ================================================================
class StaffReviewView(discord.ui.View):

    def __init__(self, user_id, mexc_data):
        super().__init__(timeout=None)

        self.user_id = user_id
        self.mexc = mexc_data

    def is_staff(self, member):
        return any(role.id in STAFF_ROLES for role in member.roles)

    async def get_member(self, guild):
        return guild.get_member(self.user_id) or await guild.fetch_member(self.user_id)


# ------------------------------------------------
# APPROVE
# ------------------------------------------------
    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not self.is_staff(interaction.user):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        guild = interaction.guild
        user = await self.get_member(guild)

        trading_status = get_trading_status(self.mexc["lastTradeTime"])

        add_user(
            str(self.user_id),
            self.mexc["uid"],
            self.mexc["lastTradeTime"],
            self.mexc["registerTime"],
            self.mexc["nickName"],
            self.mexc["email"],
            trading_status,
            int(datetime.datetime.now(datetime.UTC).timestamp())
        )

        role = guild.get_role(VERIFIED_ROLE)

        if role:
            await user.add_roles(role)

        embed = build_staff_embed(
            "Verification Approved",
            discord.Color.green(),
            user,
            interaction.user,
            self.mexc
        )

        channel = bot.get_channel(APPROVED_CHANNEL)

        if channel:
            await channel.send(embed=embed)

        await send_verify_result(
            user,
            guild,
            "approved",
            self.mexc["uid"],
            staff=interaction.user,
            trading_status=trading_status,
            last_trade_time=self.mexc["lastTradeTime"]
        )

        await cleanup_verification(guild, self.user_id)

        await interaction.message.edit(view=None)

        await interaction.response.send_message(
            "User approved successfully.",
            ephemeral=True
        )


# ------------------------------------------------
# DENY
# ------------------------------------------------
    @discord.ui.button(label="⛔ Deny", style=discord.ButtonStyle.red)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not self.is_staff(interaction.user):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        guild = interaction.guild
        user = await self.get_member(guild)

        embed = build_staff_embed(
            "Verification Denied",
            discord.Color.red(),
            user,
            interaction.user,
            self.mexc
        )

        channel = bot.get_channel(DENIED_CHANNEL)

        if channel:
            await channel.send(embed=embed)

        await send_verify_result(
            user,
            guild,
            "denied",
            self.mexc["uid"]
        )

        await cleanup_verification(guild, self.user_id)

        await interaction.message.edit(view=None)

        await interaction.response.send_message(
            "Verification denied.",
            ephemeral=True
        )


# ------------------------------------------------
# APPROVE WITH REASON
# ------------------------------------------------
    @discord.ui.button(label="✅ Approve, Reason", style=discord.ButtonStyle.green)
    async def approve_reason(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not self.is_staff(interaction.user):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        await interaction.response.send_modal(
            ReasonModal("approve", self.user_id, self.mexc)
        )


# ------------------------------------------------
# DENY WITH REASON
# ------------------------------------------------
    @discord.ui.button(label="⛔ Deny, Reason", style=discord.ButtonStyle.red)
    async def deny_reason(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not self.is_staff(interaction.user):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        await interaction.response.send_modal(
            ReasonModal("deny", self.user_id, self.mexc)
        )


# ------------------------------------------------
# CREATE VC
# ------------------------------------------------
    @discord.ui.button(label="🔊 Create VC", style=discord.ButtonStyle.blurple)
    async def create_vc(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not self.is_staff(interaction.user):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        guild = interaction.guild
        user = await self.get_member(guild)

        if self.user_id in user_vc_map:
            vc = guild.get_channel(user_vc_map[self.user_id])
            return await interaction.response.send_message(
                f"A VC already exists: {vc.mention}",
                ephemeral=True
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, connect=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }

        for rid in STAFF_ROLES:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True)

        category = guild.get_channel(VC_CATEGORY)

        vc = await guild.create_voice_channel(
            name=f"verify-{user.display_name}",
            overwrites=overwrites,
            category=category
        )

        user_vc_map[self.user_id] = vc.id

        staff_mentions = " ".join(f"<@&{r}>" for r in STAFF_ROLES)

        await vc.send(
            f"🔔 {user.mention} please join your interview VC.\n{staff_mentions}"
        )

        await interaction.response.send_message(
            f"VC created: {vc.mention}",
            ephemeral=True
        )


# ================================================================
# REASON MODAL
# ================================================================
class ReasonModal(discord.ui.Modal):

    def __init__(self, action, user_id, mexc_data):
        super().__init__(title=f"{action.capitalize()} Verification")

        self.action = action
        self.user_id = user_id
        self.mexc = mexc_data

        # Text input for reason
        self.reason_input = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = guild.get_member(self.user_id) or await guild.fetch_member(self.user_id)
        staff = interaction.user
        reason = self.reason_input.value.strip()

        # Defer response to allow DMs and channel messages
        await interaction.response.defer(ephemeral=True)

        # Determine channel, color, title for staff embed
        channel_id = APPROVED_CHANNEL if self.action == "approve" else DENIED_CHANNEL
        color = discord.Color.green() if self.action == "approve" else discord.Color.red()
        title = "Verification Approved" if self.action == "approve" else "Verification Denied"

        # Build embed for staff channel
        embed = build_staff_embed(
            title,
            color,
            user,
            staff,
            self.mexc,
            reason
        )

        # Send embed to staff channel
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send(embed=embed)

        # Approval logic
        if self.action == "approve":
            trading_status = get_trading_status(self.mexc["lastTradeTime"])

            add_user(
                str(self.user_id),
                self.mexc["uid"],
                self.mexc["lastTradeTime"],
                self.mexc["registerTime"],
                self.mexc["nickName"],
                self.mexc["email"],
                trading_status,
                int(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).timestamp())
            )

            # Assign verified role
            role = guild.get_role(VERIFIED_ROLE)
            if role:
                await user.add_roles(role)

            # Send DM to user
            await send_verify_result(
                user,
                guild,
                "approved",
                self.mexc["uid"],
                staff=staff,
                trading_status=trading_status,
                last_trade_time=self.mexc["lastTradeTime"],
                reason=reason
            )

        else:  # Deny
            await send_verify_result(
                user,
                guild,
                "denied",
                self.mexc["uid"],
                staff=staff,
                reason=reason
            )

        # Cleanup pending verification
        await cleanup_verification(guild, self.user_id)

        # Follow-up confirmation to staff
        await interaction.followup.send(
            f"✅ {self.action.capitalize()} submitted and user notified.",
            ephemeral=True
        )


# ================================================================
# VERIFY MODAL
# ================================================================
class VerifyModal(discord.ui.Modal, title="Verify with MEXC"):

    uid = discord.ui.TextInput(
        label="Enter your MEXC UID",
        placeholder="12345678",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):

        discord_id = interaction.user.id

        user_data = get_user(str(discord_id))
        if user_data:
            mexc_uid = user_data["uid"]

            verified_at = datetime.datetime.fromtimestamp(
                user_data["verified_at"],
                tz=datetime.timezone(datetime.timedelta(hours=8))
            )

            formatted_time = format_full_datetime(verified_at)

            await interaction.response.send_message(
                f"✅ **You're already verified!** Your MEXC UID `{mexc_uid}` has been connected since `{formatted_time}`.",
                ephemeral=True
            )
            return

        uid_input = str(self.uid.value).strip()

        cooldown = COOLDOWN_SECONDS
        now = int(datetime.datetime.now(datetime.UTC).timestamp())

        if discord_id in invalid_uid_cooldowns:
            remaining = invalid_uid_cooldowns[discord_id] - now

            if remaining > 0:
                await interaction.response.send_message(
                    "❌ You are still on cooldown. Please try verifying again later.",
                    ephemeral=True
                )
                return

        if discord_id in pending_verifications:
            await interaction.response.send_message(
                "You already have a pending verification request.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        data = await get_referrals()
        referrals = data.get("data", {}).get("resultList") or []

        matched_user = next(
            (u for u in referrals if str(u.get("uid")) == uid_input),
            None
        )

        # =========================================================
        # INVALID UID
        # =========================================================
        if not matched_user:

            cooldown = COOLDOWN_SECONDS
            now = int(datetime.datetime.now(datetime.UTC).timestamp())

            invalid_uid_cooldowns[discord_id] = now + cooldown

            msg = await interaction.followup.send(
                f"❌ The UID `{uid_input}` is not under the Aulsie MEXC referral.\n"
                f"You must wait **{cooldown} seconds** before trying again.",
                ephemeral=True
            )

            remaining = cooldown

            while remaining > 0:
                await asyncio.sleep(1)
                remaining -= 1

                if remaining > 0:
                    await msg.edit(
                        content=(
                            f"❌ The UID `{uid_input}` is not under the Aulsie MEXC referral.\n"
                            f"You must wait **{remaining} seconds** before trying again."
                        )
                    )
                else:
                    await msg.edit(
                        content=(
                            f"❌ The UID `{uid_input}` is not under the Aulsie MEXC referral.\n"
                            f"✅ You can try again now."
                        )
                    )
            return

        mexc_data = extract_mexc_data(matched_user)

        # =========================================================
        # BLOCK UID IF ALREADY VERIFIED BY ANOTHER USER + COOLDOWN
        # =========================================================
        existing_owner = get_user_by_uid(str(mexc_data["uid"]))
        if existing_owner and str(existing_owner["discord_id"]) != str(discord_id):

            cooldown = COOLDOWN_SECONDS
            now = int(datetime.datetime.now(datetime.UTC).timestamp())
            invalid_uid_cooldowns[discord_id] = now + cooldown

            msg = await interaction.followup.send(
                "❌ This MEXC UID is already connected to another Discord account.\n"
                f"You must wait **{cooldown} seconds** before trying again.",
                ephemeral=True
            )

            remaining = cooldown

            while remaining > 0:
                await asyncio.sleep(1)
                remaining -= 1

                if remaining > 0:
                    await msg.edit(
                        content=(
                            "❌ This MEXC UID is already connected to another Discord account.\n"
                            f"You must wait **{remaining} seconds** before trying again."
                        )
                    )
                else:
                    await msg.edit(
                        content=(
                            "❌ This MEXC UID is already connected to another Discord account.\n"
                            "✅ You can try again now."
                        )
                    )
            return

        trading_status = get_trading_status(mexc_data["lastTradeTime"])

        auto_approve = os.getenv("VAUTO_APPROVE", "False").lower() == "true"

        # =========================================================
        # AUTO APPROVE
        # =========================================================
        if auto_approve:

            role = interaction.guild.get_role(VERIFIED_ROLE)

            if role:
                await interaction.user.add_roles(role)

            add_user(
                str(discord_id),
                mexc_data["uid"],
                mexc_data["lastTradeTime"],
                mexc_data["registerTime"],
                mexc_data["nickName"],
                mexc_data["email"],
                trading_status,
                int(datetime.datetime.now(datetime.UTC).timestamp())
            )

            embed = build_staff_embed(
                "Verification Approved (Auto)",
                discord.Color.green(),
                interaction.user,
                None,
                mexc_data
            )

            approved_channel = bot.get_channel(APPROVED_CHANNEL)

            if approved_channel:
                await approved_channel.send(embed=embed)

            # ✅ MANUAL DM FOR AUTO APPROVE (TITLE HAS AUTO)
            dm_embed = discord.Embed(
                title="✅ Verification Approved (Auto)",
                description="Your **Discord UID** is now linked to your **MEXC account.**",
                color=discord.Color.green()
            )

            dm_embed.set_thumbnail(url=interaction.user.display_avatar.url)
            dm_embed.add_field(name="User", value=interaction.user.mention)
            dm_embed.add_field(name="MEXC UID", value=f"`{mexc_data['uid']}`")
            dm_embed.add_field(name="Approved by", value="Aulsie MEXC Referral")
            dm_embed.add_field(name="Trading Status", value=trading_status)
            dm_embed.add_field(
                name="Last Trade",
                value=format_last_trade(mexc_data["lastTradeTime"]),
                inline=True
            )
            dm_embed.add_field(
                name="Timestamp",
                value=f"<t:{int(datetime.datetime.now(datetime.UTC).timestamp())}:F>"
            )

            try:
                await interaction.user.send(embed=dm_embed)
            except discord.Forbidden:
                pass

            await interaction.followup.send(
                "✅ Your MEXC account was found.\nYou were **automatically verified.**",
                ephemeral=True
            )
            return


        # =========================================================
        # SEND TO PENDING
        # =========================================================
        pending_verifications[discord_id] = mexc_data

        embed = discord.Embed(
            title="Pending Verification",
            color=discord.Color.orange()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        embed.add_field(name="User", value=interaction.user.mention)
        embed.add_field(name="MEXC UID", value=f"`{mexc_data['uid']}`")
        embed.add_field(name="MEXC Nickname", value=f"`{mexc_data['nickName']}`")
        embed.add_field(name="Trading Status", value=f"`{trading_status}`")

        embed.add_field(
            name="Last Trade",
            value=f"`{format_last_trade(mexc_data['lastTradeTime'])}`",
            inline=True
        )

        embed.add_field(
            name="MEXC Registration Time",
            value=f"*{format_full_datetime(datetime.datetime.fromtimestamp(int(mexc_data['registerTime']) / 1000, tz=datetime.UTC))}*",
            inline=True
        )

        embed.add_field(
            name="Timestamp",
            value=f"*{format_full_datetime(manila_now())}*"
        )

        pending_channel = bot.get_channel(PENDING_CHANNEL)

        staff_mentions = " ".join(f"<@&{rid}>" for rid in STAFF_ROLES)

        await pending_channel.send(
            content=f"🔔 {staff_mentions}",
            embed=embed,
            view=StaffReviewView(discord_id, mexc_data),
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

        await interaction.followup.send(
            "Your verification request has been submitted for staff review.",
            ephemeral=True
        )

# ======================================================================
# VC CATEGORY FROM config.json
# ======================================================================

category = bot.get_channel(VC_CATEGORY)

@bot.tree.command(name="vcategory", description="Set the category for verification VCs", guild=GUILD)
@app_commands.describe(category="Category to create verification VCs under")
async def vcat(interaction: discord.Interaction, category: discord.CategoryChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can set the VC category.",
            ephemeral=True
        )
        return

    # Persist to config.json
    write_env("VC_CATEGORY", str(category.id))
    
    # Update global variable
    global VC_CATEGORY
    VC_CATEGORY = category.id

    await interaction.response.send_message(
        f"Verification VCs will now be created under {category.mention}.",
        ephemeral=True
    )






# =========================
# SET PENDING / APPROVED / DENIED CHANNELS
# =========================

async def set_channel(interaction: discord.Interaction, env_key: str, channel: discord.TextChannel, name: str):
    bot_member = interaction.guild.get_member(interaction.client.user.id)

    if bot_member is None:
        await interaction.response.send_message(
            "❌ Could not resolve bot member in the guild.",
            ephemeral=True
        )
        return

    perms = channel.permissions_for(bot_member)

    if not perms.send_messages or not perms.embed_links:
        await interaction.response.send_message(
            f"❌ I do not have permission to send messages or embed links in {channel.mention}.",
            ephemeral=True
        )
        return

    # Persist to config.json
    write_env(env_key, str(channel.id))
    
    # Update global variable
    if env_key == "PENDING_CHANNEL":
        global PENDING_CHANNEL
        PENDING_CHANNEL = channel.id
    elif env_key == "APPROVED_CHANNEL":
        global APPROVED_CHANNEL
        APPROVED_CHANNEL = channel.id
    elif env_key == "DENIED_CHANNEL":
        global DENIED_CHANNEL
        DENIED_CHANNEL = channel.id

    await interaction.response.send_message(
        f"✅ {name} channel set to {channel.mention}.",
        ephemeral=True
    )

@bot.tree.command(name="vsetpending", guild=GUILD)
async def vsetpending(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    await set_channel(interaction, "PENDING_CHANNEL", channel, "Pending")

@bot.tree.command(name="vsetapproved", guild=GUILD)
async def vsetapproved(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    await set_channel(interaction, "APPROVED_CHANNEL", channel, "Approved")

@bot.tree.command(name="vsetdenied", guild=GUILD)
async def vsetdenied(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    await set_channel(interaction, "DENIED_CHANNEL", channel, "Denied")
    


@bot.tree.command(name="vaddstaff", description="Add a staff role", guild=GUILD)
@app_commands.describe(role="Role to allow verification approvals")
async def vaddstaff(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    global STAFF_ROLES
    if role.id in STAFF_ROLES:
        await interaction.response.send_message(
            "That role is already a staff role.",
            ephemeral=True
        )
        return

    STAFF_ROLES.append(role.id)
    
    # Persist to config.json
    staff_roles_str = ",".join(str(r) for r in STAFF_ROLES)
    write_env("STAFF_ROLES", staff_roles_str)

    await interaction.response.send_message(
        f"{role.mention} added as verification staff.",
        ephemeral=True
    )

@bot.tree.command(name="vremovestaff", description="Remove a staff role", guild=GUILD)
@app_commands.describe(role="Staff role to remove")
async def vremovestaff(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    global STAFF_ROLES
    if role.id not in STAFF_ROLES:
        await interaction.response.send_message(
            "That role is not a staff role.",
            ephemeral=True
        )
        return

    STAFF_ROLES.remove(role.id)
    
    # Persist to config.json
    staff_roles_str = ",".join(str(r) for r in STAFF_ROLES) if STAFF_ROLES else ""
    write_env("STAFF_ROLES", staff_roles_str)

    await interaction.response.send_message(
        f"{role.mention} removed from verification staff.",
        ephemeral=True
    )


# =========================
# /vcooldown command
# =========================
@bot.tree.command(
    name="vcooldown",
    description="Set invalid UID cooldown in seconds",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(seconds="Cooldown time in seconds")
async def vsetcooldown(interaction: discord.Interaction, seconds: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    seconds = max(1, seconds)

    # Persist to config.json
    write_env("INVALID_UID_COOLDOWN", str(seconds))
    
    # Update global variable
    global INVALID_UID_COOLDOWN, COOLDOWN_SECONDS
    INVALID_UID_COOLDOWN = seconds
    COOLDOWN_SECONDS = seconds

    await interaction.response.send_message(
        f"MEXC UID verification cooldown set to `{seconds}` seconds.",
        ephemeral=True
    )

# =========================
# /verify command
# =========================
@bot.tree.command(name="verify", description="Verify your MEXC UID", guild=GUILD)
async def verify(interaction: discord.Interaction):

    user_data = get_user(str(interaction.user.id))

    if user_data:
        mexc_uid = user_data["uid"]
        # convert verified_at to Manila time
        verified_at = datetime.datetime.fromtimestamp(
            user_data["verified_at"], tz=datetime.timezone(datetime.timedelta(hours=8))
        )
        formatted_time = format_full_datetime(verified_at)  # your existing formatter

        await interaction.response.send_message(
            f"✅ **You're already verified!** Your MEXC UID `{mexc_uid}` has been connected since `{formatted_time}`.",
            ephemeral=True
        )
        return

    # show the verification modal
    await interaction.response.send_modal(VerifyModal())


# =========================
# /vsetactive command
# =========================

@bot.tree.command(name="vactive", description="Set active trading period", guild=GUILD)
@app_commands.describe(span="Choose time span", value="Number of periods")
@app_commands.choices(span=[
    app_commands.Choice(name="Day", value="day"),
    app_commands.Choice(name="Week", value="week"),
    app_commands.Choice(name="Month", value="month"),
    app_commands.Choice(name="Year", value="year")
])
async def vsetactive(interaction: discord.Interaction, span: app_commands.Choice[str], value: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    span_value = span.value

    if span_value == "day":
        seconds = value * 86400
    elif span_value == "week":
        seconds = value * 7 * 86400
    elif span_value == "month":
        seconds = value * 30 * 86400
    elif span_value == "year":
        seconds = value * 365 * 86400

    # Persist to config.json
    write_env("ACTIVE_SPAN", span_value)
    write_env("ACTIVE_VALUE", str(value))
    write_env("ACTIVE_PERIOD", str(seconds))

    # Update global variables
    global ACTIVE_PERIOD, ACTIVE_SPAN, ACTIVE_VALUE

    ACTIVE_PERIOD = seconds
    ACTIVE_SPAN = span_value
    ACTIVE_VALUE = value

    await interaction.response.send_message(
        f"Active trading period set to **{value} {span_value}(s)**.",
        ephemeral=True
    )


def trading_status(last_trade_timestamp: int) -> str:
    """
    last_trade_timestamp: milliseconds since epoch from MEXC API
    Returns "Active" or "Inactive"
    """

    active_period = ACTIVE_PERIOD  # default 1 day

    last_trade = datetime.datetime.fromtimestamp(last_trade_timestamp / 1000, datetime.UTC)
    now = datetime.datetime.now(datetime.UTC)

    delta = now - last_trade

    if delta.total_seconds() <= active_period:
        return "Active"

    return "Inactive"



# =========================
# /vsetrole command
# =========================
@bot.tree.command(name="vrole", description="Set the verified role", guild=GUILD)
@app_commands.describe(role="Role to give after verification")
async def vsetrole(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    # Persist to config.json
    write_env("VERIFIED_ROLE", str(role.id))
    
    # Update global variable
    global VERIFIED_ROLE
    VERIFIED_ROLE = role.id

    await interaction.response.send_message(
        f"Verified role updated to {role.mention}.",
        ephemeral=True
    )


# =========================
# /vunverify command
# =========================
@bot.tree.command(name="vunverify", description="Remove a user's verification", guild=GUILD)
@app_commands.describe(user="The user to unverify")
async def unverify(interaction: discord.Interaction, user: discord.Member):

    await interaction.response.defer(ephemeral=True)

    if not interaction.user.guild_permissions.administrator:
        await interaction.followup.send(
            "❌ Only **staffs** can use this command.",
            ephemeral=True
        )
        return

    discord_id = str(user.id)

    user_data = get_user(discord_id)

    if not user_data:
        await interaction.followup.send(
            f"{user.mention} is not verified.",
            ephemeral=True
        )
        return

    # =========================
    # REMOVE FROM DATABASE
    # =========================
    remove_user(discord_id)

    # =========================
    # REMOVE VERIFIED ROLE
    # =========================
    role = interaction.guild.get_role(VERIFIED_ROLE)

    if role and role in user.roles:
        try:
            await user.remove_roles(role)
        except discord.Forbidden:
            await interaction.followup.send(
                "Removed verification from database but couldn't remove role.",
                ephemeral=True
            )

    # =========================
    # REMOVE PENDING FLAG
    # =========================
    pending_verifications.pop(user.id, None)

    # =========================
    # DELETE INTERVIEW VC IF EXISTS
    # =========================
    vc_id = user_vc_map.pop(user.id, None)

    if vc_id:
        vc = interaction.guild.get_channel(vc_id)
        if vc:
            try:
                await vc.delete()
            except:
                pass

    # =========================
    # DM USER
    # =========================
    try:
        embed = discord.Embed(
            title="⚠️ Verification Removed",
            description="Your verification has been **removed by an administrator**.\n"
                        "You are no longer verified in this server.",
            color=discord.Color.orange()
        )

        embed.add_field(name="Server", value=f"`{interaction.guild.name}`")

        embed.add_field(
            name="Timestamp",
            value=f"<t:{int(datetime.datetime.now(datetime.UTC).timestamp())}:F>"
        )

        await user.send(embed=embed)

    except discord.Forbidden:
        print(f"Could not DM {user}")

    # =========================
    # FINAL RESPONSE
    # =========================
    await interaction.followup.send(
        f"✅ {user.mention} has been **unverified successfully**.",
        ephemeral=True
    )


# =========================
# PREFIX COMMAND VERSION
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def unverify(ctx, member: discord.Member = None):

    member = member or ctx.author

    user_data = get_user(str(member.id))

    if not user_data:
        await ctx.send(f"{member.mention} is not verified.")
        return

    # Remove from database
    remove_user(str(member.id))

    # Remove pending verification
    pending_verifications.pop(member.id, None)

    # Remove VC
    vc_id = user_vc_map.pop(member.id, None)

    if vc_id:
        vc = ctx.guild.get_channel(vc_id)
        if vc:
            try:
                await vc.delete()
            except:
                pass

    # Remove role
    role_id = role_id = VERIFIED_ROLE

    if role_id:
        role = ctx.guild.get_role(int(role_id))
        if role and role in member.roles:
            try:
                await member.remove_roles(role)
            except:
                pass

    await ctx.send(f"✅ {member.mention} has been unverified.")


# ====================================================
# REFERRAL SYSTEM
# ====================================================

import csv
import io
import datetime


# =============================================================================
# UI CLASSES
# =============================================================================







# ====================================================
# ====================================================
#
#                  ALL REFERRALS VIEW
#
# ====================================================
# ====================================================
class AllReferralsView(discord.ui.View):
    def __init__(self, full_data: list):
        super().__init__(timeout=None)

        # Only keep 50 most recent
        self.full_data = sorted(full_data, key=lambda x: x.get("registerTime") or 0, reverse=True)[:50]

        self.page = 0
        self.per_page = 5  # items per page
        self.update_buttons()

    # ------------------------------------------------
    # Update pagination buttons
    # ------------------------------------------------
    def update_buttons(self):
        total_pages = max(1, (len(self.full_data) - 1) // self.per_page + 1)

        for child in self.children:
            if child.label == "◀ Back":
                child.disabled = self.page == 0
            elif child.label == "Next ▶":
                child.disabled = self.page >= total_pages - 1

    # ------------------------------------------------
    # Build embed page
    # ------------------------------------------------
    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page

        entries = self.full_data[start:end]

        embed = discord.Embed(
            title="📋 All Referrals",
            color=discord.Colour(0xFFFFFF),
            description=(
                f"*Showing the 50 most recent referrals.*\n"
                f"✦ Total Referrals: `{len(self.full_data)}`"
            )
        )

        for entry in entries:
            last_trade = format_time(entry.get("lastTradeTime"))
            embed.add_field(
                name=f"{entry.get('nickName') or 'Unknown'} | UID: {entry.get('uid')}",
                value=(
                    f"Email: `{entry.get('email') or 'Hidden'}`\n"
                    f"Registered: `{format_time(entry.get('registerTime'))}`\n"
                    f"Trading Status: `{get_trading_status(entry.get('lastTradeTime'))}`\n"
                    f"Deposit: `{entry.get('depositAmount')}` | Trading: `{entry.get('tradingAmount')}`\n"
                    f"Commission: `{entry.get('commission')}` | Withdraw: `{entry.get('withdrawAmount')}`\n"
                    f"Asset: `{entry.get('asset')}`"
                ),
                inline=False
            )

        total_pages = max(1, (len(self.full_data) - 1) // self.per_page + 1)
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages} | Showing 50 newest referrals")
        return embed

    # ------------------------------------------------
    # Pagination buttons
    # ------------------------------------------------
    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.success)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        total_pages = max(1, (len(self.full_data) - 1) // self.per_page + 1)
        if self.page < total_pages - 1:
            self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # ------------------------------------------------
    # Export button
    # ------------------------------------------------
    @discord.ui.button(label="📥 Export CSV", style=discord.ButtonStyle.primary)
    async def export_csv(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id

        # Load trusted users from .env
        trusted_users = get_trusted_users_env()

        # Check permissions: server owner, co-owner, or trusted
        is_owner = (user_id == interaction.guild.owner_id)
        is_trusted = str(user_id) in trusted_users

        if not (is_owner or is_trusted):
            await interaction.response.send_message(
                "❌ Only the **server owner or trusted users** can export this CSV.", ephemeral=True
            )
            return

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "#", "MEXC UID", "Nickname", "Email", "Signup Time", "Trading Status",
            "Deposit Amount", "Trading Amount", "Commission", "First Deposit",
            "First Trade", "Last Deposit", "Last Trade", "Withdraw Amount", "Asset"
        ])

        for i, entry in enumerate(self.full_data, start=1):
            last_trade = entry.get("lastTradeTime")
            writer.writerow([
                i,
                entry.get("uid"),
                entry.get("nickName"),
                entry.get("email") or "Hidden",
                format_time(entry.get("registerTime")),
                get_trading_status(last_trade),
                entry.get("depositAmount"),
                entry.get("tradingAmount"),
                entry.get("commission"),
                format_time(entry.get("firstDepositTime")),
                format_time(entry.get("firstTradeTime")),
                format_time(entry.get("lastDepositTime")),
                format_time(last_trade),
                entry.get("withdrawAmount"),
                entry.get("asset")
            ])

        output.seek(0)

        await interaction.response.send_message(
            content=f"📥 Exported **{len(self.full_data)} referrals**.",
            file=discord.File(io.BytesIO(output.getvalue().encode()), filename="all_referrals.csv"),
            ephemeral=True
        )


# ====================================================
# /VREFERRALS COMMAND
# ====================================================
@bot.tree.command(name="vreferrals", description="Show all referrals with pagination", guild=GUILD)
async def vreferrals(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    # ------------------------------------------------
    # ADMIN CHECK
    # ------------------------------------------------
    if not interaction.user.guild_permissions.administrator:
        await interaction.edit_original_response(
            content="❌ Only **administrators** can use this command."
        )
        return

    # ------------------------------------------------
    # Fetch all MEXC referral data
    # ------------------------------------------------
    data = await get_referrals()
    all_users = data.get("data", {}).get("resultList", [])

    if not all_users:
        await interaction.edit_original_response(content="❌ No referral data found.")
        return

    # ------------------------------------------------
    # Show view
    # ------------------------------------------------
    view = AllReferralsView(all_users)
    await interaction.edit_original_response(embed=view.get_embed(), view=view)











# ====================================================
# ====================================================
#
#                  Referral Pagination View
#
# ====================================================
# ====================================================
class ReferralView(discord.ui.View):

    def __init__(self, data: dict, is_verified: bool, db_total_counts: dict):
        super().__init__(timeout=None)

        self.page = 0
        self.per_page = 4
        self.is_verified = is_verified
        self.db_total_counts = db_total_counts

        self.full_data = []

        # Normalize incoming data
        for key, info in data.items():

            last_trade_time = info.get("lastTradeTime")

            entry = {
                "discord_id": info.get("discord_id"),
                "uid": info.get("uid") or key,
                "nickname": info.get("nickname") or "Unknown",
                "email": info.get("email") or "Hidden",
                "signup_time": info.get("signup_time") or "Unknown",
                "lastTradeTime": last_trade_time,
                "trading_status": get_trading_status(last_trade_time),

                "depositAmount": info.get("depositAmount"),
                "tradingAmount": info.get("tradingAmount"),
                "commission": info.get("commission"),
                "firstDepositTime": info.get("firstDepositTime"),
                "firstTradeTime": info.get("firstTradeTime"),
                "lastDepositTime": info.get("lastDepositTime"),
                "withdrawAmount": info.get("withdrawAmount"),
                "asset": info.get("asset"),
                "identification": info.get("identification")
            }

            self.full_data.append(entry)

        # Sort newest referrals first (based on signup timestamp)
        self.full_data.sort(
            key=lambda x: x.get("signup_time") or 0,
            reverse=True
        )

        # Only show newest 50 in UI
        self.data = self.full_data[:50]
        self.total_entries = len(self.full_data)

        self.update_buttons()


    # ------------------------------------------------
    # Update pagination buttons
    # ------------------------------------------------
    def update_buttons(self):

        total_pages = max(1, (len(self.data) - 1) // self.per_page + 1)

        for child in self.children:

            if child.label == "◀ Back":
                child.disabled = self.page == 0

            elif child.label == "Next ▶":
                child.disabled = self.page >= total_pages - 1


    # ------------------------------------------------
    # Build embed page
    # ------------------------------------------------
    def get_embed(self, guild: discord.Guild):

        start = self.page * self.per_page
        end = start + self.per_page

        entries = self.data[start:end]

        embed = discord.Embed(
            title="✅ Verified Referrals" if self.is_verified else "⚠️ Unverified Referrals",
            color=discord.Color.green() if self.is_verified else discord.Color.orange(),
            description=(
                "*Displaying only the 50 most recent referrals.*\n"
                + (
                    f"✦ **Total Verified**: `{self.db_total_counts.get('verified',0)}`"
                    if self.is_verified
                    else f"✦ **Total Unverified**: `{self.db_total_counts.get('unverified',0)}`"
                )
            )
        )

        field_chunks = []
        current_chunk = ""

        for entry in entries:

            last_trade = format_time(entry.get("lastTradeTime"))

            # VERIFIED DISPLAY
            if self.is_verified:

                member = guild.get_member(int(entry.get("discord_id", 0)))
                mention = member.mention if member else f"<@{entry.get('discord_id','Unknown')}>"

                text = (
                    f"\n👤 User: **{mention}**"
                    f"\nDiscord ID: **`{entry.get('discord_id')}`**"
                    f"\nMEXC UID: **`{entry.get('uid')}`**"
                    f"\nNickname: **`{entry.get('nickname')}`**"
                    f"\nEmail: `{entry.get('email')}`"
                    f"\nRegistered: **`{entry.get('signup_time')}`**"
                    f"\nTrading Status: **`{entry.get('trading_status')}`**"
                    f"\nLast Trade: **`{last_trade}`**\n"
                )

            # UNVERIFIED DISPLAY
            else:

                text = (
                    f"\nMEXC UID: **`{entry.get('uid')}`**"
                    f"\nNickname: **`{entry.get('nickname')}`**"
                    f"\nEmail: `{entry.get('email')}`"
                    f"\nRegistered: **`{entry.get('signup_time')}`**"
                    f"\nTrading Status: **`{entry.get('trading_status')}`**"
                    f"\nLast Trade: **`{last_trade}`**\n"
                )

            if len(current_chunk) + len(text) > 1024:
                field_chunks.append(current_chunk)
                current_chunk = text
            else:
                current_chunk += text

        if current_chunk:
            field_chunks.append(current_chunk)

        for chunk in field_chunks:
            embed.add_field(name="\u200b", value=chunk.strip(), inline=False)

        total_pages = max(1, (len(self.data) - 1) // self.per_page + 1)

        embed.set_footer(
            text=f"📄 Page {self.page+1} / {total_pages} | Showing 50 newest of {self.total_entries}"
        )

        return embed


    # ------------------------------------------------
    # Pagination buttons
    # ------------------------------------------------
    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):

        if self.page > 0:
            self.page -= 1

        self.update_buttons()

        await interaction.response.edit_message(
            embed=self.get_embed(interaction.guild),
            view=self
        )


    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.success)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):

        total_pages = max(1, (len(self.data) - 1) // self.per_page + 1)

        if self.page < total_pages - 1:
            self.page += 1

        self.update_buttons()

        await interaction.response.edit_message(
            embed=self.get_embed(interaction.guild),
            view=self
        )


    # ------------------------------------------------
    # Export CSV
    # ------------------------------------------------
    @discord.ui.button(label="📥 Export CSV", style=discord.ButtonStyle.primary)
    async def export_csv(self, interaction: discord.Interaction, button: discord.ui.Button):

        user_id = interaction.user.id

        trusted_users = get_trusted_users_env()

        is_owner = (user_id == interaction.guild.owner_id)
        is_trusted = str(user_id) in trusted_users

        if not (is_owner or is_trusted):
            await interaction.response.send_message(
                "❌ Only the **server owner or trusted users** can export this CSV.",
                ephemeral=True
            )
            return

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "#","Discord ID","MEXC UID","Nickname","Email","Signup Time","Trading Status",
            "Deposit Amount","Trading Amount","Commission",
            "First Deposit","First Trade","Last Deposit","Last Trade",
            "Withdraw Amount","Asset","Identification"
        ])

        for i, entry in enumerate(self.full_data, start=1):

            writer.writerow([
                i,
                f"'{entry.get('discord_id')}",
                f"'{entry.get('uid')}",
                entry.get("nickname"),
                entry.get("email"),
                entry.get("signup_time"),
                entry.get("trading_status"),
                entry.get("depositAmount"),
                entry.get("tradingAmount"),
                entry.get("commission"),
                format_time(entry.get("firstDepositTime")),
                format_time(entry.get("firstTradeTime")),
                format_time(entry.get("lastDepositTime")),
                format_time(entry.get("lastTradeTime")),
                entry.get("withdrawAmount"),
                entry.get("asset"),
                entry.get("identification")
            ])

        output.seek(0)

        await interaction.response.send_message(
            content=f"📥 Exported **{len(self.full_data)} users**.",
            file=discord.File(
                io.BytesIO(output.getvalue().encode()),
                filename="referrals_export.csv"
            ),
            ephemeral=True
        )


# ====================================================
# ALL REFERRALS VIEW
# ====================================================
class AllReferralsView(discord.ui.View):
    def __init__(self, full_data: list):
        super().__init__(timeout=None)

        # Only keep 50 most recent
        self.full_data = sorted(full_data, key=lambda x: x.get("registerTime") or 0, reverse=True)[:50]

        self.page = 0
        self.per_page = 4  # items per page
        self.update_buttons()

    # ------------------------------------------------
    # Update pagination buttons
    # ------------------------------------------------
    def update_buttons(self):
        total_pages = max(1, (len(self.full_data) - 1) // self.per_page + 1)

        for child in self.children:
            if child.label == "◀ Back":
                child.disabled = self.page == 0
            elif child.label == "Next ▶":
                child.disabled = self.page >= total_pages - 1

    # ------------------------------------------------
    # Build embed page
    # ------------------------------------------------
    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page

        entries = self.full_data[start:end]

        embed = discord.Embed(
            title="📋 All Referrals",
            color=discord.Colour(0xFFFFFF),
            description=(
                f"*Showing the 50 most recent referrals.*\n"
                f"✦ Total Referrals: `{len(self.full_data)}`"
            )
        )

        for entry in entries:
            last_trade = format_time(entry.get("lastTradeTime"))
            embed.add_field(
                name=f"{entry.get('nickName') or 'Unknown'} | UID: {entry.get('uid')}",
                value=(
                    f"Email: `{entry.get('email') or 'Hidden'}`\n"
                    f"Registered: `{format_time(entry.get('registerTime'))}`\n"
                    f"Trading Status: `{get_trading_status(entry.get('lastTradeTime'))}`\n"
                    f"Deposit: `{entry.get('depositAmount')}` | Trading: `{entry.get('tradingAmount')}`\n"
                    f"Commission: `{entry.get('commission')}` | Withdraw: `{entry.get('withdrawAmount')}`\n"
                    f"Asset: `{entry.get('asset')}`"
                ),
                inline=False
            )

        total_pages = max(1, (len(self.full_data) - 1) // self.per_page + 1)
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages} | Showing 50 newest referrals")
        return embed

    # ------------------------------------------------
    # Pagination buttons
    # ------------------------------------------------
    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.success)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        total_pages = max(1, (len(self.full_data) - 1) // self.per_page + 1)
        if self.page < total_pages - 1:
            self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # ------------------------------------------------
    # Export button
    # ------------------------------------------------
    @discord.ui.button(label="📥 Export CSV", style=discord.ButtonStyle.primary)
    async def export_csv(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only server owner or trusted users can export
        user_id = interaction.user.id
        trusted_users = get_trusted_users_env()  # Reads TRUSTED from .env

        is_owner = (user_id == interaction.guild.owner_id)
        is_trusted = str(user_id) in trusted_users

        if not (is_owner or is_trusted):
            await interaction.response.send_message(
                "❌ Only the **server owner or trusted users** can export this CSV.", ephemeral=True
            )
            return

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "#", "MEXC UID", "Nickname", "Email", "Signup Time", "Trading Status",
            "Deposit Amount", "Trading Amount", "Commission", "First Deposit",
            "First Trade", "Last Deposit", "Last Trade", "Withdraw Amount", "Asset"
        ])

        for i, entry in enumerate(self.full_data, start=1):
            last_trade = entry.get("lastTradeTime")
            writer.writerow([
                i,
                entry.get("uid"),
                entry.get("nickName"),
                entry.get("email") or "Hidden",
                format_time(entry.get("registerTime")),
                get_trading_status(last_trade),
                entry.get("depositAmount"),
                entry.get("tradingAmount"),
                entry.get("commission"),
                format_time(entry.get("firstDepositTime")),
                format_time(entry.get("firstTradeTime")),
                format_time(entry.get("lastDepositTime")),
                format_time(last_trade),
                entry.get("withdrawAmount"),
                entry.get("asset")
            ])

        output.seek(0)

        await interaction.response.send_message(
            content=f"📥 Exported **{len(self.full_data)} referrals**.",
            file=discord.File(io.BytesIO(output.getvalue().encode()), filename="all_referrals.csv"),
            ephemeral=True
        )

# ====================================================
# /VREFERRAL COMMAND
# ====================================================

@bot.tree.command(name="vreferral", description="Show referral list", guild=GUILD)
@app_commands.describe(status="Choose which referrals to display")
@app_commands.choices(status=[
    app_commands.Choice(name="Verified", value="verified"),
    app_commands.Choice(name="Unverified", value="unverified")
])
async def vreflist(interaction: discord.Interaction, status: app_commands.Choice[str]):

    await interaction.response.defer(ephemeral=True)

    # ------------------------------------------------
    # STAFF PERMISSION CHECK
    # ------------------------------------------------
    staff_roles = os.getenv("STAFF_ROLES", "")

    allowed_roles = []
    if staff_roles:
        allowed_roles = [int(r) for r in staff_roles.split(",") if r]

    if (
        not interaction.user.guild_permissions.administrator
        and not any(role.id in allowed_roles for role in interaction.user.roles)
    ):
        await interaction.followup.send(
            "❌ You do not have permission to use this command.",
            ephemeral=True
        )
        return

    # ------------------------------------------------
    # LOAD VERIFIED USERS FROM DATABASE
    # ------------------------------------------------
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT discord_id, mexc_uid FROM users")

    rows = c.fetchall()
    conn.close()

    verified_users = {}
    verified_uids = set()

    for discord_id, uid in rows:

        uid = str(uid)
        discord_id = str(discord_id)

        verified_uids.add(uid)

        verified_users[discord_id] = {
            "discord_id": discord_id,
            "uid": uid
        }

    # ------------------------------------------------
    # FETCH MEXC REFERRAL DATA
    # ------------------------------------------------
    data = await get_referrals()

    mexc_users = {}

    if data.get("success") and "resultList" in data.get("data", {}):

        for user in data["data"]["resultList"]:

            uid = str(user.get("uid"))

            mexc_users[uid] = {

                "uid": uid,
                "nickname": user.get("nickName") or "Unknown",
                "email": user.get("email") or "Hidden",
                "signup_time": format_time(user.get("registerTime")),
                "lastTradeTime": int(user["lastTradeTime"]) if user.get("lastTradeTime") else None,

                "depositAmount": user.get("depositAmount"),
                "tradingAmount": user.get("tradingAmount"),
                "commission": user.get("commission"),
                "firstDepositTime": user.get("firstDepositTime"),
                "firstTradeTime": user.get("firstTradeTime"),
                "lastDepositTime": user.get("lastDepositTime"),
                "withdrawAmount": user.get("withdrawAmount"),
                "asset": user.get("asset"),
                "identification": user.get("identification")
            }

    # ------------------------------------------------
    # MERGE VERIFIED USERS WITH MEXC DATA
    # ------------------------------------------------
    for discord_id, info in verified_users.items():

        uid = info["uid"]
        mexc_info = mexc_users.get(uid)

        if mexc_info:
            info.update(mexc_info)
        else:
            info.update({
                "nickname": "Unknown",
                "email": "Hidden",
                "signup_time": "Unknown",
                "lastTradeTime": None
            })

    # ------------------------------------------------
    # BUILD UNVERIFIED LIST
    # ------------------------------------------------
    unverified_data = {
        uid: info for uid, info in mexc_users.items()
        if uid not in verified_uids
    }

    db_total_counts = {
        "verified": len(verified_users),
        "unverified": len(unverified_data)
    }

    # ------------------------------------------------
    # DISPLAY RESULTS
    # ------------------------------------------------
    if status.value == "verified":

        if not verified_users:
            await interaction.edit_original_response(
                content="No verified users found."
            )
            return

        view = ReferralView(
            verified_users,
            is_verified=True,
            db_total_counts=db_total_counts
        )

    else:

        if not unverified_data:
            await interaction.edit_original_response(
                content="No unverified referrals found."
            )
            return

        view = ReferralView(
            unverified_data,
            is_verified=False,
            db_total_counts=db_total_counts
        )

    await interaction.edit_original_response(
        embed=view.get_embed(interaction.guild),
        view=view
    )





# ====================================================
# /VREFERRALEXPORT
# ====================================================
@bot.tree.command(
    name="vreferralexport",
    description="Export all MEXC referral data as CSV",
    guild=GUILD
)
async def vreferralexport(interaction: discord.Interaction):

    user_id = interaction.user.id
    trusted_users = get_trusted_users_env()  # Reads TRUSTED from .env

    if not (user_id == interaction.guild.owner_id or str(user_id) in trusted_users):
        await interaction.response.send_message(
            "❌ Only the **server owner or trusted users** can export referral data.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        # ------------------------------------------------
        # FETCH ALL MEXC REFERRAL DATA
        # ------------------------------------------------
        data = await get_referrals()

        all_users = data.get("data", {}).get("resultList", [])

        if not all_users:
            await interaction.edit_original_response(
                content="❌ No referral data found."
            )
            return

        # ------------------------------------------------
        # BUILD CSV
        # ------------------------------------------------
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "#",
            "MEXC UID",
            "Nickname",
            "Email",
            "Signup Time",
            "Trading Status",
            "Deposit Amount",
            "Trading Amount",
            "Commission",
            "First Deposit",
            "First Trade",
            "Last Deposit",
            "Last Trade",
            "Withdraw Amount",
            "Asset"
        ])

        for i, user in enumerate(all_users, start=1):
            last_trade = user.get("lastTradeTime")

            writer.writerow([
                i,
                user.get("uid"),
                user.get("nickName"),
                user.get("email") or "Hidden",
                format_time(user.get("registerTime")),
                get_trading_status(last_trade),
                user.get("depositAmount"),
                user.get("tradingAmount"),
                user.get("commission"),
                format_time(user.get("firstDepositTime")),
                format_time(user.get("firstTradeTime")),
                format_time(user.get("lastDepositTime")),
                format_time(last_trade),
                user.get("withdrawAmount"),
                user.get("asset")
            ])

        output.seek(0)

        # ------------------------------------------------
        # SEND FILE
        # ------------------------------------------------
        await interaction.edit_original_response(
            content=f"📥 Exported **{len(all_users)} referrals**.",
            attachments=[
                discord.File(
                    io.BytesIO(output.getvalue().encode()),
                    filename="mexc_referrals_export.csv"
                )
            ]
        )

    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Export failed:\n`{e}`"
        )



# ====================================================
# /VREFERRALINFO COMMAND
# ====================================================

@bot.tree.command(
    name="vreferralinfo",
    description="Check verification status of a user",
    guild=GUILD
)
@app_commands.describe(user="The user to check")
async def vreferralinfo(interaction: discord.Interaction, user: discord.Member):

    user_id = interaction.user.id
    trusted_users = get_trusted_users_env()  # Reads TRUSTED from .env

    if not (user_id == interaction.guild.owner_id or str(user_id) in trusted_users):
        await interaction.response.send_message(
            "❌ Only the **server owner or trusted users** can use this command.",
            ephemeral=True
        )
        return

    discord_id = str(user.id)

    user_data = get_user(discord_id)

    if not user_data:

        await interaction.response.send_message(
            f"{user.mention} is not verified yet.",
            ephemeral=True
        )
        return

    uid = str(user_data.get("uid"))

    # ------------------------------------------------
    # FETCH MEXC DATA
    # ------------------------------------------------
    data = await get_referrals()

    mexc_user = None

    if data.get("success") and "resultList" in data.get("data", {}):

        for u in data["data"]["resultList"]:

            if str(u.get("uid")) == uid:
                mexc_user = u
                break

    if not mexc_user:

        await interaction.response.send_message(
            "MEXC user not found.",
            ephemeral=True
        )
        return

    # ------------------------------------------------
    # CALCULATE STATUS
    # ------------------------------------------------
    mexc_user["status"] = get_trading_status(
        mexc_user.get("lastTradeTime")
    )

    mexc_user["uid"] = uid

    # ------------------------------------------------
    # SHOW PAGINATED VIEW
    # ------------------------------------------------
    view = VCheckView(user, mexc_user)

    await interaction.response.send_message(
        embed=view.build_page(),
        view=view,
        ephemeral=True
    )



# ====================================================
# VERIFIED USER CHECK VIEW
# ====================================================
class VCheckView(discord.ui.View):

    def __init__(self, user, data):

        super().__init__(timeout=None)

        self.user = user
        self.data = data
        self.page = 0

        self.update_buttons()


    def update_buttons(self):

        self.back.disabled = self.page == 0
        self.next.disabled = self.page == 2


    def build_page(self):

        d = self.data

        embed = discord.Embed(
            title=f"Verified User ✔ @{self.user.display_name}",
            color=discord.Color.from_str("0xFFFACD")
        )

        if self.page == 0:

            embed.add_field(name="User", value=self.user.mention, inline=False)
            embed.add_field(name="💬 Discord ID", value=f"`{self.user.id}`", inline=False)
            embed.add_field(name="🆔 MEXC UID", value=f"`{d.get('uid')}`", inline=False)
            embed.add_field(name="🏷️ MEXC Nickname", value=f"`{d.get('nickName')}`", inline=False)
            embed.add_field(name="📧 Email", value=f"`{d.get('email')}`", inline=False)
            embed.add_field(name="⏱️ Registration Time", value=f"`{format_time(d.get('registerTime'))}`", inline=False)
            embed.add_field(name="💹 Trading Status", value=f"`{d.get('status')}`", inline=False)

            embed.set_footer(text="Page 1 / 3")

        elif self.page == 1:

            embed.add_field(name="📈 First Trade Time", value=f"`{format_time(d.get('firstTradeTime'))}`", inline=False)
            embed.add_field(name="📊 Last Trade Time", value=f"`{format_time(d.get('lastTradeTime'))}`", inline=False)
            embed.add_field(name="🏦 First Deposit Time", value=f"`{format_time(d.get('firstDepositTime'))}`", inline=False)
            embed.add_field(name="🏧 Last Deposit Time", value=f"`{format_time(d.get('lastDepositTime'))}`", inline=False)

            embed.set_footer(text="Page 2 / 3")

        else:

            embed.add_field(name="💰 Deposit Amount", value=f"`{d.get('depositAmount')}`", inline=False)
            embed.add_field(name="💸 Withdraw Amount", value=f"`{d.get('withdrawAmount')}`", inline=False)
            embed.add_field(name="💵 Commission", value=f"`{d.get('commission')}`", inline=False)
            embed.add_field(name="🪙 Asset", value=f"`{d.get('asset')}`", inline=False)

            embed.set_footer(text="Page 3 / 3")

        return embed


    async def update(self, interaction):

        self.update_buttons()

        await interaction.response.edit_message(
            embed=self.build_page(),
            view=self
        )


    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):

        if self.page > 0:
            self.page -= 1

        await self.update(interaction)


    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):

        if self.page < 2:
            self.page += 1

        await self.update(interaction)




# ====================================================
# /vcheck COMMAND (Staff Verification Check)
# ====================================================
@bot.tree.command(
    name="vcheck",
    description="Check a user's basic verification status",
    guild=GUILD
)
@app_commands.describe(user="User to check")
async def vcheck(interaction: discord.Interaction, user: discord.Member):

    await interaction.response.defer(ephemeral=True)

    # --------------------------------
    # STAFF PERMISSION CHECK
    # --------------------------------
    staff_roles = os.getenv("STAFF_ROLES", "")
    allowed_roles = [int(r) for r in staff_roles.split(",")] if staff_roles else []

    if (
        not interaction.user.guild_permissions.administrator
        and not any(role.id in allowed_roles for role in interaction.user.roles)
    ):
        await interaction.followup.send(
            "❌ You do not have permission to use this command.",
            ephemeral=True
        )
        return

    # --------------------------------
    # GET DATABASE USER
    # --------------------------------
    user_data = get_user(str(user.id))

    if not user_data:
        await interaction.followup.send(
            f"{user.mention} is **not verified**.",
            ephemeral=True
        )
        return

    uid = str(user_data.get("uid"))
    verification_time = user_data.get("verification_time") or "Unknown"

    # --------------------------------
    # FETCH MEXC DATA
    # --------------------------------
    data = await get_referrals()

    mexc_user = None

    if data.get("success"):
        for u in data.get("data", {}).get("resultList", []):
            if str(u.get("uid")) == uid:
                mexc_user = u
                break

    if not mexc_user:
        await interaction.followup.send(
            "MEXC user data could not be found.",
            ephemeral=True
        )
        return

    # --------------------------------
    # DETERMINE TRADING STATUS
    # --------------------------------
    last_trade = mexc_user.get("lastTradeTime")
    status = get_trading_status(last_trade)

    register_time = mexc_user.get("registerTime")

    register_timestamp = (
        f"<t:{int(register_time)//1000}:F>"
        if register_time else "Unknown"
    )

    verified_at = user_data.get("verified_at")

    if verified_at:
        verification_time = datetime.datetime.fromtimestamp(
            verified_at,
            datetime.UTC
        ).astimezone().strftime("%Y-%m-%d %I:%M %p").lstrip("0")
    else:
        verification_time = "Unknown"

    # --------------------------------
    # BUILD RESULT EMBED
    # --------------------------------
    embed = discord.Embed(
        title="Verified! ✅",
        description="This user is **verified** and synced with their MEXC account.",
        color=discord.Color.green()
    )

    embed.add_field(
        name="👤 User",
        value=user.mention,
        inline=False
    )

    embed.add_field(
        name="🆔 MEXC UID",
        value=f"`{uid}`",
        inline=True
    )

    embed.add_field(
        name="🏷️ MEXC Nickname",
        value=f"`{mexc_user.get('nickName') or 'Unknown'}`",
        inline=True
    )

    embed.add_field(
        name="💹 Trading Status",
        value=f"`{status}`",
        inline=True
    )

    embed.add_field(
        name="📅 MEXC Registration",
        value=register_timestamp,
        inline=True
    )

    embed.add_field(
        name="🕒 Verification Timestamp",
        value=f"`{verification_time}`",
        inline=True
    )

    embed.set_footer(text="MEXC Verification System")

    await interaction.followup.send(embed=embed, ephemeral=True)




@bot.tree.command(name="vinfo", description="Show verification system configuration", guild=GUILD)
async def vinfo(interaction: discord.Interaction):
    # ADMIN ONLY CHECK
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    guild = interaction.guild

    def ch(channel_id):
        if not channel_id or channel_id == 0:
            return "None"
        c = guild.get_channel(int(channel_id))
        return c.mention if c else "None"

    def role(role_id):
        if not role_id or role_id == 0:
            return "None"
        r = guild.get_role(int(role_id))
        return r.mention if r else "None"
        
    def get_category_name(category_id):
        if not category_id or category_id == 0:
            return "None"
        c = guild.get_channel(int(category_id))
        return c.name if c else "None"

    # Get values from .env directly
    staff_role_ids = os.getenv("STAFF_ROLES", "").split(",")
    staff_roles_list = []
    for rid in staff_role_ids:
        if rid.strip():
            role_mention = role(rid.strip())
            if role_mention != "None":
                staff_roles_list.append(f"• {role_mention}")
    
    # Format as bullet points or comma-separated
    if staff_roles_list:
        staff_roles = "\n".join(staff_roles_list)
    else:
        staff_roles = "None"

    verified_role = role(os.getenv("VERIFIED_ROLE", 0))
    verify_channel = ch(os.getenv("VERIFICATION_CHANNEL", 0))
    pending_channel = ch(os.getenv("PENDING_CHANNEL", 0))
    approved_channel = ch(os.getenv("APPROVED_CHANNEL", 0))
    denied_channel = ch(os.getenv("DENIED_CHANNEL", 0))
    category_name = get_category_name(os.getenv("VC_CATEGORY", 0))

    cooldown = os.getenv("INVALID_UID_COOLDOWN", "300")
    
    # Check API status with detailed info
    api_key = os.getenv("MEXC_API_KEY")
    api_secret = os.getenv("MEXC_SECRET")
    
    if api_key and api_secret:
        # Test the API
        is_valid, message = await test_mexc_api(api_key, api_secret)
        
        if is_valid:
            # Get additional info about the API data
            try:
                data = await get_referrals()
                if data and data.get("success"):
                    referrals = data.get("data", {}).get("resultList", [])
                    if referrals:
                        sample = referrals[0]
                        has_uid = "uid" in sample
                        has_register = "registerTime" in sample
                        if has_uid and has_register:
                            api_status = "✅ Working (full data)"
                        else:
                            api_status = "✅ Working (limited data)"
                    else:
                        api_status = "✅ Working (no referrals)"
                else:
                    api_status = "✅ Working"
            except:
                api_status = "✅ Working"
        else:
            api_status = f"❌ Not Working"
    else:
        api_status = "⚠️ Not Configured"

    span = ACTIVE_SPAN
    value = ACTIVE_VALUE
    active_span = f"{value} {span}(s)"

    vdmsg_enabled = os.getenv("VDMSG_ENABLED", "False")
    auto_approve = os.getenv("VAUTO_APPROVE", "False")

    embed = discord.Embed(
        title="🔧 Verification System Configuration",
        color=discord.Color.blurple()
    )

    embed.description = f"""
━━━━━━━━━━━━━━━━━━━━━━
**MEXC API:** `{api_status}`
━━━━━━━━━━━━━━━━━━━━━━
**📍 CHANNELS**
**Verify Channel:** {verify_channel}
**Pending Channel:** {pending_channel}
**Approved Channel:** {approved_channel}
**Denied Channel:** {denied_channel}
**VC Category:** `#{category_name}`
━━━━━━━━━━━━━━━━━━━━━━
**👥 ROLES**
**Verified Role:** {verified_role}
**Staff Roles:**
{staff_roles}
━━━━━━━━━━━━━━━━━━━━━━
**⚙️ SETTINGS**
**Verify Cooldown:** `{cooldown} seconds`
**Active Trading Span:** `{active_span}`
**AutoApprove:** `{auto_approve}`
**VDelete Messages:** `{vdmsg_enabled}`
"""

    await interaction.response.send_message(embed=embed, ephemeral=True)





async def test_mexc_api(api_key, api_secret):
    """Test if MEXC API credentials are valid by checking for uid and registerTime keywords"""
    if not api_key or not api_secret:
        return False, "API credentials not provided"
        
    async with aiohttp.ClientSession() as session:
        try:
            # Get server time
            async with session.get("https://api.mexc.com/api/v3/time") as resp:
                server_data = await resp.json()
                server_time = server_data.get("serverTime")

            if not server_time:
                return False, "Failed to get server time"

            timestamp = str(server_time)
            recv_window = "5000"
            query = f"timestamp={timestamp}&recvWindow={recv_window}"

            signature = hmac.new(
                api_secret.encode(),
                query.encode(),
                hashlib.sha256
            ).hexdigest()

            url = f"https://api.mexc.com/api/v3/rebate/affiliate/referral?{query}&signature={signature}"
            headers = {"X-MEXC-APIKEY": api_key}

            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                
                # Check if API is valid by looking for uid and registerTime
                if resp.status == 200:
                    # Look for referrals list
                    referrals = []
                    if isinstance(data, dict):
                        # Check different possible response structures
                        if "data" in data and isinstance(data["data"], dict):
                            referrals = data["data"].get("resultList", [])
                        elif "resultList" in data:
                            referrals = data.get("resultList", [])
                        elif isinstance(data, list):
                            referrals = data
                    
                    # If we have at least one referral, check for keywords
                    if referrals and len(referrals) > 0:
                        first_user = referrals[0]
                        if isinstance(first_user, dict):
                            has_uid = "uid" in first_user
                            has_register_time = "registerTime" in first_user
                            
                            if has_uid and has_register_time:
                                return True, "API is valid (found uid and registerTime)"
                            elif has_uid or has_register_time:
                                return True, "API is valid (partial data)"
                    
                    # Even if no referrals, if we got a successful response with no error, it's valid
                    if isinstance(data, dict):
                        if "code" not in data or data["code"] == 200:
                            return True, "API is valid (no referrals yet)"
                    
                    return True, "API is valid"
                else:
                    error_msg = data.get("msg", "Unknown error") if isinstance(data, dict) else f"HTTP {resp.status}"
                    return False, error_msg

        except Exception as e:
            return False, str(e)





class MEXCReplaceView(discord.ui.View):
    def __init__(self, current_api_key=None, current_api_secret=None):
        super().__init__(timeout=None)
        self.current_api_key = current_api_key
        self.current_api_secret = current_api_secret

    @discord.ui.button(label="Replace API", style=discord.ButtonStyle.red)
    async def replace_api(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = security_warning_embed()
        await interaction.response.edit_message(
            embed=embed,
            view=MEXCWarningView()
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.gray)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Cancelled.",
            embed=None,
            view=None
        )


@bot.tree.command(
    name="vsetmexcapi",
    description="Set the MEXC API key and secret",
    guild=GUILD
)
async def setmexcapi(interaction: discord.Interaction):
    user_id = interaction.user.id
    trusted_users = get_trusted_users_env()  # Reads TRUSTED from .env

    if not (user_id == interaction.guild.owner_id or str(user_id) in trusted_users):
        await interaction.response.send_message(
            "❌ Only the **server owner or trusted users** can use this command.",
            ephemeral=True
        )
        return

    api_key = os.getenv("MEXC_API_KEY")
    api_secret = os.getenv("MEXC_SECRET")
    api_exists = api_key and api_secret

    if api_exists:
        # Test if the existing API is working
        await interaction.response.defer(ephemeral=True)
        
        is_valid, message = await test_mexc_api(api_key, api_secret)
        
        status = f"✅ **Working**" if is_valid else f"❌ **Not Working**"
        details = f"\n{message}" if not is_valid else ""
        
        embed = discord.Embed(
            title="MEXC API Already Configured",
            description=f"**Current API Status:** {status}{details}",
            color=discord.Color.green() if is_valid else discord.Color.red()
        )
        
        embed.add_field(
            name="What would you like to do?",
            value="You can replace the current API credentials or cancel.",
            inline=False
        )

        await interaction.followup.send(
            embed=embed,
            view=MEXCReplaceView(api_key, api_secret),
            ephemeral=True
        )
    else:
        embed = security_warning_embed()
        await interaction.response.send_message(
            embed=embed,
            view=MEXCWarningView(),
            ephemeral=True
        )

def security_warning_embed():
    return discord.Embed(
        title="⚠ Security Warning",
        description=(
            "Never share your **API Key** and **Secret Key** with anyone.\n\n"
            "To get your API credentials:\n"
            "1. Go to **MEXC → API Management**\n"
            "2. Under **SPOT permissions**, check **View account details**\n"
            "3. This allows the bot to access your **Referrals**.\n\n"
        ),
        color=discord.Color.red()
    )


class MEXCWarningView(discord.ui.View):
    @discord.ui.button(label="Add", style=discord.ButtonStyle.success)
    async def add_api(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MEXCModal())

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Action cancelled.",
            embed=None,
            view=None
        )

class MEXCModal(discord.ui.Modal, title="Enter MEXC API Credentials"):
    api_key = discord.ui.TextInput(
        label="API Key",
        required=True
    )

    secret = discord.ui.TextInput(
        label="Secret Key",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Confirm API Credentials",
                description="**Are you sure you want to save these API credentials?** \n\n"
                        "This will allow the bot to access your referral information and provide the following features:\n\n"
                        "✅ **Verify Discord users** by checking if their MEXC UID is under your referral\n"
                        "✅ **Link Discord IDs to MEXC UIDs** for permanent verification tracking\n"
                        "✅ **View user information** including:\n"
                        "   • MEXC UID and nickname\n"
                        "   • Account registration date and time\n"
                        "   • Last trade timestamp...\n"
                        "✅ **Create interview voice channels** for manual verification sessions\n"
                        "✅ **Auto-approve users** based on referral status (optional toggle)\n"
                        "✅ **Track verified vs unverified referrals** in your server\n"
                        "✅ **Check user activity** based on their last trade time\n\n"
                        "⚠️ **Required API Permissions:**\n"
                        "• SPOT → View account details (read-only)\n"
                        "• No trading or withdrawal permissions needed",
                color=discord.Color.orange()
            ),
            view=MEXCConfirmView(self.api_key.value, self.secret.value),
            ephemeral=True
        )


class MEXCConfirmView(discord.ui.View):
    def __init__(self, api_key, secret):
        super().__init__()
        self.api_key = api_key
        self.secret = secret

    @discord.ui.button(label="Save", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Test the API before saving
        await interaction.response.defer(ephemeral=True)
        
        is_valid, message = await test_mexc_api(self.api_key, self.secret)
        
        if is_valid:
            write_env("MEXC_API_KEY", self.api_key)
            write_env("MEXC_SECRET", self.secret)

            # reload environment values so the updated keys are available immediately
            load_dotenv(override=True)
            
            # Update global variables
            global API_KEY, API_SECRET
            API_KEY = self.api_key
            API_SECRET = self.secret

            embed = discord.Embed(
                title="✅ MEXC API Saved Successfully",
                description="Your API credentials were saved to config.json successfully.\n\n**Status:** API is working correctly!",
                color=discord.Color.green()
            )

            await interaction.followup.edit_message(
                interaction.message.id,
                embed=embed,
                view=None
            )
        else:
            embed = discord.Embed(
                title="❌ API Validation Failed",
                description=f"**Error:** {message}\n\nPlease check your API credentials and try again.",
                color=discord.Color.red()
            )
            
            embed.add_field(
                name="Common Issues:",
                value="• API key or secret is incorrect\n• Missing 'View account details' permission\n• API key doesn't have referral access",
                inline=False
            )

            await interaction.followup.edit_message(
                interaction.message.id,
                embed=embed,
                view=None
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="API setup cancelled.",
            embed=None,
            view=None
        )

# =========================
# HELP EMBEDS
# =========================

def help_users_embed():
    embed = discord.Embed(
        title="📘 Verification Help — Users",
        color=discord.Color.from_str("0xFFFACD")
    )

    embed.add_field(
        name="👤 User Commands",
        value=
        "`/verify` — Submit your MEXC UID for verification\n"
        "`/vmyinfo` — View your own verification details",
        inline=False
    )

    return embed


def help_staff_embed():
    embed = discord.Embed(
        title="📘 Verification Help — Staff",
        color=discord.Color.from_str("0xFFFACD")
    )

    embed.add_field(
        name="Staff Permissions",
        value=
        "Staff members can manage the verification process:\n"
        "• Review requests in the **Pending channel**\n"
        "• Approve or deny verification requests\n"
        "• Manage verification controls",
        inline=False
    )

    embed.add_field(
        name="Staff Commands",
        value=
        "`/vcheck [user]` — View a user's verification details\n"
        "`/vunverify [user]` — Remove a user's verification\n"
        "`/vreferral [status]` — Shows the latest 50 referrals",
        inline=False
    )

    return embed


def help_admin_embed():
    embed = discord.Embed(
        title="📘 Verification Help — Admin",
        color=discord.Color.from_str("0xFFFACD")
    )

    embed.add_field(
        name="System",
        value=
        "`/vinfo` — Show verification configuration\n"
        "`/vreferral [status]` — Shows the latest 50 referrals.",
        inline=False
    )

    embed.add_field(
        name="Verification Panel & Channels",
        value=
        "`/vchannel` — Set verification channel\n"
        "`/vpanel` — Send verification panel\n"
        "`/vpaneledit` — Edit the most recently created panel.\n"
        "`/vcategory` — Set interview VC category\n"
        "`/vsetpending` — Set pending channel\n"
        "`/vsetapproved` — Set approved channel\n"
        "`/vsetdenied` — Set denied channel",
        inline=False
    )

    embed.add_field(
        name="Roles & Settings",
        value=
        "`/vrole [@role]` — Set verified role\n"
        "`/vaddstaff [@role]` — Add staff role\n"
        "`/vremovestaff [@role]` — Remove staff role\n"
        "`/vcooldown` — Set cooldown\n"
        "`/vdeletetoggle` — Toggle auto deletion\n"
        "`/vactive` — Configure active trading period",
        inline=False
    )

    return embed


def help_owner_embed():
    embed = discord.Embed(
        title="📘 Verification Help — Owner",
        color=discord.Color.from_str("0xFFFACD")
    )

    embed.add_field(
        name="👑 Owner Commands",
        value=(
            "`/vsetmexcapi` — Configure the MEXC API key and secret\n"
            "`/vreferral [Status]` — Shows the latest 50 [verified/unverified] referrals. Export CSV to view all records.\n"
            "`/vreferrals` — Shows the latest 50 referrals. Export CSV to view all records.\n"
            "`/vreferralexport` — Export all MEXC referral data to CSV\n"
            "`/vreferralinfo [user]` — View a user's MEXC details\n"
            "`/vapprovetoggle` — Toggle auto approval\n"
        ),
        inline=False
    )

    return embed


# =========================
# BUTTON VIEW
# =========================

class HelpView(discord.ui.View):

    def __init__(self, user: discord.Member, current="users"):
        super().__init__(timeout=None)

        self.current = current
        self.user = user

        # -------------------------------
        # PERMISSION CHECKS
        # -------------------------------
        is_admin = user.guild_permissions.administrator

        # Server owner
        is_owner = user.guild.owner_id == user.id

        # Trusted users from .env
        trusted_users = get_trusted_users_env()  # returns set of IDs
        is_trusted = str(user.id) in trusted_users

        # Staff roles from environment
        staff_roles = os.getenv("STAFF_ROLES", "")
        allowed_roles = [int(r) for r in staff_roles.split(",") if r] if staff_roles else []
        is_staff = any(role.id in allowed_roles for role in user.roles)

        # Only show buttons if staff/admin/owner/trusted
        if not (is_staff or is_admin or is_owner or is_trusted):
            return


        # USERS BUTTON
        self.users_btn = discord.ui.Button(
            label="Users",
            emoji="👤",
            style=discord.ButtonStyle.primary,
            disabled=current == "users"
        )
        self.users_btn.callback = self.users
        self.add_item(self.users_btn)

        # STAFF BUTTON
        if is_staff or is_admin or is_owner or is_trusted:
            self.staff_btn = discord.ui.Button(
                label="Staff",
                emoji="🛠",
                style=discord.ButtonStyle.secondary,
                disabled=current == "staff"
            )
            self.staff_btn.callback = self.staff
            self.add_item(self.staff_btn)

        # ADMIN BUTTON
        if is_admin or is_owner or is_trusted:
            self.admin_btn = discord.ui.Button(
                label="Admin",
                emoji="🛡",
                style=discord.ButtonStyle.danger,
                disabled=current == "admin"
            )
            self.admin_btn.callback = self.admin
            self.add_item(self.admin_btn)

        # OWNER BUTTON
        if is_owner or is_trusted:
            self.owner_btn = discord.ui.Button(
                label="Owner",
                emoji="👑",
                style=discord.ButtonStyle.success,
                disabled=current == "owner"
            )
            self.owner_btn.callback = self.owner
            self.add_item(self.owner_btn)

    # SECURITY CHECK
    async def interaction_check(self, interaction: discord.Interaction):

        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "❌ You cannot interact with someone else's help menu.",
                ephemeral=True
            )
            return False

        return True

    # USERS
    async def users(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=help_users_embed(),
            view=HelpView(interaction.user, "users")
        )

    # STAFF
    async def staff(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=help_staff_embed(),
            view=HelpView(interaction.user, "staff")
        )

    # ADMIN
    async def admin(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=help_admin_embed(),
            view=HelpView(interaction.user, "admin")
        )

    # OWNER
    async def owner(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=help_owner_embed(),
            view=HelpView(interaction.user, "owner")
        )




# /vchannel command
@bot.tree.command(name="vchannel", description="Set the verification channel", guild=GUILD)
@app_commands.describe(channel="The channel where verification messages appear")
async def setverify(interaction: discord.Interaction, channel: discord.TextChannel):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    # Update runtime variable immediately
    global VERIFICATION_CHANNEL
    VERIFICATION_CHANNEL = channel.id

    # Persist to config.json for future runs
    save_config("VERIFICATION_CHANNEL", channel.id)

    await interaction.response.send_message(
        f"✅ Verification channel set to {channel.mention}",
        ephemeral=True
    )


# /vdmsg command
@bot.tree.command(name="vdeletetoggle", description="Toggle auto-delete of messages in verification channel", guild=GUILD)
async def vdeletetoggle(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only **administrators** can use this command.", ephemeral=True)
        return

    global VDMSG_ENABLED
    new_state = not VDMSG_ENABLED
    VDMSG_ENABLED = new_state

    # Persist to config.json
    write_env("VDMSG_ENABLED", str(new_state))

    status = "enabled" if new_state else "disabled"

    await interaction.response.send_message(
        f"Verification message auto-delete is now **{status}**.",
        ephemeral=True
    )


@bot.tree.command(
    name="vapprovetoggle",
    description="Toggle auto approval for MEXC referrals",
    guild=GUILD
)
async def vapprovetoggle(interaction: discord.Interaction):
    # ADMIN PERMISSION CHECK
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    # Toggle auto_approve (you'll need to add this global variable)
    global AUTO_APPROVE
    current = os.getenv("VAUTO_APPROVE", "False").lower() == "true"
    new_state = not current
    
    # Persist to config.json
    write_env("VAUTO_APPROVE", str(new_state))
    
    # Update for current session
    os.environ["VAUTO_APPROVE"] = str(new_state)

    status = "True" if new_state else "False"

    await interaction.response.send_message(
        f"AutoApprove is now `{status}`",
        ephemeral=True
    )

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    verification_channel = VERIFICATION_CHANNEL
    vdmsg_enabled = VDMSG_ENABLED
    if vdmsg_enabled and message.channel.id == verification_channel:
        if not any(role.id in STAFF_ROLES for role in message.author.roles) \
        and not message.author.guild_permissions.administrator:
            try:
                await message.delete()
            except:
                pass
    await bot.process_commands(message)









def get_trusted_users_env():
    """Return a set of trusted user IDs from config.json or .env fallback."""
    trusted = os.getenv("TRUSTED", "")
    return set(uid.strip() for uid in trusted.split(",") if uid.strip())

def set_trusted_users_env(trusted_set):
    """Overwrite .env TRUSTED value with updated list"""
    # Read the .env file
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    # Build new TRUSTED line
    new_trusted_line = f'TRUSTED={",".join(trusted_set)}\n'
    found = False

    for i, line in enumerate(lines):
        if line.startswith("TRUSTED="):
            lines[i] = new_trusted_line
            found = True
            break

    if not found:
        lines.append(new_trusted_line)

    # Write back to .env
    with open(env_path, "w") as f:
        f.writelines(lines)



@bot.tree.command(name="vtrust", description="Add user to trusted list", guild=GUILD)
@app_commands.describe(user="User to trust")
async def vtrust(interaction: discord.Interaction, user: discord.Member):
    # Only server owner can manage trusted users
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message(
            "❌ Only the **server owner** can manage trusted users.",
            ephemeral=True
        )
        return

    trusted_set = get_trusted_users_env()
    trusted_set.add(str(user.id))
    set_trusted_users_env(trusted_set)

    trusted_list = "\n".join(f"<@{uid}>" for uid in trusted_set) or "None"

    embed = discord.Embed(
        description=f"✅ {user.mention} successfully added to trusted list\n\n**Trusted:**\n{trusted_list}",
        color=discord.Colour.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="vuntrust", description="Remove user from trusted list", guild=GUILD)
@app_commands.describe(user="User to remove")
async def vuntrust(interaction: discord.Interaction, user: discord.Member):
    # Only server owner can manage trusted users
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message(
            "❌ Only the **server owner** can manage trusted users.",
            ephemeral=True
        )
        return

    trusted_set = get_trusted_users_env()
    trusted_set.discard(str(user.id))
    set_trusted_users_env(trusted_set)

    trusted_list = "\n".join(f"<@{uid}>" for uid in trusted_set) or "None"

    embed = discord.Embed(
        description=f"❌ {user.mention} successfully removed from trusted list\n\n**Trusted:**\n{trusted_list}",
        color=discord.Colour.orange()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)





# =========================
# /vhelp command
# =========================

@bot.tree.command(
    name="vhelp",
    description="Show verification bot commands and usage",
    guild=GUILD
)
async def vhelp(interaction: discord.Interaction):

    view = HelpView(interaction.user, "users")

    await interaction.response.send_message(
        embed=help_users_embed(),
        view=view,
        ephemeral=True
    )





# =========================
# UPDATE ENV FUNCTION
# =========================

def update_env(key: str, value: str):
    save_config(key, value)

# =========================
# /vpanel command
# =========================

@bot.tree.command(name="vpanel", description="Create verification panel", guild=GUILD)
@app_commands.checks.has_permissions(administrator=True)
async def vpanel(interaction: discord.Interaction):

    global PANEL_CHANNEL_ID, PANEL_MESSAGE_ID

    verification_channel_id = VERIFICATION_CHANNEL

    if not verification_channel_id:
        await interaction.response.send_message(
            "❌ Verification channel not set. Use `/vchannel` first.",
            ephemeral=True
        )
        return

    channel = bot.get_channel(verification_channel_id) or await bot.fetch_channel(verification_channel_id)

    if not channel:
        await interaction.response.send_message(
            "Cannot access the verification channel. Check bot permissions.",
            ephemeral=True
        )
        return

    perms = channel.permissions_for(channel.guild.me)

    print("Send:", perms.send_messages)
    print("Embed:", perms.embed_links)

    embed = discord.Embed(
        title="Aulsie MEXC Referral Verification",
        description="Press the button below to verify your MEXC account.",
        color=0x2ecc71
    )

    view = VerifyButton()

    try:
        msg = await channel.send(embed=embed, view=view)

        PANEL_CHANNEL_ID = channel.id
        PANEL_MESSAGE_ID = msg.id

        update_env("PANEL_CHANNEL_ID", str(channel.id))
        update_env("PANEL_MESSAGE_ID", str(msg.id))

        await interaction.response.send_message(
            f"✅ Verification panel created in {channel.mention}.",
            ephemeral=True
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "Failed to send verification panel. Bot cannot send messages here.",
            ephemeral=True
        )

    



# =========================
# PANEL EDIT MODAL
# =========================

class PanelEditModal(discord.ui.Modal, title="Edit Verification Panel"):

    def __init__(self, old_title, old_description, old_thumbnail=None, old_image=None):
        super().__init__()

        self.title_input = discord.ui.TextInput(
            label="Title",
            default=old_title,
            max_length=256
        )
        self.add_item(self.title_input)

        self.desc_input = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=old_description,
            max_length=2048
        )
        self.add_item(self.desc_input)

        self.thumb_input = discord.ui.TextInput(
            label="Thumbnail URL (optional)",
            default=old_thumbnail or "",
            required=False
        )
        self.add_item(self.thumb_input)

        self.image_input = discord.ui.TextInput(
            label="Image URL (optional)",
            default=old_image or "",
            required=False
        )
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):

        if not PANEL_CHANNEL_ID or not PANEL_MESSAGE_ID:
            await interaction.response.send_message(
                "❌ Verification panel not configured.",
                ephemeral=True
            )
            return

        channel = bot.get_channel(PANEL_CHANNEL_ID) or await bot.fetch_channel(PANEL_CHANNEL_ID)

        if not channel:
            await interaction.response.send_message(
                "Cannot access the verification channel.",
                ephemeral=True
            )
            return

        try:
            message = await channel.fetch_message(PANEL_MESSAGE_ID)

        except discord.NotFound:
            await interaction.response.send_message(
                "❌ Panel message not found.",
                ephemeral=True
            )
            return

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Missing access to the panel message.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=self.title_input.value,
            description=self.desc_input.value,
            color=0x2ecc71
        )

        if self.thumb_input.value.strip():
            embed.set_thumbnail(url=self.thumb_input.value.strip())

        if self.image_input.value.strip():
            embed.set_image(url=self.image_input.value.strip())

        await message.edit(embed=embed)

        await interaction.response.send_message(
            "✅ Verification panel updated.",
            ephemeral=True
        )

# =========================
# /vpaneledit command
# =========================

@bot.tree.command(name="vpaneledit", description="Edit the verification panel", guild=GUILD)
@app_commands.checks.has_permissions(administrator=True)
async def vpaneledit(interaction: discord.Interaction):

    if not PANEL_CHANNEL_ID or not PANEL_MESSAGE_ID:
        await interaction.response.send_message(
            "❌ Verification panel not configured.",
            ephemeral=True
        )
        return

    channel = bot.get_channel(PANEL_CHANNEL_ID) or await bot.fetch_channel(PANEL_CHANNEL_ID)

    try:
        message = await channel.fetch_message(PANEL_MESSAGE_ID)
    except:
        await interaction.response.send_message(
            "❌ Panel message not found.",
            ephemeral=True
        )
        return

    embed = message.embeds[0] if message.embeds else None

    old_title = embed.title if embed else ""
    old_desc = embed.description if embed else ""
    old_thumb = embed.thumbnail.url if embed and embed.thumbnail else None
    old_image = embed.image.url if embed and embed.image else None

    modal = PanelEditModal(old_title, old_desc, old_thumb, old_image)

    await interaction.response.send_modal(modal)

    
@app_commands.checks.has_permissions(administrator=True)
async def vpanel_edit(interaction: discord.Interaction):

    from database_controller import get_panel

    data = get_panel()

    if not data or not data.get("message_id") or not data.get("channel_id"):
        await interaction.response.send_message("No panel found.", ephemeral=True)
        return

    channel = bot.get_channel(data["channel_id"]) or await bot.fetch_channel(data["channel_id"])

    if not channel:
        await interaction.response.send_message(
            "Cannot access the verification channel. Check bot permissions.",
            ephemeral=True
        )
        return

    try:
        message = await channel.fetch_message(data["message_id"])
    except discord.NotFound:
        await interaction.response.send_message("Panel message not found.", ephemeral=True)
        return
    except discord.Forbidden:
        await interaction.response.send_message("Missing access to the panel message.", ephemeral=True)
        return

    # Get current embed data (old content)
    old_embed = message.embeds[0] if message.embeds else None
    old_title = old_embed.title if old_embed else ""
    old_description = old_embed.description if old_embed else ""
    old_thumbnail = old_embed.thumbnail.url if old_embed and old_embed.thumbnail.url else None
    old_image = old_embed.image.url if old_embed and old_embed.image.url else None

    # Show modal with old data pre-filled
    await interaction.response.send_modal(
        PanelEditModal(old_title, old_description, old_thumbnail, old_image)
    )



# =========================
# /vmyinfo command
# =========================
@bot.tree.command(
    name="vmyinfo",
    description="Check your own verification information",
    guild=GUILD
)
async def vmyinfo(interaction: discord.Interaction):

    user = interaction.user
    discord_id = str(user.id)

    user_data = get_user(discord_id)

    if not user_data:
        await interaction.response.send_message(
            "❌ You are not verified yet.",
            ephemeral=True
        )
        return

    uid = str(user_data.get("uid"))

    data = await get_referrals()

    mexc_user = None

    if data.get("success") and "resultList" in data.get("data", {}):
        for u in data["data"]["resultList"]:
            if str(u.get("uid")) == uid:
                mexc_user = u
                break

    if not mexc_user:
        await interaction.response.send_message(
            "⚠ Your MEXC data could not be found.",
            ephemeral=True
        )
        return

    # determine trading status
    status = "Inactive"
    last_trade = mexc_user.get("lastTradeTime")

    if last_trade:
        try:
            status = trading_status(int(last_trade))
        except:
            status = "Unknown"

    mexc_user["status"] = status
    mexc_user["uid"] = uid

    view = VCheckView(user, mexc_user)

    embed = view.build_page()

    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True
    )


async def cache_cleaner():
    while True:
        now = int(datetime.datetime.now(datetime.UTC).timestamp())

        expired = [
            uid for uid, ts in invalid_uid_cooldowns.items()
            if ts < now
        ]

        for uid in expired:
            invalid_uid_cooldowns.pop(uid, None)

        await asyncio.sleep(600)

async def setup_hook():
    asyncio.create_task(cache_cleaner())

bot.setup_hook = setup_hook


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):

    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ Only **administrators** can use this command.",
            ephemeral=True
        )
        return

    raise error




@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    init_db()
    print("Database initialized")
    
    # keep persistent button working
    bot.add_view(VerifyButton())
    # bot.add_view(WatchCourseView())  
    
    try:
        guild = discord.Object(id=GUILD_ID)

        # Sync the tree to the guild after cleanup
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands to guild.")
        
        # Display all commands
        if synced:
            cmd_names = [f"/{cmd.name}" for cmd in synced]
            
            # Display commands in columns (8 per row for better readability)
            for i in range(0, len(cmd_names), 8):
                row = cmd_names[i:i+8]
                formatted_row = []
                for cmd in row:
                    # Pad commands to 20 characters for alignment
                    formatted_row.append(f"{cmd:<20}")
                print("  " + "".join(formatted_row))
            
            
        else:
            print("⚠️ No commands found!\n")
            
    except Exception as e:
        print(f"Error syncing commands: {e}\n")
    
    # Fetch and display MEXC API data
    data = await get_referrals()
    
    if data and data.get("success"):
        referrals = data.get("data", {}).get("resultList", [])
        
        if referrals:
            all_keys = set()
            for user in referrals:
                if isinstance(user, dict):
                    all_keys.update(user.keys())
            
            # Sort keys for better readability
            sorted_keys = sorted(all_keys)
            
            print("=" * 80)
            print(f"🔑 MEXC API RESPONSE KEYS ({len(sorted_keys)} keys found)")
            
            # Display keys in columns (10 per row)
            for i in range(0, len(sorted_keys), 10):
                row = sorted_keys[i:i+10]
                formatted_row = []
                for key in row:
                    # Pad keys to 15 characters for alignment
                    formatted_row.append(f"{key:<15}")
                print("  " + "".join(formatted_row))
            
        else:
            print("❌ No referral data found in response")
            
    else:
        error_msg = data.get("msg", "Unknown error") if data else "No response"
        print(f"❌ Failed to fetch referrals: {error_msg}")
    
    print("\nBOT IS READY!")


# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)