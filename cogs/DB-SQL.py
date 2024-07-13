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

    on_LLM_message: Discord_Message
        called when an LLM message is sent. Stores it in the database

    on_STT_event: Discord_Message
        called when a STT event is detected. Stores it in a list and request
        token count from the LLM cog.

    on_interrupted_message: Discord_Message
        message from the LLM to update the message text to indicate which sentences
        were interrupted by the user speaking.

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
from typing import Optional
from typing_extensions import Annotated

from discord import Member
from discord.ext import commands

from sqlalchemy import Integer, BigInteger,String , DateTime, Text, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, writeonly
from sqlalchemy.sql import text
from sqlalchemy.future import select
from sqlalchemy.sql.expression import desc, asc
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine, AsyncSession, AsyncAttrs

from utils.datatypes import Discord_Message, Commands_Bot

str_255 = Annotated[str, mapped_column(String(255))]

logger = logging.getLogger(__name__)

class Base(DeclarativeBase, AsyncAttrs):
    pass

class Users(Base):
    __tablename__ = 'user'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str_255]
    real_name: Mapped[Optional[str_255]]
    timestamp_creation = mapped_column(DateTime, nullable=False, server_default=func.now())
    bot: Mapped[bool] = mapped_column(default=False)
    info: Mapped[Optional['UserInfo']] = relationship()
    logs: Mapped[list['UserLog']] = relationship(lazy='selectin')
    messages: Mapped[list['Messages']] = relationship(lazy='selectin', back_populates='user')#, order_by=desc('messages.timestamp'))
    messages_listened_to: Mapped[list['MessageListeners']] = relationship(lazy='selectin')#, order_by='desc(MessageListeners.timestamp)')

class UserInfo(Base):
    __tablename__ = 'user_info'
    id: Mapped[int] = mapped_column(BigInteger, ForeignKey('user.id'), primary_key= True)
    text: Mapped[Optional[str]] = mapped_column(Text)

class UserLog(Base):
    __tablename__ = 'user_log'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('user.id'))
    timestamp_in: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    timestamp_out: Mapped[Optional[datetime]]

class Messages(Base):
    __tablename__ = 'messages'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] =  mapped_column(BigInteger, ForeignKey('user.id'))
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    tokens: Mapped[int]
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    listeners: Mapped[list['MessageListeners']] = relationship(back_populates= 'message', lazy='selectin')
    user: Mapped[Users] = relationship(back_populates='messages', lazy='selectin')
    discord_text_message_id: Mapped[int]

class MessageListeners(Base):
    __tablename__ = 'message_listeners'  # table name
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey('messages.id'))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('user.id'))
    message: Mapped[Messages] = relationship(back_populates='listeners', lazy='selectin')
    users: Mapped[Users] = relationship(back_populates='messages_listened_to', lazy='selectin')

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
        self.users = Users
        self.user_log = UserLog
        self.messages = Messages
        self.message_listeners = MessageListeners
        self.user_info = UserInfo

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

    async def check_user(self, member_id: int, name: str, bot: bool):
        '''
        Check if the user is in the database and add them if they are not
        '''
        async with self.factory() as session:
            async with session.begin():
                user = await session.get(self.users, member_id)

                if user is None:
                    user  = self.users(id=member_id, name=name, bot=bot)
                    session.add(user)
                    await session.commit()
    
    async def login_user(self, member_id: int):
        '''
        login the user with a timestamp, if they are not already logged in by
        checking checking timestamp_out and create a new login by adding a new 
        record if timestamp_out is not None.
        '''
        async with self.factory() as session:
            async with session.begin():
                user = await session.get(self.users, member_id)
                if user.logs in [None, []]:
                    session.add(self.user_log(user_id=user.id))
                elif user.logs[-1].timestamp_out is not None:
                    session.add(self.user_log(user_id=user.id))
                    await session.commit()

    async def logout_user(self, member_id: int, all: bool = False):
        '''
        log out user with a timestamp. the all parameter is used during
        the cleanup method
        '''
        async with self.factory() as session:
            async with session.begin():
                if all == True:
                    users = await session.execute(select(self.users))
                    for user in users.scalars().all():
                        if user.logs[-1].timestamp_out is None:
                            user.logs[-1].timestamp_out = func.now()
                else: 
                    user = await session.get(self.users, member_id)
                    if user is None:
                        raise Exception('No such user exists in the database.')
                    
                    if user.logs[-1].timestamp_out is not None:
                        raise Exception('User already departed, no new logout record to be created.')
                    else:
                        user.logs[-1].timestamp_out = func.now()
            await session.commit()

    async def message(self, message: Discord_Message): 
        '''
        adds a message to the message tabel and updates the message_listeners 
        table. This allows the message history to contain messges they
        witnessed.
        '''    
        async with self.factory() as session:
            async with session.begin():

                user = await session.get(self.users, message.member_id)
            
                if user is None: 
                    raise Exception('No such user exists in the database on message creation.')

                user.messages.append(self.messages(id = message.message_id,
                            message_text=message.text, 
                            tokens=message.tokens))
                await session.flush()

                for listener in message.listeners:
                    
                    listener_record = await session.get(self.users, listener)

                    if listener_record is None:
                        raise Exception('No such user exists in the database on message creation.')

                    session.add(self.message_listeners(user_id = listener_record.id
                                                , message_id=user.messages[-1].id))
            
                await session.commit()

    async def update_message_text(self, message: Discord_Message):
        '''
        gets the message from the message.id and updates the text to the new value
        '''
        async with self.factory() as session:
            message_record = await session.get(self.messages, message.message_id)
            message_record.message_text = message.text
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
                
                user = await session.get(self.users, member_id)

                for _ in range (len(user.messages_listened_to), 0, -1):
                    message_listened_to = user.messages_listened_to[(_ - 1)]

                    await session.refresh(message_listened_to.message)
                    await session.refresh(message_listened_to.message.user)

                    current_message = Discord_Message(
                            member_id = message_listened_to.message.author_id,
                            member = message_listened_to.message.user.name,
                            text = message_listened_to.message.message_text,
                            tokens = message_listened_to.message.tokens,
                            message_id = message_listened_to.message.id,
                            listeners = [listener.user_id for listener in message_listened_to.message.listeners],
                            listener_names = [listener.users.name for listener in message_listened_to.message.listeners]
                        )

                    message_history.update({current_message.message_id: current_message})
                    total_tokens += current_message.tokens
                    if total_tokens > max_tokens:
                        break
 
                return message_history

    async def update_tokens(self, message: Discord_Message) -> bool:
        '''
        checks the database for a message and update the token. if the
        message is not in the database it will add the message to the 
        database
        '''
        async with self.factory() as session:
            async with session.begin():
                message_record = await session.get(self.messages, message.message_id)
                if message_record is not None:
                    message_record.tokens = message.tokens
                    await session.commit()
                else:
                    await self.message(message=message)
        return True
            
