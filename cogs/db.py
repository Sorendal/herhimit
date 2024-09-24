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
        
Event Listeners

    on_ready - startup

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

    todo : Discord_Message.db_id and db_stored - for saving regenerated 
        prompts if the format changes

        important - set of message ids based on the db_message.id that 
            have been stored in the DB to prevent message duplication
'''
import logging
from datetime import datetime

from discord import VoiceState
from discord import Member as Disc_Member
from discord.ext import commands, tasks

from scripts.db_sql import SQL_Interface_Base
import scripts.db_cog as db_cog
from scripts.discord_ext import Commands_Bot

logger = logging.getLogger(__name__)

class SQL_Interface(commands.Cog, SQL_Interface_Base):
    def __init__(self, bot) -> None:
        self.bot:Commands_Bot = bot
        self.user_info: dict[int, db_cog.user] = self.bot.custom.user_info
        SQL_Interface_Base.__init__(self, self.bot.custom.config, self.user_info)
        self.queues = self.bot.custom.queues
        self.db_connected: bool = True
        self.db_connected_expected: bool = True

    @tasks.loop(seconds=10)
    async def DB_Monitor(self):
        return
        # check for users in the memory dict against the database
        # process login/logout queue

        # process messages queue - messages can be stored if they 
        # have not already be stored. there is an attribute in the 
        # record that indicates this.

        # remove the messages from the queue if they have been stored

    async def db_connect(self, switch_state: bool = None):
        '''
        allows the database connection to be turned on and off
        first checks db_always_connected setting
        '''
        return
        if self.bot.custom.db_always_connected:
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

    def cog_user_login(self, user: Disc_Member) -> bool:
        '''
        creates a record in the loginout queue for a user logging in
        '''
        if not user.id in self.user_info:
            self.cog_user_add(user)
        for record in reversed(self.queues.db_loginout):
            if record['user_id'] == user.id and not record['out_time']:
                logger.info(f'cog_user_login - {user.id} already logged in')
                return True
            elif record['user_id'] == user.id and record['out_time']:
                break
        self.queues.db_loginout.append(db_cog.InOut({
                'member_id' : user.id,
                'in_time': datetime.now(),
                'out_time': None,
                'stored_in_db': False
                }))
        return True
    
    def cog_user_logout(self, user: Disc_Member) -> bool:
        '''
        creates a record in the loginout queue for a user logging out
        '''
        if not user.id in self.user_info:
            self.cog_user_add(user)
        for record in reversed(self.queues.db_loginout):
            if (record['user_id'] == user.id) and (not record['out_time']):
                record['out_time'] = datetime.now()
                return True
        #failsafe - should never be reached
        logger.info(f'user {self.user_info[user.id]} does not have a valid LogInOut record, adding one with the current time')
        self.queues.db_loginout.append(db_cog.InOut({
            'member_id' : user.id,
            'in_time': datetime.now(),
            'out_time': datetime.now(),
            'stored_in_db': False
            }))
        return True

    def cog_user_add(self, user: Disc_Member):
        '''
        add a new user to the dict
        '''
        if user.id not in self.user_info:
            self.user_info[user.id] = db_cog.User(
                    user_id = user.id,
                    name = user.name.capitalize(),
                    display_name = user.display_name,
                    global_name = user.global_name, 
                    timestamp = datetime.now(),
                    bot = user.bot,
                    last_DB_InOut = None)
        
    @commands.Cog.listener('on_voice_client_connected')
    async def on_voice_client_connected(self, members: list[Disc_Member], *args, **kwargs):
        for member in members:
            self.cog_user_login(user=member)

    @commands.Cog.listener('on_connect')
    async def on_connect(self):
        return
        if not await self.check_tables():
            await self.create_tables()
        self.DB_Monitor.start()

    # not sure this is necessary
    @commands.Cog.listener('on_ready')
    async def on_ready(self, *args, **kwargs):
        self.bot.dispatch('db')
        pass

    @commands.Cog.listener('on_voice_member_speaking_state')
    async def on_voice_member_speaking_state(self, member: Disc_Member, *args, **kwargs):
        self.cog_user_login(user=member)

    @commands.Cog.listener('on_voice_state_update')
    async def on_voice_state_update(self, member: Disc_Member, before: VoiceState, after: VoiceState):
        if before.channel == self.bot.custom.voice_channel:
            await self.cog_user_logout(user_id=member.id)
        if after.channel == self.bot.custom.voice_channel:
            await self.cog_user_login(user_id=member.id)

    async def cleanup(self):
        return
        if not self.db_connected:
            pass
        for member in self.bot.custom.voice_channel.members:
            await self.user_logout_q(user_id=member.id)
        await self.db_connect(switch_state=True)
        if self.queues.db_loginout:
            await self.record_loginout(logins=self.queues.db_loginout)
        if self.queues.db_message:
            await self.record_messages(disc_messages=self.queues.db_message)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SQL_Interface(bot))