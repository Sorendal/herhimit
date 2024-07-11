'''
This is the core bot that implements the basic text functionality of the bot. Most of the magic
is done by the cogs. 

Authoization is implimented in a basic fashion any anyone on the server that is not a basic
user can run text commands. Fairly easy to come up with more complex system (i.e. server owner,
server admin, bot admin roles could be introduced.)

Configuration: Handled via the .env file, which is copied to the bot.config dictionary when the
bot starts up. Not married to this implimentation.

Annoying problem with discord channels - when a message is updated or created, an audio message
is sent to all users in discord. A conversation will create messages frequently and send that
alert. Not sure how to impliment a correction on this (other than tell the users to configure
their clients to not send audio messages for the channel). It might be possible to have the bot
create the channel when the voice client connects with no permisssions to anyone except the bot,
then update permissions when the user enters the voice channel.

Events Dispatched

    text_client_connected: data passed text_channel: discord.TextChannel
        This is dispatched when the text channel is connected to the bot. The data passed is
        a discord.TextChannel object.

    callme: data passed 
        name: one word string

Events Listeners

    on_STT_event_HC_pass: sends a message to the text channel with the member name and the text.
        This is so the users can see what the STT module output is not corrext (the word error
        rate is above 5%)

    on_LLM_message - sends  a message to the text channel and stores the id of that 
        message in self.last_bot_message_id

    on_update_message - edits the last message sent by a user or bot with the new text. 
        For a bot message, this is to show interrupts with a strike through.
        For user messages, this is to show if they have a speaking pause 

    on_delete_message - deletes the last message sent by the bot.

    on_ready - logs an info message

Commands

    list_cogs - lists all cogs to the text channel

    reload - reloads a cog if modified. Experimental feature and is probably better to
        restart the bot.

    die - calls cleanup in all cogs and then exits

    callme - sets name for llm (Bob instead of SuperSexyBob) - not implimented

    unload - unloads a cog, use 3 letters instead of the full cog name

    load - loads a cog (not implimented, broken code)


Configuration

    client_token
    client_text_channel
    behavior_track_text_interrupt="True"
    behavior_command_prefix='.'    

Cog Configuration

    Expected methods
    
        cleanup - called when the bot is shutting down to clean up any resources that may be
            in use. Just create a method with pass if not needed.

    configuration parameters - all configuration parameters are stored in the .env file, copied
        to to bot.config and can be accessed by self.bot.config[<parameter>]

'''
import logging, asyncio, os

from dotenv import dotenv_values

import discord
from discord.ext import commands

from utils.datatypes import Discord_Message, Halluicanation_Sentences

config = dotenv_values('.env')

intents=discord.Intents.all() 
intents.members = True
intents.voice_states = True
intents.message_content = True

discord.utils.setup_logging()

bot = commands.Bot(command_prefix=config["behavior_command_prefix"], intents=intents)

