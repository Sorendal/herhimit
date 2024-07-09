import discord
from discord.ext import commands

class Test(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("Ready!")

async def setup(bot: commands.Bot):
    await bot.add_cog(Test(bot))
