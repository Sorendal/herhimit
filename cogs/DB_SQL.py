'''
Interface to store message histories in a sql database. Should work with
any sql database suppored by sqlachemy, but currently configured with
to use mariadb/mysql and sqlite. SQLite implmentation requires a db file (this 
cog is for message storing after restarting the bot).

This expects the bot object to have the relevant configuarion parameters
bot.config dict (to be loaded by the main bot). I encourage you to set access
rights to your db appropreatly (dont use root and give this boot full access
to a seperate discord database). I am not responsible if you choose to use this 
and it deletes all your DB data.

Events Dispatched

    message_history : dict of message id to Discord_Message objects
        to be caught by the LLM cog. Called in 2 situations:
            1 - on startup for all users in the channel
            2 - on_voice_memeber_speaking_state - when a user is first detected
                speaking the the voice channel
        
    token_count_request: Discord_Message
        request to be caught by the LLM cog to count tokens on
        a STT message

Event Listeners

    on_ready - startup

    on_tokens_counted: Discord_Message
        passed by the LLM cog with the token count added to the message object
        so the messag can be stored in the database.

    on_voice_member_speaking_state: member(discord.member object)
        called when a voice member is detected sending data (not usualy
        more than noise), checks if the user is in the DB, then logs 
        an activity timestamp

    on_voice_member_disconnect: member(discord.member object)
        called when a voice member disconnects from the voice channel.
        Checks if the user is in the DB, then logs an activity timestamp
    
    on_voice_client_connected: list of discord.Member objects
        called when the bot joins the voice channel. Checks if each user
        is in the DB, then logs an activity timestamp. Used during
        bot startup
'''
import logging
from datetime import datetime

from discord import Member, VoiceState
from discord.ext import commands, tasks

from scripts.DB_SQL import SQL_Interface_Base
from scripts.discord_ext import Commands_Bot
from utils.datatypes import Discord_Message, DB_InOut, Cog_User_Info

logger = logging.getLogger(__name__)

