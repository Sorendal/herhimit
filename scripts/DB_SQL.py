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

Configuration - expected in the .env config file
    sql_db_type - mysql, mariadb, sqlite, postgresql(untested, let me know if this works)
    sql_db_sqlite_file - only for sqlite - ./filename (no ./ causes weirdness)
    sql_db_host - for remote db
    sql_db_port
    sql_db_user
    sql_db_password
    sql_db_database
'''
import logging
from datetime import datetime
from collections import deque
from typing import Optional, Union
from typing_extensions import Annotated

from sqlalchemy import Integer, BigInteger,String, Text, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, registry
from sqlalchemy.sql import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine, AsyncSession, AsyncAttrs

from utils.datatypes import Discord_Message, DB_InOut, Cog_User_Info

str_255 = Annotated[str, mapped_column(String(255))]
str_10 = Annotated[str, mapped_column(String(10))]

logger = logging.getLogger(__name__)

# the default for the sqlalchemy only has time precision to the second.
# this will give it to the hundreth of a second
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.mysql import DATETIME
@compiles(DATETIME, "mysql")
def compile_datetime_mysql(type_, compiler, **kw):
     return "DATETIME(2)"

class Base(DeclarativeBase, AsyncAttrs):
    registry = registry(
        type_annotation_map={
            str_255: String(255),
            str_10: String(10)
        }
    )

class Users(Base):
    __tablename__ = 'Users'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, unique=True)
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
    timestamp_creation: Mapped[datetime] = mapped_column(DATETIME(2))
    tokens: Mapped[int]
    prompt_type: Mapped[str_10]
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
        self.member_info: dict[int, Cog_User_Info] = {}

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

    async def db_check_add_user(self, disc_member: Cog_User_Info) -> Union[True, False, dict]:
        '''
        Check if the user is in the database and add them if they are not
        True - User logged in
        dict - returns a dict of changes
        '''
        async with self.factory() as session:
            async with session.begin():
                user = await session.get(Users, disc_member.member_id)
                response = {}
                #permissions = {}
                if user is None:
                    user = Users(
                        id  = disc_member.member_id,
                        name = disc_member.name.capitalize(),
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
                        response['change_old_name'] = user.name
                        response['change_new_name'] = disc_member.name
                        if disc_member.name:
                            user.name = disc_member.name
                    if user.display_name != disc_member.display_name:
                        response['change_old_display_name'] = user.display_name
                        response['change_new_display_name'] = disc_member.display_name
                        if disc_member.display_name:
                            user.display_name = disc_member.display_name
                    if user.global_name != disc_member.global_name:
                        response['change_old_global_name'] = user.global_name
                        response['change_new_global_name'] = disc_member.global_name
                        if disc_member.global_name:
                            user.global_name = disc_member.global_name
                    if user.bot != disc_member.bot:
                        response['change_old_bot'] = user.bot
                        response['change_new_bot'] = disc_member.bot
                        user.bot = disc_member.bot
                    #for attribute in dir(disc_member):
                    #    if not attribute.startswith('DB'):
                    #        pass
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
                    session.add(UserLog(user_id=user.id, timestamp_in=datetime.now()))
                elif user.logs[-1].timestamp_out:
                    session.add(UserLog(user_id=user.id, timestamp_in=datetime.now()))
                elif user.logs[-1].timestamp_out is not None:
                    session.add(UserLog(user_id=user.id))
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
                    user = await session.get(Users, disc_message.member_id)
                    if user is None:
                        raise Exception('No such user exists in the database on message creation.')
                    if disc_message.member_id not in query_users:
                        query_users[disc_message.member_id] = user
                    for listener in disc_message.listeners:
                        queried_listener = await session.get(Users, listener)
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
                        prompt_type = disc_message.prompt_type,
                        timestamp_creation = disc_message.timestamp_creation,
                        ))
                    await session.flush()
                    for listener in disc_message.listeners:
                        if listener not in query_users.keys():
                            raise Exception('No such user exists in the database on message creation.')
                        session.add(MessageListeners(
                            user_id = query_users[listener].id,
                            message_id=query_users[disc_message.member_id].messages[-1].id))
                await session.commit()
                for disc_message in disc_messages:
                    disc_message.stored_in_db = True

    async def get_message_history(self, member_id: int, 
                    max_tokens: int = 32768) -> dict[datetime, Discord_Message]:
        '''
        get a user history of total tokens, return a dict with a 
            key of message_id and value of Discord_messsage object
        '''
        async with self.factory() as session:
            async with session.begin():
                total_tokens = 0
                message_history: dict[float, Discord_Message] = {}
                
                user = await session.get(Users, member_id)
                if user.messages_listened is None:
                    return None

                for _ in range (len(user.messages_listened), 0, -1):
                    message_listened_to = user.messages_listened[(_ - 1)]

                    await session.refresh(message_listened_to.message)
                    await session.refresh(message_listened_to.message.user)

                    current_message = Discord_Message(
                            member_id = message_listened_to.message.user.id,
                            member =    message_listened_to.message.user.name,
                            text =      message_listened_to.message.text,
                            tokens =    message_listened_to.message.tokens,
                            timestamp_creation = message_listened_to.message.timestamp_creation,
                            listeners = [listener.user_id for listener in message_listened_to.message.listeners],
                            listener_names = [listener.user.name for listener in message_listened_to.message.listeners],
                            stored_in_db=True
                        )

                    message_history[current_message.timestamp_creation] = current_message
                    total_tokens += current_message.tokens
                    if total_tokens > max_tokens:
                        break
                if message_history.items() == 0:
                    return None
                else:
                    return message_history
            