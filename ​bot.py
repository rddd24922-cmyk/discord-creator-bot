import os
import re
import asyncio
import logging
import calendar
from datetime import datetime, timedelta
import psycopg2
import discord
from discord import app_commands
from discord.ext import commands, tasks

# --- ضبط الإعدادات والمتغيرات ---
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))  # معرف رتبة المشرفين في السيرفر
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID", "0"))  # معرف روم الإدارة للتقارير

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- دوال قاعدة البيانات ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            discord_id BIGINT PRIMARY KEY,
            added_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id BIGINT PRIMARY KEY,
            game_id TEXT UNIQUE,
            registered_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS creator_platforms (
            id SERIAL PRIMARY KEY,
            discord_id BIGINT,
            platform TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TEXT,
            UNIQUE(discord_id, platform)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            discord_id BIGINT,
            video_url TEXT UNIQUE,
            views INTEGER DEFAULT 0,
            submission_month TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- دوال التحقق والحسابات ---
def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    return any(role.id == ADMIN_ROLE_ID for role in getattr(interaction.user, "roles", []))

def is_allowed(discord_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT discord_id FROM whitelist WHERE discord_id = %s", (discord_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def get_user_platforms(discord_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT platform, status FROM creator_platforms WHERE discord_id = %s", (discord_id,))
    res = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in res}

def calculate_rank(views, videos_count):
    if views >= 2000000 and videos_count >= 60:
        return "👑 إمبراطور (مكافأة 24,000 صدفة + تأهل لجائزة طماطم بلس)"
    elif views >= 1000000 and videos_count >= 20:
        return "💎 أيقونة (مكافأة 20,000 صدفة)"
    elif views >= 500000 and videos_count >= 20:
        return "🏆 أسطورة (مكافأة 16,000 صدفة)"
    elif views >= 100000 and videos_count >= 20:
        return "⚡ سلطان (مكافأة 13,000 صدفة)"
    elif views >= 50000 and videos_count >= 20:
        return "🔥 زعيم (مكافأة 9,000 صدفة)"
    elif views >= 15000 and videos_count >= 15:
        return "🎖 قائد (مكافأة 6,000 صدفة)"
    elif views >= 5000 and videos_count >= 12:
        return "⭐ فارس (مكافأة 3,500 صدفة)"
    elif views >= 1500 and videos_count >= 8:
        return "⚔️ محارب (مكافأة 2,000 صدفة)"
    elif views >= 150 and videos_count >= 5:
        return "🛡️ مجند (مكافأة 800 صدفة)"
    elif views >= 50 and videos_count >= 1:
        return "🌱 مبتدئ (مكافأة 200 صدفة)"
    else:
        return "📌 مرشح (لم يستوفِ الحد الأدنى من شروط الرتب)"

def get_next_rank_progress(views, videos_count):
    ranks_tiers = [
        (50, 1, "🌱 مبتدئ"),
        (150, 5, "🛡️ مجند"),
        (1500, 8, "⚔️ محارب"),
        (5000, 12, "⭐ فارس"),
        (15000, 15, "🎖 قائد"),
        (50000, 20, "🔥 زعيم"),
        (100000, 20, "⚡ سلطان"),
        (500000, 20, "🏆 أسطورة"),
        (1000000, 20, "💎 أيقونة"),
        (2000000, 60, "👑 إمبراطور")
    ]
    for req_v, req_c, r_name in ranks_tiers:
        if views < req_v or videos_count < req_c:
            diff_views = max(0, req_v - views)
            diff_videos = max(0, req_c - videos_count)
            return f"🎯 للوصول إلى رتبة ({r_name}) يتبقى لك: **{diff_views:,}** مشاهدة و **{diff_videos}** مقطع."
    return "🎉 لقد وصلت إلى أعلى رتبة نهائية (إمبراطور)! مبروك!"

URL_PATTERNS = {
    "TikTok": r"(https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com)/\S+)",
    "YouTube": r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+)",
    "Instagram": r"(https?://(?:www\.)?instagram\.com/\S+)",
    "Facebook": r"(https?://(?:www\.)?(?:facebook\.com|fb\.watch)/\S+)"
}

