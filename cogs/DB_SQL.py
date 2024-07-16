'''
Interface to store message histories in a sql database. Should work with
any sql database suppored by sqlachemy, but currently configured with
to use mariadb/mysql and sqlite. SQLite implmentation requires a db file (this 
cog is for message storing after restarting the bot).

Was designed to be run directly for unit testing outside of discord. Learning
sqlalchemy for the fisrt time in an async enviornment was.. challenging.
The SQL_Base class is inherited by the testing class and bot class.

This expects the bot object to have the relevant configuarion parameters
bot.config dict (to be loaded by the main bot). I encourage you to set access
rights to your db appropreatly (dont use root and give this boot full access
to a seperate discord database). I am not responsible if you choose to use this 
and it deletes all your DB data.

Configuration - expected in the .env config file
    sql_db_type - mysql, mariadb, sqlite, postgresql(untested, let me know if this works)
    sql_db_sqlite_file - only for sqlite - ./filename (no ./ causes weirdness)
    sql_db_host - for remote db
    sql_db_port
    sql_db_user
    sql_db_password
    sql_db_database

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
import asyncio, logging
from datetime import datetime
from collections import deque
from dataclasses import dataclass
from typing import Optional, Union, TypedDict
from typing_extensions import Annotated

from discord import Member, VoiceState
from discord.ext import commands, tasks

from sqlalchemy import Integer, BigInteger,String , DateTime, Text, ForeignKey, TIMESTAMP, Null, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, writeonly, registry
from sqlalchemy.sql import text
from sqlalchemy.future import select
from sqlalchemy.sql.expression import desc, asc
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine, AsyncSession, AsyncAttrs

from utils.datatypes import Discord_Message, Commands_Bot, DB_InOut

str_255 = Annotated[str, mapped_column(String(255))]

logger = logging.getLogger(__name__)

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import DateTime
from sqlalchemy.dialects.mysql import DATETIME

@compiles(DateTime, "mysql")
def compile_datetime_mysql(type_, compiler, **kw):
     return "DATETIME(2)"

@dataclass
class Cog_User_Info:
#class Cog_User_Info(TypedDict):
    member_id: int
    name: str
    global_name: str
    display_name: str
    bot: bool
    timestamp_creation: datetime
    checked_against_db: bool = False
    last_DB_InOut: DB_InOut = False

class Base(DeclarativeBase, AsyncAttrs):
    registry = registry(
        type_annotation_map={
            str_255: String(255),
        }
    )

class Users(Base):
    __tablename__ = 'Users'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str_255]
    global_name: Mapped[Optional[str_255]]
    display_name: Mapped[Optional[str_255]]
    real_name: Mapped[Optional[str_255]]
    bot: Mapped[bool] = mapped_column(default=False)
    timestamp_creation: Mapped[datetime] = mapped_column(default=func.now())
    logs: Mapped[list['UserLog']] = relationship(back_populates= 'user', lazy='selectin')
    info: Mapped['UserInfo'] = relationship(back_populates= 'user', lazy='selectin')
    messages: Mapped[list['Messages']] = relationship(lazy='selectin', back_populates= 'user')
    messages_listened: Mapped[list['MessageListeners']] = relationship(back_populates= 'user', lazy='selectin')

class Messages(Base):
    __tablename__ = 'Messages'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('Users.id'))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_corrected: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_interrupted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp_creation: Mapped[datetime] = mapped_column(DateTime(2))
    tokens: Mapped[int]
    discord_message_id: Mapped[BigInteger] = mapped_column
    listeners: Mapped[list['MessageListeners']] = relationship(lazy='selectin')
    user: Mapped['Users'] = relationship()

class UserLog(Base):
    __tablename__ = 'UserLog'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('Users.id'))
    timestamp_in: Mapped[datetime]
    timestamp_out: Mapped[Optional[datetime]]
    user: Mapped['Users'] = relationship(back_populates='logs', lazy='selectin')

class UserInfo(Base):
    __tablename__ = 'UserInfo'
    id: Mapped[int] = mapped_column(primary_key= True)
    text: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('Users.id'))
    user: Mapped['Users'] = relationship(back_populates='info', lazy='joined')

class MessageListeners(Base):
    __tablename__ = 'MessageListeners'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('Users.id'))
    message_id: Mapped[int] = mapped_column(ForeignKey('Messages.id'))
    user: Mapped['Users'] = relationship(back_populates='messages_listened', lazy='selectin')
    message: Mapped['Messages'] = relationship(back_populates='listeners', lazy='selectin')

class SQL_Interface_Base():
    def __init__(self):
        self.host = None
        self.port = None
        self.user = None
        self.password  = None
        self.database = None
        self.server_type = None
        self.sqlite_filename = None
        self.Base = Base
        self.engine: AsyncEngine = None
        self.factory: async_sessionmaker[AsyncSession] = None
        self.users: Users = Users
        self.user_log: UserLog = UserLog
        self.messages: Messages = Messages
        self.message_listeners: MessageListeners = MessageListeners
        self.user_info: UserInfo = UserInfo

    def get_engine(self) -> AsyncEngine:
        if self.server_type == 'sqlite':
            return create_async_engine(f"sqlite+aiosqlite:///{self.sqlite_filename}")
        elif self.server_type in ['mysql', 'mariadb']:
            return create_async_engine(f"mysql+asyncmy://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}")
        elif self.server_type == 'postgreslq':
            return create_async_engine(f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}/{self.database}")
        else:
            raise Exception('Invalid server type')

    def get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        logger.debug(f'factory returned')
        return async_sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
    async def create_tables(self):
         # Create the tables in the database
        async with self.engine.begin() as conn:
            await conn.run_sync(self.Base.metadata.create_all)

    async def list_tables(self) -> list[str]:
         async with self.factory() as session:
            if self.server_type == 'sqlite':
                result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
            else:
                result = await session.execute(text("SHOW TABLES"))
            return result.all()
         
    async def check_tables(self) -> bool:
        '''
        Check if the tables in the database match the tables in the metadata
        if no tables found, return false
        error out if the tables do not exist
        EXPECTED IS THE ENTIRE LIST OF TABLES. WILL RAISE AN UNHANDLED EXCEPTION 
        IF NOT ALL TABLES ARE PRESENT. DOES NOT CHECK FOR COLUMNS OR DATA TYPES.
        '''
        tables_object = await self.list_tables()
        if len(tables_object) == 0:
            return False
        meta_tables = [item[0] for item in self.Base.metadata.tables.items()]
        for item in tables_object:
            if item[0] not in meta_tables:
                logger.warning(f'Table {item} is not in the database')
                print(f'Table {item} is not in the database')
                raise Exception(f'Table {item} is not in the database')
        return True

    async def check_user(self, disc_member: Cog_User_Info) -> Union[True, False, dict]:
        '''
        Check if the user is in the database and add them if they are not
        True - User logged in
        dict - returns a dict of changes
        '''
        async with self.factory() as session:
            async with session.begin():
                user = await session.get(Users, disc_member.member_id)
                response = {}
                if user is None:
                    user = Users(
                        id  = disc_member.member_id,
                        name = disc_member.name,
                        bot = disc_member.bot,
                        display_name = disc_member.display_name,
                        global_name = disc_member.global_name,
                        timestamp_creation = disc_member.timestamp_creation
                        )
                    session.add(user)
                    await session.commit()
                    return True
                else:
                    if user.name != disc_member.name:
                        response['old_name'] = user.name
                        response['new_name'] = disc_member.name
                        if disc_member.name:
                            user.name = disc_member.name
                    if user.display_name != disc_member.display_name:
                        response['old_display_name'] = user.display_name
                        response['new_display_name'] = disc_member.display_name
                        if disc_member.display_name:
                            user.display_name = disc_member.display_name
                    if user.global_name != disc_member.global_name:
                        response['old_global_name'] = user.global_name
                        response['new_global_name'] = disc_member.global_name
                        if disc_member.global_name:
                            user.global_name = disc_member.global_name
                    if user.bot != disc_member.bot:
                        response['old_bot'] = user.bot
                        response['new_bot'] = disc_member.bot
                        user.bot = disc_member.bot
                    await session.commit()
                if len(response) > 0:
                    return response
                else:
                    return True

    async def record_loginout(self, logins: deque[DB_InOut]) -> bool:
        '''
        Record the login and logouts of users in the database.
        '''
        async with self.factory() as session:
            async with session.begin():
                for login in logins:
                    if login['in_time'] is None or login['out_time'] is None:
                        continue
                    user = await session.get(Users, login['member_id'])
                    #logger.info(f'record loginout - user - {user}')
                    if user is None:
                        logger.info(f'User {login["member_id"]} not found in database')
                        continue
                    new_login = UserLog(user_id = user.id, 
                            timestamp_in = login['in_time'],
                            timestamp_out = login['out_time'])
                    session.add(new_login)
                    login['db_commit'] = True
                await session.commit()
                return True

    async def login_user(self, member_id: int):
        '''
        login the user with a timestamp, if they are not already logged in by
        checking checking timestamp_out and create a new login by adding a new 
        record if timestamp_out is not None.
        '''
        async with self.factory() as session:
            async with session.begin():
                user = await session.get(Users, member_id)
                if not user.logs:
                    session.add(self.user_log(user_id=user.id, timestamp_in=datetime.now()))
                elif user.logs[-1].timestamp_out:
                    session.add(self.user_log(user_id=user.id, timestamp_in=datetime.now()))
                elif user.logs[-1].timestamp_out is not None:
                    session.add(self.user_log(user_id=user.id))
                    await session.commit()

    async def logout_user(self, member_id: int):
        '''
        log out user with a timestamp. the all parameter is used during
        the cleanup method
        '''
        async with self.factory() as session:
            async with session.begin():
                user = await session.get(Users, member_id)
                if user is None:
                    raise Exception('No such user exists in the database.')
                
                if user.logs[-1].timestamp_out is not None:
                    raise Exception('User already departed, no new logout record to be created.')
                else:
                    user.logs[-1].timestamp_out = datetime.now()
            await session.commit()

    async def record_messages(self, disc_messages: list[Discord_Message]): 
        '''
        adds a message to the message tabel and updates the message_listeners 
        table. This allows the message history to contain messges they
        witnessed.
        '''    
        async with self.factory() as session:
            async with session.begin():
                query_users: dict[int, Users] = {}
                for disc_message in disc_messages:
                    # retreive users from the database
                    user = await session.get(self.users, disc_message.member_id)
                    if user is None:
                        raise Exception('No such user exists in the database on message creation.')
                    if disc_message.member_id not in query_users:
                        query_users[disc_message.member_id] = user
                    for listener in disc_message.listeners:
                        queried_listener = await session.get(self.users, listener)
                        if queried_listener is None:
                            raise Exception('No such user exists in the database on message creation.')
                        if listener not in query_users:
                            query_users[listener] = queried_listener
                for disc_message in disc_messages:
                    query_users[disc_message.member_id].messages.append(Messages(
                        text = disc_message.text, 
                        text_corrected = disc_message.text_llm_corrected,
                        text_interrupted = disc_message.text_user_interrupt,
                        tokens = disc_message.tokens,
                        timestamp_creation = disc_message.timestamp_creation,
                        ))
                    await session.flush()
                    for listener in disc_message.listeners:
                        if listener not in query_users.keys():
                            raise Exception('No such user exists in the database on message creation.')
                        session.add(self.message_listeners(
                            user_id = query_users[listener].id,
                            message_id=query_users[disc_message.member_id].messages[-1].id))
                await session.commit()

    async def get_message_history(self, member_id: int, max_tokens: int = 32768) -> dict[int, Discord_Message]:
        '''
        get a user history of total tokens, return a dict with a 
            key of message_id and value of Discord_messsage object
        '''
        async with self.factory() as session:
            async with session.begin():
                total_tokens = 0
                message_history = {}
                
                user = await session.get(Users, member_id)

                for _ in range (len(user.messages_listened), 0, -1):
                    message_listened_to = user.messages_listened[(_ - 1)]

                    await session.refresh(message_listened_to.message)
                    await session.refresh(message_listened_to.message.user)

                    current_message = Discord_Message(
                            member_id = message_listened_to.message.user.id,
                            member =    message_listened_to.message.user.name,
                            text =      message_listened_to.message.text,
                            tokens =    message_listened_to.message.tokens,
                            timestamp_LLM = message_listened_to.message.timestamp_creation,
                            listeners = [listener.user_id for listener in message_listened_to.message.listeners],
                            listener_names = [listener.user.name for listener in message_listened_to.message.listeners]
                        )

                    message_history.update({current_message.timestamp_LLM: current_message})
                    total_tokens += current_message.tokens
                    if total_tokens > max_tokens:
                        break
 
                return message_history
            
class SQL_Interface(commands.Cog, SQL_Interface_Base):
    def __init__(self, bot: Commands_Bot) -> None:
        self.bot:Commands_Bot = bot
        SQL_Interface_Base.__init__(self)
        self.message_waiting_for_token_count = []
        self.queues = self.bot.___custom.queues
        self.set_config()
        self.member_info: dict[int, Cog_User_Info] = {}

        self.DB_Monitor.start()

    @tasks.loop(seconds=10)
    async def DB_Monitor(self):
#need a way to ensure monitor shuts down the engine on startup after getting message history
#a way to track queues not changing
#unify the member info across cogs

        if self.bot.___custom.check_voice_idle(idle_time=300): # 5 minutes

            # check for users in the memory dict against the database
            for user in self.member_info.values():
                if not user.checked_against_db:
                    response = await self.check_user(disc_member=user)
                    if type(response) is dict:
                        logger.info(f"Logged in user info changed {(', '.join([f'{key}={value}' for key, value in response.items()]))}")
                    user.checked_against_db = True

            # process login/logout queue
            process_list = []
            for record in self.queues.db_loginout:
                if record['in_time'] and record['out_time']:
                    process_list.append(record)                
            self.record_loginout(logins=process_list)
            for index, record in enumerate(self.queues.db_loginout.reverse()):
                if record['db_commit']:
                    self.queues.db_loginout.remove(record)

            # process messages queue
            self.record_messages(disc_messages=self.queues.db_message)
            for index, record in enumerate(self.queues.db_message):
                if record['db_commit']:
                    self.queues.db_message.remove(record)

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

    def user_login_q(self, member_id: int) -> bool:
       
       # get user info from memory dict
       member_info = self.get_member_info(member_id=member_id)
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
    
    def user_logout_q(self, member_id: int) -> bool:
        member_info = self.get_member_info(member_id)
        if not member_info:
            return False
        elif not member_info.last_DB_InOut:
            logger.info('lno loginout record - expected if bot starts and user does not have activity before leaving channel')
            self.user_login_q(member_id=member_id)
            self.user_logout_q(member_id=member_id)
            return False
        else:
            member_info.last_DB_InOut['out_time'] = datetime.now()
            return True

    def get_member_info(self, member_id: int) -> Cog_User_Info:
        if member_id not in self.member_info:
            discord_member = self.bot.get_user(member_id)
            member_object = Cog_User_Info(
                    member_id = member_id,
                    name = discord_member.name,
                    display_name = discord_member.display_name,
                    global_name = discord_member.global_name, 
                    timestamp_creation = datetime.now(),
                    bot=discord_member.bot
            )
            self.member_info[member_id] = member_object
            return member_object
        else:
            return self.member_info[member_id]
        
    @commands.Cog.listener('voice_client_connected')
    async def voice_client_connected(self, members: list[Member], *args, **kwargs):
        for member in members:
            self.user_login_q(member.id)
        for member in self.bot.___custom.voice_channel.members:
            self.user_login_q(member.id)

    @commands.Cog.listener('on_connect')
    async def on_connect(self):
        if not await self.check_tables():
            await self.create_tables()

    @commands.Cog.listener('on_ready')
    async def on_ready(self, *args, **kwargs):
        pass

    @commands.Cog.listener('on_voice_member_speaking_state')
    async def on_voice_member_speaking_state(self, member: Member, *args, **kwargs):
        #logger.info(f'on_voice_member_speaking_state args {args} kwargs {kwargs}')
        self.user_login_q(member_id=member.id)

    @commands.Cog.listener('on_voice_state_update')
    async def on_voice_state_update(self, member: Member, before: VoiceState, after: VoiceState):
        if before.channel == self.bot.___custom.voice_channel:
            self.user_logout_q(member_id=member.id)
        if after.channel == self.bot.___custom.voice_channel:
            self.user_login_q(member_id=member.id)

    async def cleanup(self):
        for member in self.bot.___custom.voice_channel.members:
            self.user_logout_q(member_id=member.id)
        if self.queues.db_loginout:
            await self.record_loginout(logins=self.queues.db_loginout)
        if self.queues.db_message:
            await self.record_messages(disc_messages=self.queues.db_message)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SQL_Interface(bot))

class SQL_Interface_Test(SQL_Interface_Base):
    def __init__(self, config: dict):
        super().__init__()
        self.set_config(config=config)

    def set_config(self, config):
        self.host = config['sql_db_host']
        self.port = config['sql_db_port']
        self.user = config['sql_db_user']
        self.password = config['sql_db_password']
        self.database = config['sql_db_database']
        self.server_type = config['sql_db_type']
        self.sqlite_filename = config['sql_db_sqlite_file']
        self.engine = self.get_engine()
        self.factory = self.get_session_factory()
        
    async def drop_tables(self):
        # Drop the tables in the database
        async with self.engine.begin() as conn: 
           await conn.run_sync(self.Base.metadata.drop_all)

    async def populate_tables(self):
        # join, depart, message, bot message
        
        Alice = Cog_User_Info(name= 'Alice', member_id=1001, timestamp_creation=datetime.now(), display_name=None, global_name=None, bot = False)
        Bob = Cog_User_Info(name='Bob', member_id=2001, timestamp_creation=datetime.now(), display_name=None, global_name=None, bot=False)
        Cindy = Cog_User_Info(name= 'Cindy', member_id=3001, timestamp_creation=datetime.now(), display_name=None, global_name=None, bot=False)

        userlist = [Alice, Bob, Cindy]

        Bot_Zak = Cog_User_Info(name= 'Zak', member_id=10, bot = True, timestamp_creation=datetime.now(), display_name=None, global_name=None)
        Bot_Yasmeen = Cog_User_Info(name= 'Yasmeen', member_id=11, bot=True, timestamp_creation=datetime.now(), display_name=None, global_name=None)
        bot_list = [Bot_Zak, Bot_Yasmeen]

        listeners = []
        listener_names = []
        await self.check_user(disc_member=Bot_Yasmeen)
        await self.login_user(member_id=Bot_Yasmeen.member_id)
        listeners.append(Bot_Yasmeen.member_id)
        listener_names.append(Bot_Yasmeen.name)
        await asyncio.sleep(1)
        await self.check_user(disc_member=Bot_Zak)
        await self.login_user(member_id=Bot_Zak.member_id)
        listeners.append(Bot_Zak.member_id)
        listener_names.append(Bot_Zak.name)
        await asyncio.sleep(1)
        await self.check_user(disc_member=Alice)
        await self.login_user(member_id=Alice.member_id)
        listeners.append(Alice.member_id)
        listener_names.append(Alice.name)
        await asyncio.sleep(1)
        print(listeners)
        await self.record_messages(disc_messages=[
            Discord_Message(
                member_id= Alice.member_id, 
                member=Alice.name, text ='Hello', 
                listeners = listeners, 
                listener_names=listener_names, 
                tokens=50,
                timestamp_creation = datetime.now(), 
                )])
        await asyncio.sleep(1)
        await self.record_messages(disc_messages=
            [Discord_Message(
                member= Bot_Zak.name,
                member_id= Bot_Zak.member_id, 
                text= 'Hi there!',
                listeners=listeners,listener_names=listener_names,
                tokens=50,
                timestamp_creation = datetime.now(), 
                )])
        await asyncio.sleep(1)
        
        await self.check_user(disc_member=Bob)
        await self.login_user(member_id=Bob.member_id)
        listeners.append(Bob.member_id)
        listener_names.append(Bob.name)
        await asyncio.sleep(1)
        print(listeners)
        await self.record_messages(disc_messages=
            [Discord_Message(
                member= Bob.name,
                member_id= Bob.member_id,
                text ='Hello',
                listeners = listeners,
                listener_names=listener_names, 
                tokens=50,
                timestamp_creation = datetime.now(),
                )])
        await asyncio.sleep(1)
        await self.record_messages(disc_messages=
            [Discord_Message(
                member= Bot_Yasmeen.name,
                member_id= Bot_Yasmeen.member_id,
                text= 'Hi there!',
                listeners=listeners,
                listener_names=listener_names,
                tokens=50,
                timestamp_creation = datetime.now(),
                )])
        await asyncio.sleep(1)

        await self.check_user(disc_member=Cindy)
        await self.login_user(member_id=Cindy.member_id)
        await asyncio.sleep(1)
        listeners.append(Cindy.member_id)
        listener_names.append(Cindy.name)
        print(listeners)
        await self.record_messages(disc_messages=
            [Discord_Message(
                member = Cindy.name,
                member_id = Bob.member_id,
                text ='Hello',
                listeners = listeners,
                listener_names=listener_names, 
                tokens=50,
                timestamp_creation = datetime.now(),
                )])
        await asyncio.sleep(1)
        await self.record_messages(disc_messages=
            [Discord_Message(
                member= Bot_Yasmeen.name,
                member_id= Bot_Yasmeen.member_id,
                text= 'Hi there!',
                listeners=listeners,
                listener_names=listener_names,
                tokens=50,
                timestamp_creation = datetime.now(),
                )])
        await asyncio.sleep(1)

        print(listeners)
        await self.record_messages(disc_messages=[Discord_Message(timestamp_creation = datetime.now(), member= Bob.name, member_id= Bob.member_id, text ='Bye',  listeners = listeners, listener_names=listener_names, tokens=50)])
        await asyncio.sleep(1)
        await self.logout_user(member_id= Bob.member_id)
        await asyncio.sleep(1)
        listeners.remove(Bob.member_id)
        listener_names.remove(Bob.name)
        print(listeners)

        await asyncio.sleep(1)
        await self.record_messages(disc_messages=[Discord_Message(timestamp_creation = datetime.now(), member= Alice.name, member_id= Alice.member_id, text ='Bob left',  listeners = listeners, listener_names=listener_names, tokens=50)])
        await asyncio.sleep(1)
        await self.record_messages(disc_messages=[Discord_Message(timestamp_creation = datetime.now(), member= Cindy.name, member_id= Cindy.member_id, text ='bye bob',  listeners =  listeners, listener_names=listener_names, tokens=50)])
        await asyncio.sleep(1)

        await self.record_messages(disc_messages=[Discord_Message(timestamp_creation = datetime.now(), member= Alice.name, member_id= Alice.member_id, text ='Bye',  listeners = listeners, listener_names=listener_names, tokens=50)])
        await asyncio.sleep(1)
        await self.logout_user(member_id= Alice.member_id)
        await asyncio.sleep(1)
        listeners.remove(Alice.member_id)
        listener_names.remove(Alice.name)
        print(listeners)

        await self.record_messages(disc_messages=[Discord_Message(timestamp_creation = datetime.now(), member= Cindy.name, member_id= Cindy.member_id, text ='I feel all alone',  listeners =  listeners, listener_names=listener_names, tokens=50)])
        await asyncio.sleep(1)
        await self.record_messages(disc_messages=[Discord_Message(timestamp_creation = datetime.now(), member=Bot_Yasmeen.name, member_id= Bot_Yasmeen.member_id, text= 'I am here' , listeners=listeners, listener_names=listener_names, tokens=50)])
        await asyncio.sleep(1)
        await self.record_messages(disc_messages=[Discord_Message(timestamp_creation = datetime.now(), member= Bot_Zak.name, member_id= Bot_Zak.member_id, text= 'You have us!' , listeners=listeners, listener_names=listener_names, tokens=50)])
        await asyncio.sleep(1)

        await self.check_user(disc_member=Cindy)
        await self.login_user(member_id= Bob.member_id)
        await asyncio.sleep(1)
        listeners.append(Bob.member_id)
        listener_names.append(Bob.name)
        print(listeners)
        await self.record_messages(disc_messages=[Discord_Message(timestamp_creation = datetime.now(), member= Bob.name, member_id= Bob.member_id, text ='I  am back!',  listeners = listeners, listener_names=listener_names, tokens=50)])
        await asyncio.sleep(1)

        await self.record_messages(disc_messages=
            [Discord_Message(
                timestamp_creation = datetime.now(), 
                member= Cindy.name, 
                member_id= Cindy.member_id, 
                text ='These bots are freaking me out',  
                listeners = listeners, 
                listener_names=listener_names, 
                tokens=50
                )])
        await asyncio.sleep(1)
        await self.record_messages(disc_messages=
            [Discord_Message(
                timestamp_creation = datetime.now(),
                member= Bob.name, 
                member_id= Bob.member_id, 
                text ='yeah, lets get out of here',
                listeners = listeners,
                listener_names=listener_names,
                tokens=50)])
        await asyncio.sleep(1)

        await self.logout_user(member_id= Cindy.member_id)
        await asyncio.sleep(1)
        listeners.remove(Cindy.member_id)
        listener_names.remove(Cindy.name)
        print(listeners)
        await self.logout_user(member_id= Bob.member_id)
        await asyncio.sleep(1)
        listeners.remove(Bob.member_id)
        listener_names.remove(Bob.name)
        print(listeners)        

    async def display_history(self):
        async with self.factory() as session: 
            result = await session.execute(select(Users))
            #all_users = result.scalars().all()
            for user in result.scalars().unique():
                message_history = await self.get_message_history(user.id)
                print(f"Message history for {user.name}:")
                for key, value in message_history.items():
                    print(f"{key}: {value.text}            {value.listeners} {value.listener_names} ")

if __name__  == '__main__':
    async def main():
        import argparse    
        from dotenv import dotenv_values
        
        config = dotenv_values('../.env')

        parser = argparse.ArgumentParser()
        parser.add_argument("-tc", "--test_connection", action= 'store_true', help="Test the connection to the database")
        parser.add_argument("-lt", "--list_tables",  action='store_true', help="List all tables")
        parser.add_argument('-ct', '--create_tables', action='store_true', help="Create the tables in the database")
        parser.add_argument('-cht', '--check_tables', action='store_true', help="Check the tables in the database")
        parser.add_argument('-dt', '--drop_table', action='store_true', help="Drop(delete) the tables in the database")
        parser.add_argument('-pt', '--populate_tables', action='store_true', help="simulate login, logout, messages")
        parser.add_argument('-dh', '--display_history',action='store_true', help='Display message history')

        sql_object = SQL_Interface_Test(config)

        args = parser.parse_args()
        if args.list_tables:
            print(await sql_object.list_tables())
        elif args.create_tables: 
            await sql_object.create_tables()
        elif args.check_tables: 
            if await sql_object.check_tables():
                print("Tables exist")
            else:
                print("Tables do not exist")
        elif args.drop_table:  
            await sql_object.drop_tables()
        elif args.populate_tables:
            await sql_object.populate_tables()
        elif args.display_history:
            await sql_object.display_history()

        #await sql_object.create_tables()
        #if not await sql_object.check_tables():
        #    sql_object.create_tables()

        #await sql_object.list_tables()
        #await sql_object.drop_tables()
        #await sql_object.populate_tables()
        #await sql_object.display_history()

    asyncio.run(main())