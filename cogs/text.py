import logging, asyncio

import discord
from discord.ext import commands, tasks

from scripts.discord_ext import Commands_Bot
from scripts.datatypes import Discord_Message
from scripts.utils import time_diff

class text_interface(commands.Cog):
    def __init__(self, bot: Commands_Bot):
        self.bot: Commands_Bot = bot
        self.text_channel_title = self.bot.custom.config['client_text_channel']
        self.track_interrupt = bool(self.bot.custom.config['behavior_track_text_interrupt'])
        self.bot.custom.show_timings = bool(self.bot.custom.config['performance_show_timings'])
        self.bot.custom.show_text = bool(self.bot.custom.config['performance_show_text'])
        self.bot.custom.tts_enable = bool(self.bot.custom.config['behavior_TTS_enable'])
        self.bot.custom.db_always_connected = bool(self.bot.custom.config['performance_db_always_connected'])
        self.show_timings = self.bot.custom.show_timings
        self.text_channel: discord.TextChannel = self.bot.custom.text_channel
        self.authorized_roles: dict[int, str] = {}
        self.last_message: dict[int, int] = {}
        self.monitor_loop_count: int = 0
        self.id_member_name: dict[int, str] = self.bot.custom.current_listeners
        self.user_speaking: set[int] = self.bot.custom.user_speaking
        self.queues = self.bot.custom.queues
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
        if self.show_timings:
            if self.bot.custom.show_text:
                logging.info(self.report_text_info(disc_message=message))
        # edited message
        if message.text_llm_corrected or message.text_user_interrupt:
            try:
                disc_message = await self.text_channel.fetch_message(message.discord_text_message_id)
                if message.text_llm_corrected:
                    await disc_message.edit(content=f':{message.member}: {message.text} (corrected by LLM)')
                elif message.text_user_interrupt:
                    await disc_message.edit(content=f'{message.text}')
            except discord.errors.HTTPException:
                if message.discord_text_retry == 2:
                    logging.info("Max retries exceeded for editing the message. Discarding message")
                else:
                    message.discord_text_retry += 1
                    logging.info(f"An HTTP exception occurred while fetching or editing message")
                    self.queues.text_message.appendleft(message)                
            except discord.NotFound:
                logging.info("The specified message was not found.")
            except discord.Forbidden:
                logging.info("Permission error: fetch messages from this channel, or Discord prevented it.")
        #new message
        else:
            output_text = ''
            if message.user_id == self.bot.user.id:
                output_text = message.text
            else:
                output_text = f':{message.user_name.capitalize()}: {message.text}'
            try:    
                disc_message = await self.text_channel.send(output_text)
                message.discord_text_message_id = disc_message.id
            except discord.errors.HTTPException:
                if message.discord_text_retry == 2:
                    logging.info(f"An HTTP exception occurred while sending message - Max retrys - Discarding message")
                else:
                    message.discord_text_retry += 1
                    self.queues.text_message.appendleft(message)                
                    logging.info(f"An HTTP exception occurred while sending message")
            except discord.Forbidden:
                logging.info("Permission error: send messages to this channel, or Discord prevented it.")

    def report_text_info(self, disc_message: Discord_Message) -> str:
        output_text = ''
        if self.bot.custom.show_text:
            if disc_message.text:
                output_text += f'Text: {disc_message.text} '
            if disc_message.text_llm_corrected:
                output_text += f'LLM Corrected Text: {disc_message.text_llm_corrected} '
            if disc_message.text_user_interrupt:
                output_text += f'User Interrupted Text: {disc_message.text_user_interrupt} '
        if self.bot.custom.show_timings and self.bot.custom.show_text:
            output_text += '\n'
        if self.show_timings:
            if disc_message.timestamp_STT:
                output_text += f'Timing: STT:{time_diff(disc_message.timestamp_STT, disc_message.timestamp_Audio_End)}'
            if disc_message.timestamp_LLM:
                output_text += f' LLM:{time_diff(disc_message.timestamp_LLM, disc_message.timestamp_Audio_End)}'
            if disc_message.timestamp_TTS_start:
                output_text += f' TTS:({time_diff(disc_message.timestamp_TTS_start, disc_message.timestamp_Audio_End)}'
            if disc_message.timestamp_TTS_end:
                output_text += f'-{time_diff(disc_message.timestamp_TTS_end, disc_message.timestamp_Audio_End)}'
        return output_text        

    @commands.Cog.listener('on_connect')
    async def on_connect(self):
        
        while self.text_channel == None:
            await self._connect_text()
            if self.text_channel== None:
                await asyncio.sleep(1)
        
        await self.text_channel.send("Hello, world!")
        await self._set_authorized_roles()
        self.Text_Monitor.start()
        logging.info(f'{self.bot.user.name} {self.bot.user.id} has connected to Discord!')

    @commands.command()
    async def list_cogs(self, ctx: commands.context.Context, *args):
        """Lists all cogs"""
        if self.check_auth(ctx) == False:
            await ctx.send("You are not authorized to use this command.")
            return
        await ctx.send('Cogs: ' + ', '.join([f'`{x}`' for x in self.bot.extensions]))

    @commands.command()
    async def reload(self, ctx: commands.context.Context, cog: str):
        """Reloads a cog. name shortened to 3 letters after cogs."""
        if self.check_auth(ctx) == False:
            await ctx.send("You are not authorized to use this command.")
            return
        extensions = self.bot.extensions.copy()
        ext_dict = {}
        for extension in extensions:
            ext_dict.update({f'{extension[5:8].lower()}' : extension})

        if cog == 'all':
            for extension in extensions:
                await self.bot.reload_extension(extension)
        else:
            if cog not in ext_dict.keys():
                return await ctx.send("That's not a valid cog!")
            await self.bot.reload_extension(ext_dict[cog])
            logging.info(f'Reloaded {ext_dict[cog]}')
        await ctx.send('Done.')
    
    @commands.command()
    async def unload(self, ctx: commands.context.Context, cog: str):
        """Unloads a cog. name shortened to 3 letters after cogs."""
        if not self.check_auth(ctx):
            await ctx.send("You are not authorized to use this command.")
            return
        extensions = self.bot.extensions.copy()
        ext_dict = {}
        for extension in extensions:
            ext_dict.update({f'{extension[5:8].lower()}' : extension})

        if cog not in ext_dict.keys():
            return await ctx.send("That's not a valid cog!")
        await self.bot.unload_extension(ext_dict[cog])
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
            await ctx.send("You are not authorized to use this command.", delete_after=5)
            return
        for extension in self.bot.cogs:
            try:
                logging.info(f'Cleaning up {extension}...')
                working_cog: Commands_Bot.cogs = self.bot.get_cog(extension)
                await working_cog.cleanup()
            except Exception as e:
                logging.error(f'Error cleaning up {extension}: {e}')
        await ctx.message.delete()
        await ctx.send('Bye!')
        await self.bot.close()

    '''
    not implmented yet
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
    '''

    @commands.command()
    async def log(self, ctx: commands.context.Context, arg1: str, arg2: str = None):
        '''
        toggles to display info to the log

        q - show queues
        pgen - show prompt generation
        mh - show message history - very, very spammy - basically debug
        text - show text generation
        '''
        if not self.check_auth(ctx):
            await ctx.send("You are not authorized to use this command.", delete_after=5)
        elif arg1 == 'q':
            if self.display_logs_queue:
                self.display_logs_queue = False
                await ctx.send("Log queue disabled.")
            else:
                self.display_logs_queue = True
                await ctx.send("Log queue enabled.")
        elif arg1 == 'pgen':
            if self.bot.custom.display_message_history == True:
                self.bot.custom.display_message_history = False
                await self.text_channel.send('Message history disabled.', delete_after=5)
            else:
                self.bot.custom.display_message_history = True
                await self.text_channel.send('Message history enabled.', delete_after=5)
        elif arg1 == 'text':
            if self.bot.custom.show_text:
                self.bot.custom.show_text = False
                await ctx.send(f"Text logging is now disabled.", delete_after=5)
            else:
                self.bot.custom.show_text = True
                await ctx.send("Text logging is now enabled.", delete_after=5)
        else:
            await ctx.message.delete()
        #delete the sent message
        await ctx.message.delete(delay=5)

    @commands.command()
    async def toggle(self, ctx: commands.context.Context, arg1, *args):
        '''toggles options 
            db = db_always_connected
            tts 
            response - sub command
                ctr - shows a message as to why the bot choose to not respond
        '''
        if not self.check_auth(ctx):
            await ctx.send("You are not authorized to use this command.", delete_after=5)
        elif arg1 == 'db':
            if self.bot.custom.db_always_connected:
                self.bot.custom.db_always_connected = False
                await ctx.send("DB connection will disconnect when not idle.", delete_after=5)
            else:
                self.bot.custom.db_always_connected = True
                await ctx.send("DB connection will stay connected.", delete_after=5)
        elif arg1 == 'tts':
            if self.bot.custom.tts_enable:
                self.bot.custom.tts_enable = False
                await ctx.send("TTS is now disabled.", delete_after=5)
            else:
                self.bot.custom.tts_enable = True
                await ctx.send("TTS is now enabled.", delete_after=5)
        elif arg1 == 'response':
                if args[0] == 'ctr':
                    if self.bot.custom.show_choice_to_respond:
                        self.bot.custom.show_choice_to_respond = False
                        await ctx.send("Reasoning as to why not to respond disabled.", delete_after=5)
                    else:
                        self.bot.custom.show_choice_to_respond = True
                        await ctx.send("Reasoning as to why not to respond enabled.", delete_after=5)

        #delete the sent message
        await ctx.message.delete(delay=5)

async def setup(bot: commands.Bot):
    await bot.add_cog(text_interface(bot))