class SQL_Interface(commands.Cog, SQL_Interface_Base):
    def __init__(self, bot: Commands_Bot) -> None:
        self.bot:Commands_Bot = bot
        SQL_Interface_Base.__init__(self)
        self.message_waiting_for_token_count = []
        self.set_config()

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

    @commands.Cog.listener('on_ready')
    async def on_ready(self):
        if not await self.check_tables():
            await self.create_tables()
        logger.info('ready')

    @commands.Cog.listener('on_LLM_message')
    async def on_LLM_message(self, message: Discord_Message = None, messages = list[Discord_Message]):
        #logger.info(message)
        if message:
            await self.message(message=message)
        elif messages:
            for message in messages:
                await self.message(message=message)

    @commands.Cog.listener('on_tokens_counted')
    async def on_tokens_counted(self, message: Discord_Message):
        if await self.update_tokens(message=message):
            self.message_waiting_for_token_count.remove(message)

    @commands.Cog.listener('on_interrupted_message')
    async def on_interrupted_message(self, message: Discord_Message):
        await self.update_message_text(message=message)

    @commands.Cog.listener('on_voice_member_speaking_state')
    async def on_voice_member_speaking_state(self, member: Member, *args, **kwargs):
        await self.check_user(member_id = member.id, 
                name = member.name,
                bot = member.bot )
        await self.login_user(member_id = member.id)
        message_history = await self.get_message_history(member_id=member.id)
        self.bot.dispatch(f'message_history', message_history= message_history)

    @commands.Cog.listener('on_voice_member_disconnect')
    async def on_voice_member_disconnect(self, member: Member, *args, **kwargs):
        await self.logout_user(member_id = member.id)

    @commands.Cog.listener('on_voice_client_connected')
    async def on_voice_client_connected(self, members: list[Member], *args, **kwargs):
        logger.info('voice client connected')
        for member in members:
            await self.check_user(member_id = member.id, 
                    name = member.name,
                    bot = member.bot)
            await self.login_user(member_id=member.id)
            if member.bot != True:
                self.bot.dispatch(f'message_history', message_history=await self.get_message_history(member_id=member.id))
        
    async def cleanup(self):
        # will need to add in token counting if a message has 0 tokens
        # upon loading
        for message in self.message_waiting_for_token_count:
            await self.message(message=message)
        self.message_waiting_for_token_count.clear()
        await self.logout_user(member_id=None, all=True)
        pass

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
        from dataclasses import dataclass

        @dataclass
        class test_user():
            name: str 
            id: int

        Alice = test_user(name= 'Alice', id=1001)
        Bob = test_user(name=  'Bob', id=2001)
        Cindy = test_user(name= 'Cindy' , id=3001)
        userlist = [Alice, Bob, Cindy]

        Bot_Zak = test_user(name= 'Zak', id=10)
        Bot_Yasmeen = test_user(name=  'Yasmeen', id=11)
        bot_list = [Bot_Zak, Bot_Yasmeen]

        await self.check_user(name= Bot_Yasmeen.name, member_id=Bot_Yasmeen.id, bot=True)
        await self.login_user(member_id=Bot_Yasmeen.id)
        await asyncio.sleep(1)
        await self.check_user(name= Bot_Zak.name, member_id=Bot_Zak.id, bot=True)
        await self.login_user(member_id=Bot_Zak.id)
        await asyncio.sleep(1)
        await self.check_user(name= Alice.name,  member_id= Alice.id, bot=False)
        await self.login_user(member_id=Alice.id)
        await asyncio.sleep(1)
        listeners = [Alice.id, Bot_Zak.id, Bot_Yasmeen.id]
        listener_names= [Alice.name, Bot_Zak.name, Bot_Yasmeen.name]
        print(listeners)
        await self.message(Discord_Message(member_id= Alice.id, member=Alice.name, text ='Hello',  listeners = listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.message(Discord_Message(member= Bot_Zak.name, member_id= Bot_Zak.id , text= 'Hi there!' , listeners=listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        
        await self.check_user(name= Bob.name,  member_id= Bob.id, bot=False)
        await self.login_user(member_id=Bob.id)
        await asyncio.sleep(1)
        listeners.append(Bob.id)
        listener_names.append(Bob.name)
        print(listeners)
        await self.message(Discord_Message(member= Bob.name ,member_id= Bob.id, text ='Hello',  listeners = listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.message(Discord_Message(member= Bot_Yasmeen.name, member_id= Bot_Yasmeen.id, text= 'Hi there!' ,  listeners=listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)

        await self.check_user(name= Cindy.name,  member_id= Cindy.id, bot=False)
        await self.login_user(member_id=Cindy.id)
        await asyncio.sleep(1)
        listeners.append(Cindy.id)
        listener_names.append(Cindy.name)
        print(listeners)
        await self.message(Discord_Message(member= Cindy.name ,member_id= Bob.id, text ='Hello',  listeners = listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.message(Discord_Message(member= Bot_Yasmeen.name, member_id= Bot_Yasmeen.id, text= 'Hi there!' , listeners=listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)

        print(listeners)
        await self.message(Discord_Message(member= Bob.name, member_id= Bob.id, text ='Bye',  listeners = listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.logout_user(member_id= Bob.id)
        await asyncio.sleep(1)
        listeners.remove(Bob.id)
        listener_names.remove(Bob.name)
        print(listeners)

        await asyncio.sleep(1)
        await self.message(Discord_Message(member= Alice.name, member_id= Alice.id, text ='Bob left',  listeners = listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.message(Discord_Message(member= Cindy.name, member_id= Cindy.id, text ='bye bob',  listeners =  listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)

        await self.message(Discord_Message(member= Alice.name, member_id= Alice.id, text ='Bye',  listeners = listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.logout_user(member_id= Alice.id)
        await asyncio.sleep(1)
        listeners.remove(Alice.id)
        listener_names.remove(Alice.name)
        print(listeners)

        await self.message(Discord_Message(member= Cindy.name, member_id= Cindy.id, text ='I feel all alone',  listeners =  listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.message(Discord_Message(member=Bot_Yasmeen.name, member_id= Bot_Yasmeen.id, text= 'I am here' , listeners=listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.message(Discord_Message(member= Bot_Zak.name, member_id= Bot_Zak.id, text= 'You have us!' , listeners=listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)

        await self.check_user(name= Bob.name,  member_id= Bob.id, bot=False)
        await self.login_user(member_id= Bob.id)
        await asyncio.sleep(1)
        listeners.append(Bob.id)
        listener_names.append(Bob.name)
        print(listeners)
        await self.message(Discord_Message(member= Bob.name, member_id= Bob.id, text ='I  am back!',  listeners = listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)

        await self.message(Discord_Message(member= Cindy.name, member_id= Cindy.id, text ='These bots are freaking me out',  listeners =  listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)
        await self.message(Discord_Message(member= Bob.name, member_id= Bob.id, text ='yeah, lets get out of here',  listeners = listeners, listener_names=listener_names, tokens=50))
        await asyncio.sleep(1)

        await self.logout_user(member_id= Cindy.id)
        await asyncio.sleep(1)
        listeners.remove(Cindy.id)
        listener_names.remove(Cindy.name)
        print(listeners)
        await self.logout_user(member_id= Bob.id)
        await asyncio.sleep(1)
        listeners.remove(Bob.id)
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