class SQL_Interface(commands.Cog, SQL_Interface_Base):
    def __init__(self, bot: Commands_Bot) -> None:
        self.bot:Commands_Bot = bot
        SQL_Interface_Base.__init__(self)
        self.message_waiting_for_token_count = []
        self.queues = self.bot.___custom.queues
        self.set_config()
        self.db_connected: bool = True
        self.db_connected_expected: bool = self.db_connected

    def set_config(self):
        self.host = self.bot.___custom.config['sql_db_host']
        self.port = self.bot.___custom.config['sql_db_port']
        self.user = self.bot.___custom.config['sql_db_user']
        self.password = self.bot.___custom.config['sql_db_password']
        self.database = self.bot.___custom.config['sql_db_database']
        self.server_type = self.bot.___custom.config['sql_db_type']
        self.sqlite_filename = self.bot.___custom.config['sql_db_sqlite_file']
        self.engine = self.get_engine()
        self.factory = self.get_session_factory()
        self.member_info: dict[int, Cog_User_Info] = self.bot.___custom.member_info

    @tasks.loop(seconds=10)
    async def DB_Monitor(self):
        # switch the state of the db connection if needed for manual control
        if self.db_connected != self.db_connected_expected:
            await self.db_connect(switch_state=self.db_connected)
            self.db_connected_expected = self.db_connected

        if self.db_connected and not self.bot.___custom.check_voice_idle(idle_time=0):
            # disconnect dbs
            await self.db_connect(switch_state=False)
            self.db_connected_expected = self.db_connected

        if self.bot.___custom.check_voice_idle(idle_time=300): # 5 minutes
            # connect dbs if there are messages to process need to check if 
            # a person is idle in voice chat
            only_active = True
            for item in self.bot.___custom.queues.db_loginout:
                if item['out_time']:
                    only_active = False
            if self.bot.___custom.queues.db_message and only_active:
                await self.db_connect(switch_state=True)
            else:
                await self.db_connect(switch_state=False)

            # check for users in the memory dict against the database
            for user in self.member_info.values():
                if not user.checked_against_db:
                    response = await self.db_check_add_user(disc_member=user)
                    if type(response) is dict:
                        logger.info(f"Logged in user info changed {(', '.join([f'{key}={value}' for key, value in response.items()]))}")
                    user.checked_against_db = True

            # process login/logout queue
            process_list = []
            for record in self.bot.___custom.queues.db_loginout:
                if 'db_commit' in record:
                    process_list.append(record)
            if process_list:
                for record in reversed(process_list):
                    self.queues.db_loginout.remove(record)
                process_list.clear()

            # process messages queue
            await self.record_messages(disc_messages=self.queues.db_message)
            for record in self.bot.___custom.queues.db_message:
                if record.stored_in_db:
                    process_list.append(record)
            if process_list:
                for record in reversed(process_list):
                    self.queues.db_message.remove(record)

    async def db_connect(self, switch_state: bool = None):
        '''
        allows the database connection to be turned on and off
        first checks db_always_connected setting
        '''
        if self.bot.___custom.db_always_connected:
            return
        if switch_state and not self.db_connected:
            self.engine = self.get_engine()
            self.factory = self.get_session_factory()
            self.db_connected = True
        elif not switch_state and self.db_connected:
            try:
                await self.engine.dispose()
            except Exception as e:
                logger.info(e)
            self.factory = None
            self.engine = None
            self.db_connect = False

    async def user_login_q(self, member_id: int) -> bool:
       
       # get user info from memory dict
       member_info = await self.get_member_info(member_id=member_id)
       if not member_info:
           logger.error('login - User not found')
           return False

       # check the last record
       last_record = member_info.last_DB_InOut
       if last_record:
           # check if that last record is not a complete login/logout pair and do nothing
           if not last_record['out_time']:
               logger.info(f'login q - already logged in - unforseen error')
               return True
       new_record = DB_InOut({'member_id': member_id, 'in_time': datetime.now(), 'out_time': None})
       self.queues.db_loginout.append(new_record)
       member_info.last_DB_InOut = new_record
       return True
    
    async def user_logout_q(self, member_id: int) -> bool:
        member_info = await self.get_member_info(member_id)
        if not member_info:
            logger.info('logout - User not found')
            return False
        elif not member_info.last_DB_InOut:
            logger.info('loginout record - expected if bot starts and user does not have activity before leaving channel')
            await self.user_login_q(member_id=member_id)
            await self.user_logout_q(member_id=member_id)
            return False
        else:
            member_info.last_DB_InOut['out_time'] = datetime.now()
            return True

    async def get_member_info(self, member_id: int) -> Cog_User_Info:
        if member_id not in self.member_info:
            discord_member = self.bot.get_user(member_id)
            member_object = Cog_User_Info(
                    member_id = member_id,
                    name = discord_member.name,
                    display_name = discord_member.display_name,
                    global_name = discord_member.global_name, 
                    timestamp_creation = datetime.now(),
                    bot=discord_member.bot,
                    last_DB_InOut = None
            )
            self.member_info[member_id] = member_object
            if self.db_connected:
                await self.db_check_add_user(disc_member=member_object)
            return member_object
        else:
            member_object = self.member_info[member_id]
        return member_object
        
        
    @commands.Cog.listener('on_voice_client_connected')
    async def on_voice_client_connected(self, members: list[Member], *args, **kwargs):
        for member in members:
            await self.user_login_q(member.id)
            if self.db_connected:
                await self.get_member_info(member_id=member.id)
        for member in self.bot.___custom.voice_channel.members:
            logger.info(f'Member {member.name} and db is {self.db_connected}')
            if member.bot  and self.db_connected:
                message_history = await self.get_message_history(member_id=member.id)
                if len(message_history) == None:
                    return
                self.bot.dispatch('message_history', member_id=member.id, 
                    message_history= message_history)

    @commands.Cog.listener('on_connect')
    async def on_connect(self):
        if not await self.check_tables():
            await self.create_tables()
        self.DB_Monitor.start()

    @commands.Cog.listener('on_ready')
    async def on_ready(self, *args, **kwargs):
        self.bot.dispatch('db')
        pass

    @commands.Cog.listener('on_voice_member_speaking_state')
    async def on_voice_member_speaking_state(self, member: Member, *args, **kwargs):
        #logger.info(f'on_voice_member_speaking_state args {args} kwargs {kwargs}')
        await self.user_login_q(member_id=member.id)

    @commands.Cog.listener('on_voice_state_update')
    async def on_voice_state_update(self, member: Member, before: VoiceState, after: VoiceState):
        if before.channel == self.bot.___custom.voice_channel:
            await self.user_logout_q(member_id=member.id)
        if after.channel == self.bot.___custom.voice_channel:
            await self.user_login_q(member_id=member.id)

    async def cleanup(self):
        for member in self.bot.___custom.voice_channel.members:
            await self.user_logout_q(member_id=member.id)
        await self.db_connect(switch_state=True)
        if self.queues.db_loginout:
            await self.record_loginout(logins=self.queues.db_loginout)
        if self.queues.db_message:
            await self.record_messages(disc_messages=self.queues.db_message)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SQL_Interface(bot))