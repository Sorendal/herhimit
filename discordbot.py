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
from discord.ext import commands, tasks

from utils.datatypes import Discord_Message, Commands_Bot, DB_InOut

config = dotenv_values('.env')

intents=discord.Intents.all() 
intents.members = True
intents.voice_states = True
intents.message_content = True

discord.utils.setup_logging()

bot = Commands_Bot(command_prefix=config["behavior_command_prefix"], intents=intents, config=config)

#bot = commands.Bot(command_prefix=config["behavior_command_prefix"], intents=intents)

'''
future ideas:
    user mute penalty box: track users who speak over other users and give them a penalty box 
        for a certain amount of time this will be a dictionary with the user id as the key and 
        the number of times they have spoken over another user as the value
    STT input coherence check - pass the text to the llm with the history and see if the llm
        can correct errors in the text (word error rate is still above 6% for the best models)

things to check 

    STT - Make sure behavoir is correct for multiple users
'''

class TextInterface(commands.Cog):
    def __init__(self, bot: Commands_Bot):
        self.bot: Commands_Bot = bot
        self.text_channel_title = self.bot.___custom.config['client_text_channel']
        self.track_interrupt = bool(self.bot.___custom.config['behavior_track_text_interrupt'])
        self.bot.___custom.show_timings = bool(self.bot.___custom.config['performance_show_timings'])
        self.show_timings = self.bot.___custom.show_timings
        self.text_channel: discord.TextChannel = None
        self.authorized_roles: dict[int, str] = {}
        self.last_message: dict[int, int] = {}
        self.monitor_loop_count: int = 0
        self.id_member_name: dict[int, str] = self.bot.___custom.current_listeners
        self.user_speaking: set[int] = self.bot.___custom.user_speaking
        self.queues = self.bot.___custom.queues
        self.display_logs_queue: bool = False

    @tasks.loop(seconds=0.1)
    async def Text_Monitor(self):
        self.monitor_loop_count += 1
        report: list[str] = []
        # every iteration
        if report:
            logging.info('\n'.join(report))
            
        if self.monitor_loop_count % 10:
        # every second
            if self.display_logs_queue:
                report.append(self.diag_list_queues())
            if report:
                logging.info('\n'.join(report))
            pass
        if self.monitor_loop_count % 600 == 0:
        # every minute
            pass

        if self.queues.text_message:
            await self.process_text_message(message=self.queues.text_message.popleft())

    def diag_list_queues(self):
        return 'Queues: ' + ', '.join([f'{item}: {len(getattr(self.queues, item))}' 
                    for item in vars(self.queues)])

        #return_string = 'Queues: '
        #for item in vars(self.queues):
        #    return_string += f'{item} {len(getattr(self.queues, item))}, '
        #return return_string

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
    
    async def process_text_message(self, message: Discord_Message):
        logging.info(f'Processing text message: Discord Message ID: {message.discord_text_message_id}  Text:{len(message.text)} LLM Correct: {len(message.text_llm_corrected)} User Interrupt: {len(message.text_user_interrupt)}')

        #edited message
        if message.text_llm_corrected or message.text_user_interrupt:
            try:
                disc_message = await self.text_channel.fetch_message(message.discord_text_message_id)
                if message.text_llm_corrected:
                    await disc_message.edit(content=f':{message.member}: {message.text_llm_corrected} (corrected by LLM)')
                elif message.text_user_interrupt:
                    await disc_message.edit(content=f'{message.text_user_interrupt}')
            except discord.errors.HTTPException:
                if message.discord_retry == 2:
                    logging.info("Max retries exceeded for editing the message. Discarding message")
                else:
                    message.discord_retry += 1
                    logging.info(f"An HTTP exception occurred while fetching or editing message")
                    self.queues.text_message.appendleft(message)                
            except discord.NotFound:
                logging.info("The specified message was not found.")
            except discord.Forbidden:
                logging.info("Permission error: fetch messages from this channel, or Discord prevented it.")
        #new message
        else:
            output_text = ''
            if message.member_id == self.bot.user.id:
                output_text = message.text
            else:
                output_text = f':{message.member}: {message.text}'
            try:    
                disc_message = await self.text_channel.send(output_text)
                message.discord_text_message_id = disc_message.id
            except discord.errors.HTTPException:
                if message.discord_retry == 2:
                    logging.info(f"An HTTP exception occurred while sending message - Max retrys - Discarding message")
                else:
                    message.discord_retry += 1
                    self.queues.text_message.appendleft(message)                
                logging.info(f"An HTTP exception occurred while sending message")
            except discord.Forbidden:
                logging.info("Permission error: send messages to this channel, or Discord prevented it.")

    @commands.Cog.listener('on_connect')
    async def on_connect(self):
        
        while self.text_channel == None:
            await self._connect_text()
            if self.text_channel== None:
                await asyncio.sleep(1)
        
        await self.text_channel.send("Hello, world!")
        await self._set_authorized_roles()
        self.Text_Monitor.start()
        logging.info(f'{bot.user.name} {bot.user.id} has connected to Discord!')

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
    async def rdb(self, ctx: commands.context.Context):
        """Reloads the database"""
        if self.check_auth(ctx) == False:
            await ctx.send("You are not authorized to use this command.")
            return
        bot.dispatch('reload_database')

    @commands.Cog.listener('on_db_ready_reload')
    async def on_db_ready_reload(self):
        """Reloads the database"""
        await self.reload(cog='db-')

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
    
    @commands.command()
    async def logq(self, ctx: commands.context.Context):
        if self.display_logs_queue:
            self.display_logs_queue = False
            await ctx.send("Log queue disabled.")
        else:
            self.display_logs_queue = True
            await ctx.send("Log queue enabled.")
    
    @commands.command()
    async def ii(self, ctx: commands.context.Context):
        for item in self.queues.db_loginout:
            logging.info(item)

#@bot.event98
#async def on_ready(*args):
#    logging.info(f'{bot.user.name} {bot.user.id} has connected to Discord!')

async def load_cogs():
    #Intentionally kept text cog integrated to the main bot
    await bot.add_cog(TextInterface(bot))

    for file in os.listdir('./cogs'):
        if file.endswith('.py'):
            await bot.load_extension(f'cogs.{file[:-3]}')

async def main():   
    
    await load_cogs()
    
    await bot.start(config['client_token'])

asyncio.run(main())