class TextInterface(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.text_channel_title = self.bot.config['client_text_channel']
        self.track_interrupt = bool(self.bot.config['behavior_track_text_interrupt'])
        self.text_channel: discord.TextChannel = None
        self.authorized_roles: dict[int, str] = {}
        self.last_message: dict[int, int] = {}

    async def _connect_text(self):
        if self.text_channel == None:
            self.text_channel = discord.utils.get(self.bot.get_all_channels(), 
                name=self.text_channel_title, 
                type=discord.ChannelType.text)
            self.bot.dispatch('text_client_connected', text_channel = self.text_channel)
        else:
            logging.info(f"Text channel '{self.text_channel_title}' not found.")
            return
        
    async def _set_authorized_roles(self):
        for role in self.bot.guilds[0].roles:
            if role.name != "@everyone":
                self.authorized_roles.update({role.id : role.name})

    def check_auth(self, ctx: commands.Context) -> bool:
        if ctx.author.roles[-1].id in self.authorized_roles.keys():
            return True
        else:
            return False

    async def cleanup(self):
        pass
    
    @commands.Cog.listener('on_connect')
    async def on_connect(self):
        
        while self.text_channel == None:
            await self._connect_text()
            if self.text_channel== None:
                await asyncio.sleep(1)
        
        await self.text_channel.send("Hello, world!")
        await self._set_authorized_roles()

    @commands.command()
    async def list_cogs(self, ctx: commands.context.Context, *args):
        """Lists all cogs"""
        if self.check_auth(ctx) == False:
            await ctx.send("You are not authorized to use this command.")
            return
        await ctx.send('Cogs: ' + ', '.join([f'`{x}`' for x in bot.extensions]))

    @commands.command()
    async def reload(self, ctx: commands.context.Context, cog: str):
        """Reloads a cog. name shortened to 3 letters after cogs."""
        if self.check_auth(ctx) == False:
            await ctx.send("You are not authorized to use this command.")
            return
        extensions = bot.extensions.copy()
        ext_dict = {}
        for extension in extensions:
            ext_dict.update({f'{extension[5:8].lower()}' : extension})

        if cog == 'all':
            for extension in extensions:
                await bot.reload_extension(extension)
        else:
            if cog not in ext_dict.keys():
                return await ctx.send("That's not a valid cog!")
            await bot.reload_extension(ext_dict[cog])
            logging.info(f'Reloaded {ext_dict[cog]}')
        await ctx.send('Done.')

    @commands.command()
    async def unload(self, ctx: commands.context.Context, cog: str):
        """Unloads a cog. name shortened to 3 letters after cogs."""
        if self.check_auth(ctx) == False:
            await ctx.send("You are not authorized to use this command.")
            return
        extensions = bot.extensions.copy()
        ext_dict = {}
        for extension in extensions:
            ext_dict.update({f'{extension[5:8].lower()}' : extension})

        if cog not in ext_dict.keys():
            return await ctx.send("That's not a valid cog!")
        await bot.unload_extension(ext_dict[cog])
        logging.info(f'Unloaded {ext_dict[cog]}')
        await ctx.send('Done.')

#    @commands.command()
#    async def load(self, ctx: commands.context.Context, cog: str):
#        """loads a cog. name shortened to 3 letters after cogs."""
#        if self.check_auth(ctx) == False:
#            await ctx.send("You are not authorized to use this command.")
#            return
#        extensions = bot.extensions.copy()
#        ext_dict = {}
#        for extension in extensions:
#            ext_dict.update({f'{extension[5:8].lower()}' : extension})
#
#        if cog in ext_dict.keys():
#            return await ctx.send("That cog is already loaded!")
#        
#        for item in os.scandir(f'./cogs/'):
#            if item.name.lower().startswith(cog.lower()) and item.name.lower().endswith('.py'):
#                await bot.load_extension(f'{item.name[:-3]}')
#                logging.info(f'Loaded {ext_dict[cog]}')
#                continue
#        else:
#            return await ctx.send("That cog is not available.")
#
#        await bot.load_extension(ext_dict[cog])
#        await ctx.send('Done.')

    @commands.command()
    async def die (self, ctx: commands.context.Context, *args):
        '''calls cleanup in all cogs and then exits'''
        if self.check_auth(ctx) == False:
            await ctx.send("You are not authorized to use this command.")
            return
        for extension in bot.cogs:
            try:
                logging.info(f'Cleaning up {extension}...')
                working_cog = bot.get_cog(extension)
                await working_cog.cleanup()
            except Exception as e:
                logging.error(f'Error cleaning up {extension}: {e}')
        await ctx.send('Bye!')
        await bot.close()

    @commands.command()
    async def callme(self, ctx: commands.context.Context, name: str):
        """
        simple command to displach the real name so the db and llm know it
        """
        if name in ['', None]:
            await ctx.send('Please provide a name to call you by.')
        else:
            self.bot.dispatch('update_username', name=name)
            await ctx.send('I will call you ' + name)
    
    @commands.Cog.listener('on_STT_event_HC_passed')
    async def on_STT_event_HC_passed(self, message: Discord_Message, *args, **kwargs):
        sent_message = await self.text_channel.send(f':{message.member.capitalize()}: {message.text}')
        self.last_message[message.member_id] = (sent_message.id + 1 - 1)

    @commands.Cog.listener('on_LLM_message')
    async def on_LLM_message(self, message: Discord_Message):
        '''
        create a new message and store the message id in self.last_bot_message_id
        '''
        sent_message = await self.text_channel.send(message.text) 
        self.last_message[message.member_id] = (sent_message.id + 1 - 1)

    @commands.Cog.listener('on_update_message')
    async def on_update_message(self, message: Discord_Message):
        if self.track_interrupt == False:
            return
        channel_message = await self.text_channel.fetch_message(self.last_message[message.member_id])
        await channel_message.edit(content=message.text)
        logging.info(f'Message updated')

    @commands.Cog.listener('on_delete_message')
    async def on_interrupted_message(self, message: Discord_Message):
        await self.text_channel.delete_messages(self.last_message[message.member_id])


@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} {bot.user.id} has connected to Discord!')

async def load_cogs():
    #Intentionally kept text cog integrated to the main bot
    await bot.add_cog(TextInterface(bot))

    for file in os.listdir('./cogs'):
        if file.endswith('.py'):
            await bot.load_extension(f'cogs.{file[:-3]}')

bot.config = config

async def main():   
    
    await load_cogs()
    
    await bot.start(config['client_token'])

asyncio.run(main())