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


    todo: check saving users and bots
    
'''
import logging, json
from datetime import datetime
from collections import deque
from typing import Union, List, Tuple

from sqlalchemy import select
from sqlalchemy.sql import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine, AsyncSession

import scripts.db_sql_tables as db_t

from scripts.datatypes import db_in_out, db_client, info_table
from scripts.datatypes import Discord_Message as Client_Message

logger = logging.getLogger(__name__)

class SQL_Interface_Base():
    def __init__(self, config: dict, user_info: dict[Union[str,int], db_client]):
        self.host = config['sql_db_host']
        self.port = config['sql_db_port']
        self.user = config['sql_db_user']
        self.password = config['sql_db_password']
        self.database = config['sql_db_database']
        self.server_type = config['sql_db_type']
        self.sqlite_filename = config['sql_db_sqlite_file']
        self.Base = db_t.Base
        self.engine: AsyncEngine = self.get_engine()
        self.factory = async_sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.user_info: dict[int, db_client] = user_info
#        self.bot_info: dict[str, info_table] = bot_info
        
    def validate_settings(self):
        if (not self.sqlite_filename) and (self.server_type == 'sqlite'):
            # bot will run fine if without any db, so no point run this
            # without a file
            raise Exception("db type set to sqlite and sql_db_sqlite_file is not set in .env")
        elif not (self.host and self.port and self.user and self.password and self.database):
            raise Exception("sql_db_host, sql_db_port, sql_db_user, sql_db_password, sql_db_database error. check .env")

    def get_engine(self) -> AsyncEngine:
        if self.server_type == 'sqlite':
            return create_async_engine(f"sqlite+aiosqlite:///{self.sqlite_filename}")
        elif self.server_type in ['mysql', 'mariadb']:
            return create_async_engine(f"mysql+asyncmy://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}")
        elif self.server_type == 'postgreslq':
            return create_async_engine(f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}/{self.database}")
        else:
            raise Exception('Invalid config, check settings')

    def get_session_factory(self) -> AsyncSession:
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
         
    async def _get_users(self, session) -> dict[int, db_t.Users]:
       users: list[db_t.Users] = await session.scalars(select(db_t.Users))
       return {user.user_id: user for user in users}

    async def _get_bots(self, session) -> dict[int, db_t.Bots]:
       bots: list[db_t.Bots] = await session.scalars(select(db_t.Bots))
       return {bot.id: bot for bot in bots}
         
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

    async def db_get_users(self) -> dict[int, db_client]:
        '''
        retreive all users from the database.
        '''
        async with self.factory() as session:
            user_info: dict[Union[int, str], db_client]= {}
            users:dict[int, db_t.Users] = await self._get_users(session)
            bots:dict[str, db_t.Bots] = await self._get_bots(session)
            # add to users_to_return dict
            for user in users.values():
                user_info[user.user_id] = db_client(
                    user_id=user.user_id,
                    name = user.user_name,
                    global_name= user.global_name,
                    display_name=user.display_name,
                    info = json.loads(user.info),
                    bot = False
                    )
            for bot in bots.values():
                cur_bot = db_client(
                        bot_uid=bot.message_key,
                        name = bot.name,
                        voice = bot.voice,
                        speaker=bot.speaker,
                        personality=bot.personality
                        )
                #get knowledge from db_t.bot.knowledge
                result:list[db_t.Bot_kof_Users] = await session.execute(select(db_t.Bot_kof_Users).where(db_t.Bot_kof_Users.bot_id == bot.id))
                for item in result:
                    cur_bot.knowledge_user[item.user_id] = json.dumps(item.knowledge)
                    cur_bot.opinion_user[item.user_id] = json.dumps(item.opinion)
                
                #get knowledge from db_t.bot.bot_knowledge
                result:List[db_t.Bot_kof_Bots] = await session.execute(select(db_t.Bot_kof_Bots).where(db_t.Bot_kof_Bots.bot_id == bot.id))
                for item in result:
                    cur_bot.knowledge_bot[item.other_bot_id] = json.dumps(item.knowledge)
                    cur_bot.opinion_bot[item.other_bot_id] = json.dumps(item.opinion)

                user_info[cur_bot.user_id] = cur_bot
            return self.user_info

    async def  db_store_bot(self, session: AsyncSession, client: db_client, bots: dict[str, db_t.Bots]) -> None:
        pass

    async def db_store_user(self,  session: AsyncSession, client: db_client, users: dict[int, db_t.Users]):
        if client.user_id not in users.keys():
            user = db_t.Users(
                user_id  = client.user_id,
                user_name = client.name.capitalize(),
                bot = client.bot,
                display_name = client.display_name,
                global_name = client.global_name,
                timestamp_creation = client.timestamp,
                info = json.dumps(client.info)
                )
            if len(client.info) > 0:
                user.info = json.dumps(client.info)
            session.add(user)
        else:
            response = []
            user = users[client.user_id]
            if user.user_name != client.name:
                response.append(f'{client.name} to {user.user_name}')
                if client.name:
                    user.user_name = client.name
            if user.display_name != client.display_name:
                response.append(f'{client.display_name} to {user.display_name}')
                if client.display_name:
                    user.display_name = client.display_name
            if user.global_name != client.global_name:
                response.append(f'{client.global_name} to {user.global_name}')
                if client.global_name:
                    user.global_name = client.global_name
            user.info = json.dumps(client.info)
        return {client.user_id : ', '.join(response)}

    async def db_add_user(self, clients: List[db_client]|db_client) -> Union[False, dict[id, str]]:
        '''
        Check if the user is in the database and add them if they are not
        True - User logged in
        dict - returns a dict[user_id:str] of the user name changes
        '''
        if type(clients) != list:
            clients:List[db_t.Users] = [clients]
        async with self.factory() as session:
            async with session.begin():
                response_dict = {}
                bots = await self._get_bots(session)
                users = await self._get_users(session)
                for client in clients:
                    if client.bot:
                        response_dict += await self.db_store_bot(session, client, bots)
                    else:
                        response_dict +=await self.db_store_user(session, client, users)

                    await session.commit()
                if len(response_dict) > 0:
                    return response_dict
                else:
                    return False

    async def process_loginout(self, in_out: list[db_in_out]|db_in_out):
        '''
        Record the login and logouts of users in the database. 

        only prosses those records with both login and logout fields to be present 
        in each dictionary records
        '''
        if type(in_out) is not list:
            in_out = [in_out]
        async with self.factory() as session:
            async with session.begin():
                user = await self._get_users(session)
                bots = await self._get_bots(session)
                for login in in_out:
                    if login['in_time'] is None or login['out_time'] is None:
                        continue
                    #logger.info(f'record loginout - user - {user}')
                    if user is None:
                        logger.info(f'User {login["user_id"]} not found in database')
                        continue
                    new_login = db_t.UserLog(user_id = user.user_id, 
                            timestamp_in = login['in_time'],
                            timestamp_out = login['out_time'])
                    session.add(new_login)
                    session.flush()
                    login['db_commit'] = True
                await session.commit()

    async def record_messages(self, client_messages: list[Client_Message]|Client_Message): 
        '''
        adds a message to the message tabel and updates the message_listeners 
        table. This allows the message history to contain messges they
        witnessed.

        expects the user and bot to be in the database already
        first sorts the list based on message.timestamp
        '''
        if type(client_messages) is not list:
            client_messages:List[Client_Message] = [client_messages]
        client_messages = sorted(client_messages, key=lambda x: x.timestamp)
        async with self.factory() as session:
            async with session.begin():
                users_objects: dict[int, db_t.Users] = self._get_users(session)
                bots_objects: dict[str, db_t.Bots] = self._get_bots(session)

                for cli_msg in client_messages:
                    new_db_msg = db_t.Messages(
                            text = cli_msg.text,
                            timestamp = cli_msg.timestamp,
                            text_corrected = cli_msg.text_llm_corrected,
                            text_interrupted = cli_msg.text_user_interrupt,
                            tokens = cli_msg.tokens,
                            prompt_type = cli_msg.prompt_type
                            )
                    if cli_msg.user_id:
                        new_db_msg.user_id = users_objects[cli_msg.user_id].user_id
                    else:
                        new_db_msg.bot_id = bots_objects[cli_msg.bot_id].id

                    for listener in cli_msg.listener_ids:
                        if listener in users_objects.keys():
                            new_db_msg.listeners.append(users_objects[listener].user_id)
                        else:
                            new_db_msg.listeners.append(bots_objects[listener].id)
                    session.add(new_db_msg)

                await session.commit()
                for client_message in client_messages:
                    client_message.stored_in_db = True

    async def get_message_history(self, max_tokens: int = 32768, user_id: int = None) -> List[Client_Message]:
        '''
        get a history for all users in the db limited by max_tokens per user

        if a user_id is provided then only return messages for that user
        '''
        async with self.factory() as session:
            async with session.begin():
                message_history: dict[int, Client_Message] = {}
                users_objects: dict[int, db_t.Users] = self._get_users(session)
                bots_objects: dict[str, db_t.Bots] = self._get_bots(session)
                for user in users_objects.values():
                    if user.messages_listened is None:
                        continue
                    ql = select(db_t.Messages, db_t.MessageListeners).join(db_t.MessageListeners).where(db_t.MessageListeners.message_id == db_t.Messages.id)
                    messages:List[Tuple[db_t.Messages, db_t.MessageListeners]] = await session.execute(ql)
                    total_tokens = 0
                    for packed_message in messages.reverse():
                        listeners: list[db_t.MessageListeners] = packed_message[1]
                        message: db_t.Messages = packed_message[0]
                
                        # check to see if token max is reached
                        if total_tokens + message.tokens > max_tokens:
                            break
                        total_tokens += message.tokens
                        # check to see if we have already added this message
                        if message.id in message_history.keys():
                            continue
                        cur_mes = Client_Message(
                                text=message.text,
                                text_llm_corrected=message.text_corrected,
                                text_user_interrupt=message.text_interrupted,
                                timestamp=message.timestamp,
                                stored_in_db= message.id,
                                tokens=message.tokens,
                                prompt_type=message.prompt_type)
                    
                        if message.user_id:
                            cur_mes.user_id = message.user_id
                            cur_mes.user_name = users_objects[cur_mes.user_id].user_name
                        elif message.bot_id:
                            cur_mes.bot_id = bots_objects[message.bot_id]
                            cur_mes.bot_name = bots_objects[cur_mes.bot_id].name
                        
                        for listener in listeners:
                            if listener.user_id:
                                cur_mes.listener_ids.add(listener.user_id)
                                cur_mes.listener_names.add(users_objects[listener.user_id].user_name)
                            elif listener.bot_id:
                                cur_mes.listener_ids.add(listener.bot_id)
                                cur_mes.listener_names.add(bots_objects[listener.bot_id].name)

                        message_history[message.id] = cur_mes

                if message_history.items() == 0:
                    return None
                else:
                    return message_history
                
