import os
import discord
from discord.ext import commands
import asyncpg

# قراءة المتغيرات البيئية
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
        print(f"✅ تم الاتصال بقاعدة بيانات Neon بنجاح!")
        await bot.tree.sync()
        print(f"Logged in as {bot.user.name}")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")

# ==========================================
# 1. لوحة تحكم صانع المحتوى (تظهر للجميع)
# ==========================================
class CreatorDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔗 ربط حساب اللعبة", style=discord.ButtonStyle.primary, custom_id="register_btn")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())

    @discord.ui.button(label="📥 طلب اعتماد منصة", style=discord.ButtonStyle.success, custom_id="request_platform_btn")
    async def request_platform_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlatformModal())

class RegisterModal(discord.ui.Modal, title="ربط حساب صانع المحتوى"):
    game_id = discord.ui.TextInput(label="معرف اللعبة (Game ID)", placeholder="اكتب معرفك هنا...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (user_id, game_id) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET game_id = $2",
                    str(interaction.user.id), self.game_id.value
                )
            await interaction.response.send_message(f"✅ تم ربط حسابك بمعرف اللعبة: **{self.game_id.value}** بنجاح!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"حدث خطأ: {e}", ephemeral=True)

class PlatformModal(discord.ui.Modal, title="طلب اعتماد منصة جديدة"):
    platform_name = discord.ui.TextInput(label="اسم المنصة (TikTok, YouTube, etc.)", placeholder="اكتب اسم المنصة...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        platform = self.platform_name.value
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_platforms (user_id, platform, status) 
                    VALUES ($1, $2, 'pending')
                    ON CONFLICT (user_id, platform) DO UPDATE SET status = 'pending'
                    """,
                    user_id, platform
                )

            await interaction.response.send_message(f"✅ تم إرسال طلب اعتماد منصة **{platform}** للإدارة بنجاح.", ephemeral=True)

            # إرسال الطلب لقناة الإدارة مع أزرار التحكم الخاصة بالمشرفين
            admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
            if admin_channel:
                embed = discord.Embed(
                    title="📥 طلب اعتماد منصة جديد",
                    description=f"المستخدم: {interaction.user.mention}\nالمنصة: **{platform}**",
                    color=discord.Color.blue()
                )
                view = AdminApprovalView(user_id=int(user_id), platform=platform)
                await admin_channel.send(embed=embed, view=view)
        except Exception as e:
            await interaction.response.send_message(f"حدث خطأ: {e}", ephemeral=True)

# ==========================================
# 2. لوحة تحكم المشرفين (مع حماية بالرتبة)
# ==========================================
class AdminApprovalView(discord.ui.View):
    def __init__(self, user_id: int, platform: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.platform = platform

    # دالة التحقق لتأكيد أن الضاغط يمتلك رتبة الإدارة أو صلاحيات المشرف
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        admin_role_name = "Content creators"  # استبدلها باسم رتبة المشرفين أو الإدارة في سيرفرك
        role = discord.utils.get(interaction.user.roles, name=admin_role_name)
        
        if role or interaction.user.guild_permissions.administrator:
            return True
        
        await interaction.response.send_message("❌ عذراً، هذه الأزرار مخصصة للمشرفين فقط!", ephemeral=True)
        return False

    @discord.ui.button(label="اعتماد ✅", style=discord.ButtonStyle.success)
    async def approve_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_platforms SET status = 'approved' WHERE user_id = $1 AND platform = $2",
                str(self.user_id), self.platform
            )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"✅ تم اعتماد منصة **{self.platform}** للمستخدم <@{self.user_id}> بنجاح!", ephemeral=True)

    @discord.ui.button(label="رفض ❌", style=discord.ButtonStyle.danger)
    async def reject_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_platforms SET status = 'rejected' WHERE user_id = $1 AND platform = $2",
                str(self.user_id), self.platform
            )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"❌ تم رفض طلب منصة **{self.platform}** للمستخدم <@{self.user_id}>.", ephemeral=True)

# ==========================================
# أمر إرسال لوحة صناع المحتوى
# ==========================================
@bot.tree.command(name="setup_creator_panel", description="إرسال لوحة تفاعلية لصناع المحتوى")
async def setup_creator_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("هذا الأمر للمشرفين فقط لإرسال اللوحة.", ephemeral=True)
        return
        
    embed = discord.Embed(
        title="🎮 لوحة تحكم صناع المحتوى",
        description="استخدم الأزرار بالأسفل لربط حسابك أو تقديم طلب اعتماد منصاتك بكل سهولة:",
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=embed, view=CreatorDashboardView())
    await interaction.response.send_message("✅ تم نشر لوحة صناع المحتوى بنجاح.", ephemeral=True)

bot.run(TOKEN)
