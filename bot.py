import os
import discord
from discord.ext import commands
import asyncpg
from datetime import datetime

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID", "1566768613279400008"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

db_pool = None

@bot.event
async def on_ready():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        print("✅ تم الاتصال بقاعدة بيانات Neon بنجاح!")
        
        # نشر لوحة تحكم صناع المحتوى تلقائياً فور تشغيل البوت
        channel = bot.get_channel(ADMIN_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="🎮 لوحة تحكم صناع المحتوى الشاملة",
                description="استخدم الأزرار بالأسفل لإدارة حسابك، تقديم طلبات المنصات، إرسال المقاطع، تعديل المشاهدات، أو متابعة إحصائياتك بكل سهولة:",
                color=discord.Color.green()
            )
            await channel.send(embed=embed, view=CreatorDashboardView())
            print("✅ تم نشر لوحة تحكم صناع المحتوى تلقائياً بنجاح!")

        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    game_id TEXT UNIQUE,
                    registered_at TEXT
                );
                CREATE TABLE IF NOT EXISTS creator_platforms (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT,
                    platform TEXT,
                    status TEXT DEFAULT 'pending',
                    requested_at TEXT,
                    UNIQUE(user_id, platform)
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT,
                    video_url TEXT UNIQUE,
                    views INTEGER DEFAULT 0,
                    submission_month TEXT,
                    created_at TEXT
                );
            """)
            print("✅ تم التحقق من الجداول وإنشاؤها بنجاح!")
            
        await bot.tree.sync()
        print(f"Logged in as {bot.user.name}")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات أو التهيئة: {e}")

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

# ==========================================
# لوحة تحكم صانع المحتوى (جميع الأزرار بفعالية تامة)
# ==========================================
class CreatorDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # 1. زر ربط حساب اللعبة
    @discord.ui.button(label="🔗 ربط حساب اللعبة", style=discord.ButtonStyle.primary, custom_id="register_game_id")
    async def register_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())

    # 2. زر طلب اعتماد منصة
    @discord.ui.button(label="📥 طلب اعتماد منصة", style=discord.ButtonStyle.success, custom_id="request_platform")
    async def platform_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlatformModal())

    # 3. زر إرسال مقطع جديد
    @discord.ui.button(label="🎬 إرسال مقطع جديد", style=discord.ButtonStyle.secondary, custom_id="submit_video")
    async def submit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VideoSubmissionModal())

    # 4. زر تعديل مشاهدات مقطع (عرض قائمة المقاطع الخاصة بالمستخدم)
    @discord.ui.button(label="⚙️ تعديل المشاهدات", style=discord.ButtonStyle.primary, custom_id="update_views_btn")
    async def update_views_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        current_month = datetime.now().strftime("%Y-%m")
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT video_url, views FROM submissions WHERE user_id = $1 AND submission_month = $2 ORDER BY id ASC", user_id, current_month)
        
        if not rows:
            await interaction.response.send_message("⚠️ ليس لديك أي مقاطع مسجلة لهذا الشهر لتعديل مشاهداتها.", ephemeral=True)
            return

        text = "🎬 **مقاطعك المسجلة هذا الشهر:**\n\n"
        for idx, row in enumerate(rows, 1):
            text += f"{idx}. الرابط: `{row['video_url']}`\n   👁 المشاهدات: **{row['views']:,}**\n\n"
        text += "💡 لتحديث مشاهدات مقطع أو استبداله، تواصل مع الإدارة أو استخدم أمر التعديل المخصص."
        await interaction.response.send_message(text, ephemeral=True)

    # 5. زر إحصائياتي هذا الشهر
    @discord.ui.button(label="📊 إحصائياتي", style=discord.ButtonStyle.danger, custom_id="my_stats")
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        current_month = datetime.now().strftime("%Y-%m")
        async with db_pool.acquire() as conn:
            subs = await conn.fetch("SELECT video_url, views FROM submissions WHERE user_id = $1 AND submission_month = $2", user_id, current_month)
        
        total_views = sum(s["views"] for s in subs)
        v_count = len(subs)
        rank = calculate_rank(total_views, v_count)
        
        text = f"📊 **إحصائياتك لشهر {current_month}:**\n\n📹 عدد المقاطع: **{v_count}**\n👁 إجمالي المشاهدات: **{total_views:,}**\n🎖 رتبتك الحالية: {rank}"
        await interaction.response.send_message(text, ephemeral=True)

    # 6. زر إلغاء / تراجع
    @discord.ui.button(label="❌ إلغاء", style=discord.ButtonStyle.secondary, custom_id="cancel_action")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 تم التراجع وإلغاء العملية بنجاح.", ephemeral=True)

# نافذة ربط المعرف (Modal)
class RegisterModal(discord.ui.Modal, title="ربط حساب اللعبة"):
    game_id = discord.ui.TextInput(label="معرف اللعبة (Game ID)", placeholder="اكتب أرقام المعرف فقط...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        g_id = self.game_id.value.strip()
        if not g_id.isdigit():
            await interaction.response.send_message("❌ يرجى إدخال أرقام صحيحة فقط للمعرف.", ephemeral=True)
            return
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (user_id, game_id, registered_at) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET game_id = $2",
                    user_id, g_id, now
                )
            await interaction.response.send_message(f"✅ تم ربط حسابك بنجاح بمعرف اللعبة: **{g_id}**", ephemeral=True)
        except Exception:
            await interaction.response.send_message("❌ عذراً، هذا المعرف مستخدم مسبقاً لحساب آخر.", ephemeral=True)

# نافذة طلب اعتماد منصة (Modal)
class PlatformModal(discord.ui.Modal, title="طلب اعتماد منصة جديدة"):
    platform_name = discord.ui.TextInput(label="اسم المنصة (TikTok, YouTube, etc.)", placeholder="اكتب اسم المنصة...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        plat = self.platform_name.value.strip().capitalize()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        async with db_pool.acquire() as conn:
            user_check = await conn.fetchval("SELECT game_id FROM users WHERE user_id = $1", user_id)
            if not user_check:
                await interaction.response.send_message("⚠️ يجب عليك ربط حساب اللعبة أولاً قبل طلب اعتماد المنصات!", ephemeral=True)
                return

            try:
                await conn.execute(
                    "INSERT INTO creator_platforms (user_id, platform, status, requested_at) VALUES ($1, $2, 'pending', $3)",
                    user_id, plat, now
                )
            except Exception:
                await conn.execute(
                    "UPDATE creator_platforms SET status = 'pending', requested_at = $3 WHERE user_id = $1 AND platform = $2",
                    user_id, plat, now
                )

        await interaction.response.send_message(f"✅ تم إرسال طلب اعتماد منصة **{plat}** إلى الإدارة بنجاح.", ephemeral=True)

        admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
        if admin_channel:
            embed = discord.Embed(title="🔔 طلب اعتماد منصة جديد", color=discord.Color.blue())
            embed.add_field(name="صانع المحتوى", value=interaction.user.mention, inline=False)
            embed.add_field(name="المنصة", value=plat, inline=False)
            view = AdminPlatformApprovalView(user_id=int(user_id), platform=plat)
            await admin_channel.send(embed=embed, view=view)

# نافذة إرسال المقطع (Modal)
class VideoSubmissionModal(discord.ui.Modal, title="إرسال مقطع جديد"):
    video_url = discord.ui.TextInput(label="رابط المقطع", placeholder="ضع الرابط هنا...", required=True)
    views_count = discord.ui.TextInput(label="عدد المشاهدات الحالي", placeholder="أرقام صحيحة فقط...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        url = self.video_url.value.strip()
        views_str = self.views_count.value.strip()

        if not views_str.isdigit():
            await interaction.response.send_message("❌ عدد المشاهدات يجب أن يكون أرقاماً صحيحة.", ephemeral=True)
            return
        
        views = int(views_str)
        current_month = datetime.now().strftime("%Y-%m")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        async with db_pool.acquire() as conn:
            matched_platform = "Other"
            if "tiktok.com" in url: matched_platform = "TikTok"
            elif "youtube.com" in url or "youtu.be" in url: matched_platform = "YouTube"
            elif "instagram.com" in url: matched_platform = "Instagram"
            elif "facebook.com" in url: matched_platform = "Facebook"

            plat_status = await conn.fetchval(
                "SELECT status FROM creator_platforms WHERE user_id = $1 AND platform ILIKE $2", 
                user_id, matched_platform
            )
            
            if plat_status != "approved":
                await interaction.response.send_message(f"⛔ منصة **{matched_platform}** غير معتمدة لحسابك. يرجى طلب اعتمادها أولاً.", ephemeral=True)
                return

            try:
                await conn.execute(
                    "INSERT INTO submissions (user_id, video_url, views, submission_month, created_at) VALUES ($1, $2, $3, $4, $5)",
                    user_id, url, views, current_month, now
                )
            except Exception:
                await interaction.response.send_message("❌ هذا الرابط مسجل مسبقاً في النظام!", ephemeral=True)
                return

            stats = await conn.fetchrow(
                "SELECT COUNT(*), SUM(views) FROM submissions WHERE user_id = $1 AND submission_month = $2",
                user_id, current_month
            )
            v_count, total_views = stats[0], stats[1]

        rank = calculate_rank(total_views, v_count)
        await interaction.response.send_message(
            f"✅ **تم تسجيل المقطع بنجاح!**\n📹 المنصة: {matched_platform}\n👁 المشاهدات: {views:,}\n📊 إجمالي مقاطعك هذا الشهر: {v_count} | المشاهدات الكلية: {total_views:,}\n🎖 رتبتك: {rank}",
            ephemeral=True
        )

# ==========================================
# لوحة تحكم المشرفين للموافقة على المنصات
# ==========================================
class AdminPlatformApprovalView(discord.ui.View):
    def __init__(self, user_id: int, platform: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.platform = platform

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("❌ هذه الأزرار مخصصة للمشرفين فقط!", ephemeral=True)
        return False

    @discord.ui.button(label="موافقة ✅", style=discord.ButtonStyle.success)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE creator_platforms SET status = 'approved' WHERE user_id = $1 AND platform = $2",
                str(self.user_id), self.platform
            )
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"✅ تمت الموافقة على منصة **{self.platform}** للمستخدم <@{self.user_id}>.", ephemeral=True)
        try:
            user = await bot.fetch_user(self.user_id)
            await user.send(f"🎉 مبروك! تمت الموافقة على منصة **{self.platform}** الخاصة بك.")
        except Exception:
            pass

    @discord.ui.button(label="رفض ❌", style=discord.ButtonStyle.danger)
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE creator_platforms SET status = 'rejected' WHERE user_id = $1 AND platform = $2",
                str(self.user_id), self.platform
            )
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"❌ تم رفض منصة **{self.platform}** للمستخدم <@{self.user_id}>.", ephemeral=True)
        try:
            user = await bot.fetch_user(self.user_id)
            await user.send(f"⚠️ عذراً، تم رفض طلب اعتماد منصة **{self.platform}**.")
        except Exception:
            pass

# أمر الأدمن لإدارة النظام
@bot.tree.command(name="admin", description="[للمشرفين فقط] لوحة التحكم الإدارية")
async def admin_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ عذراً، هذا الأمر مخصص للمشرفين فقط.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚡ لوحة التحكم الإدارية لنظام صناع المحتوى",
        description="النظام يعمل بكفاءة وجاهز لإدارة الطلبات والإحصائيات.",
        color=discord.Color.dark_blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(TOKEN)