# --- الأزرار التفاعلية اعتماد المنصات ---
class PlatformApprovalView(discord.ui.View):
    def __init__(self, discord_id: int, platform: str):
        super().__init__(timeout=None)
        self.discord_id = discord_id
        self.platform = platform

    @discord.ui.button(label="موافقة ✅", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ ليس لديك صلاحيات الإدارة.", ephemeral=True)
            return
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE creator_platforms SET status = 'approved' WHERE discord_id = %s AND platform = %s", (self.discord_id, self.platform))
        conn.commit()
        conn.close()

        await interaction.response.edit_message(content=f"{interaction.message.content}\n\n**الحالة:** تمت الموافقة ✅ بواسطة {interaction.user.mention}", view=None)
        
        user = bot.get_user(self.discord_id)
        if user:
            try:
                await user.send(f"🎉 مبروك! تمت الموافقة على اعتماد منصة **{self.platform}** الخاصة بك.")
            except Exception:
                pass

    @discord.ui.button(label="رفض ❌", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ ليس لديك صلاحيات الإدارة.", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE creator_platforms SET status = 'rejected' WHERE discord_id = %s AND platform = %s", (self.discord_id, self.platform))
        conn.commit()
        conn.close()

        await interaction.response.edit_message(content=f"{interaction.message.content}\n\n**الحالة:** تم الرفض ❌ بواسطة {interaction.user.mention}", view=None)

# --- مهام الخلفية والتقارير الشهرية ---
@tasks.loop(minutes=30)
async def monthly_report_task():
    now = datetime.now()
    last_day = calendar.monthrange(now.year, now.month)[1]
    current_month_str = now.strftime("%Y-%m")
    
    if now.day == last_day and now.hour == 23 and ADMIN_CHANNEL_ID != 0:
        channel = bot.get_channel(ADMIN_CHANNEL_ID)
        if channel:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.game_id, COUNT(s.id), SUM(s.views), u.discord_id
                FROM users u
                LEFT JOIN submissions s ON u.discord_id = s.discord_id AND s.submission_month = %s
                GROUP BY u.discord_id, u.game_id
            """, (current_month_str,))
            creators = cursor.fetchall()
            conn.close()
            
            if creators:
                report = f"🏆 **التقرير الشهري الختامي لصناع المحتوى (شهر {current_month_str}):**\n\n"
                for idx, c in enumerate(creators, 1):
                    v_count, v_views, d_id = c[1] or 0, c[2] or 0, c[3]
                    rank = calculate_rank(v_views, v_count)
                    report += f"{idx}. 🎮 Game ID: `{c[0]}` | <@{d_id}>\n   📹 المقاطع: **{v_count}** | 👁 المشاهدات: **{v_views:,}**\n   🎖 الرتبة: {rank}\n\n"
                await channel.send(report)

@bot.event
async def on_ready():
    logging.info(f"✅ تسجيل الدخول باسم: {bot.user}")
    try:
        synced = await bot.tree.sync()
        logging.info(f"📡 تم مزامنة {len(synced)} أمر Slash Commands بنجاح.")
    except Exception as e:
        logging.error(f"❌ خطأ المزامنة: {e}")
    monthly_report_task.start()

# --- تنفيذ أوامر صناع المحتوى ---

@bot.tree.command(name="register", description="ربط حسابك بمعرّف اللعبة (Game ID)")
@app_commands.describe(game_id="معرّف اللعبة الخاص بك (أرقام فقط)")
async def register(interaction: discord.Interaction, game_id: str):
    if not is_allowed(interaction.user.id) and not is_admin(interaction):
        await interaction.response.send_message("⛔ عذراً، هذا الأمر مخصص لصناع المحتوى المعتمدين فقط.", ephemeral=True)
        return
    if not game_id.isdigit():
        await interaction.response.send_message("❌ يرجى إدخال أرقام صحيحة فقط.", ephemeral=True)
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (discord_id, game_id, registered_at) VALUES (%s, %s, %s)", (interaction.user.id, game_id, now))
        conn.commit()
        await interaction.response.send_message(f"✅ تم ربط حسابك بمعرّف اللعبة: `{game_id}` بنجاح!", ephemeral=True)
    except psycopg2.IntegrityError:
        conn.rollback()
        await interaction.response.send_message("⚠️ أنت مسجل مسبقاً أو أن المعرّف مستخدم من لاعب آخر.", ephemeral=True)
    finally:
        conn.close()

@bot.tree.command(name="mystats", description="عرض مقاطعي وإحصائياتي لهذا الشهر")
async def mystats(interaction: discord.Interaction):
    d_id = interaction.user.id
    current_month = datetime.now().strftime("%Y-%m")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT video_url, views, created_at FROM submissions WHERE discord_id = %s AND submission_month = %s ORDER BY id ASC", (d_id, current_month))
    rows = cursor.fetchall()
    cursor.execute("SELECT COUNT(*), SUM(views) FROM submissions WHERE discord_id = %s AND submission_month = %s", (d_id, current_month))
    stats = cursor.fetchone()
    conn.close()

    v_count, total_views = stats[0] or 0, stats[1] or 0
    if not rows:
        await interaction.response.send_message(f"⚠️ لم تقم بإرسال أي مقاطع لشهر {current_month}.", ephemeral=True)
        return

    res = f"🎬 **مقاطعك المسجلة لشهر {current_month}:**\n\n"
    for idx, r in enumerate(rows, 1):
        res += f"{idx}. {r[0]}\n   👁 المشاهدات: `{r[1]:,}` | ⏱ `{r[2]}`\n"
    res += f"\n📊 **إجمالي المشاهدات:** `{total_views:,}` | **المقاطع:** `{v_count}`\n🎖 **الرتبة:** {calculate_rank(total_views, v_count)}"
    await interaction.response.send_message(res, ephemeral=True)

@bot.tree.command(name="request_platform", description="طلب اعتماد منصة نشر جديدة")
@app_commands.choices(platform=[
    app_commands.Choice(name="TikTok", value="TikTok"),
    app_commands.Choice(name="Instagram", value="Instagram"),
    app_commands.Choice(name="YouTube", value="YouTube"),
    app_commands.Choice(name="Facebook", value="Facebook")
])
async def request_platform(interaction: discord.Interaction, platform: str):
    d_id = interaction.user.id
    user_plats = get_user_platforms(d_id)
    if user_plats.get(platform) == "pending":
        await interaction.response.send_message(f"⚠️ لديك طلب معلق بالفعل لمنصة **{platform}**.", ephemeral=True)
        return
    elif user_plats.get(platform) == "approved":
        await interaction.response.send_message(f"✅ منصة **{platform}** معتمدة لديك بالفعل.", ephemeral=True)
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO creator_platforms (discord_id, platform, status, requested_at) VALUES (%s, %s, 'pending', %s) ON CONFLICT (discord_id, platform) DO UPDATE SET status = 'pending', requested_at = EXCLUDED.requested_at", (d_id, platform, now))
    conn.commit()
    conn.close()

    await interaction.response.send_message(f"✅ تم إرسال طلب اعتماد منصة **{platform}** للإدارة.", ephemeral=True)
    if ADMIN_CHANNEL_ID != 0:
        channel = bot.get_channel(ADMIN_CHANNEL_ID)
        if channel:
            view = PlatformApprovalView(d_id, platform)
            await channel.send(f"🔔 **طلب اعتماد منصة جديد:**\n👤 صانع المحتوى: {interaction.user.mention}\n📱 المنصة: **{platform}**", view=view)

@bot.tree.command(name="submit_video", description="إرسال مقطع جديد مع عدد المشاهدات")
@app_commands.describe(url="رابط المقطع", views="عدد المشاهدات الحالي")
async def submit_video(interaction: discord.Interaction, url: str, views: int):
    d_id = interaction.user.id
    matched_platform = None
    for plat, pattern in URL_PATTERNS.items():
        if re.search(pattern, url):
            matched_platform = plat
            break

    if not matched_platform:
        await interaction.response.send_message("❌ رابط المقطع غير صالح أو غير مدعوم.", ephemeral=True)
        return

    user_plats = get_user_platforms(d_id)
    if user_plats.get(matched_platform) != "approved":
        await interaction.response.send_message(f"⛔ منصة **{matched_platform}** غير معتمدة بحسابك.", ephemeral=True)
        return

    current_month = datetime.now().strftime("%Y-%m")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO submissions (discord_id, video_url, views, submission_month, created_at) VALUES (%s, %s, %s, %s, %s)", (d_id, url, views, current_month, now))
        conn.commit()
        cursor.execute("SELECT COUNT(*), SUM(views) FROM submissions WHERE discord_id = %s AND submission_month = %s", (d_id, current_month))
        stats = cursor.fetchone()
        v_count, total_views = stats[0] or 1, stats[1] or views

        rank = calculate_rank(total_views, v_count)
        next_progress = get_next_rank_progress(total_views, v_count)

        await interaction.response.send_message(f"✅ **تم تسجيل المقطع بنجاح!**\n📹 المنصة: {matched_platform}\n👁 المشاهدات: {views:,}\n📊 مجموع هذا الشهر: {v_count} مقطع | {total_views:,} مشاهدة\n🎖 الرتبة: {rank}\n{next_progress}", ephemeral=True)
    except psycopg2.IntegrityError:
        conn.rollback()
        await interaction.response.send_message("❌ هذا الرابط مسجل مسبقاً في النظام.", ephemeral=True)
    finally:
        conn.close()

# --- تنفيذ أوامر المشرفين (Admin Commands) ---

@bot.tree.command(name="allow", description="[إدارة] إضافة صانع محتوى للقائمة المعتمدة")
async def allow_user(interaction: discord.Interaction, user: discord.User):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ لا تملك الصلاحية.", ephemeral=True)
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO whitelist (discord_id, added_at) VALUES (%s, %s)", (user.id, now))
        conn.commit()
        await interaction.response.send_message(f"✅ تم اعتماد الحساب {user.mention} بنجاح.")
    except psycopg2.IntegrityError:
        conn.rollback()
        await interaction.response.send_message("⚠️ الحساب مضاف مسبقاً.")
    finally:
        conn.close()

@bot.tree.command(name="broadcast", description="[إدارة] إرسال إشعار جماعي لكل صناع المحتوى")
async def broadcast(interaction: discord.Interaction, message: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ لا تملك الصلاحية.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT discord_id FROM users")
    users = cursor.fetchall()
    conn.close()

    sent, failed = 0, 0
    for u in users:
        member = bot.get_user(u[0])
        if member:
            try:
                await member.send(f"📢 **إشعار هام من الإدارة:**\n\n{message}")
                sent += 1
                await asyncio.sleep(0.2)
            except Exception:
                failed += 1
    await interaction.followup.send(f"✅ **تم الإرسال الجماعي:**\n📤 تم بنجاح: `{sent}` | ❌ فشل: `{failed}`")

# تشغيل البوت
if __name__ == "__main__":
    bot.run(TOKEN)
