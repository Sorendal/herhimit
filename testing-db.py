import asyncio
from datetime import datetime

from sqlalchemy.ext.compiler import compiles
#from sqlalchemy.types import DateTime
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.future import select
from sqlalchemy import Integer, BigInteger,String, Text, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, registry
from sqlalchemy.sql import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine, AsyncSession, AsyncAttrs

from scripts.datatypes import Discord_Message, db_client, db_in_out, info_table
from scripts.db_sql import SQL_Interface_Base


@compiles(DATETIME, "mysql")
def compile_datetime_mysql(type_, compiler, **kw):
     return "DATETIME(2)"

class SQL_Interface_Test(SQL_Interface_Base):
    def __init__(self, config: dict):
        self.user_info: dict[int, db_client] = {}
        super().__init__(config, user_info=self.user_info)

    async def drop_tables(self):
        # Drop the tables in the database
        async with self.engine.begin() as conn: 
           await conn.run_sync(self.Base.metadata.drop_all)
    
    def gen_message(self, user_id, user_name, text, listeners, listener_names) -> Discord_Message:
        return Discord_Message(
                user_id= user_id, 
                user_name= user_name,
                text =text, 
                listener_ids= listeners, 
                listener_names=listener_names, 
                tokens=50,
                timestamp = datetime.now(),
                prompt_type= 'message'
                )
    


    async def populate_tables(self):
        # join, depart, message, bot message
        
        Alice = db_client(name= 'Alice', user_id=1001, timestamp=datetime.now())
        Bob = db_client(name='Bob', user_id=2001, timestamp=datetime.now()), 
        Cindy = db_client(name= 'Cindy', user_id=3001, timestamp=datetime.now())

        userlist = [Alice, Bob, Cindy]

        Bot_Zak = db_client(name= 'Zak', user_id= 'Zak', bot_uid='Zak', voice = 'test', speaker= 1, personality= 'test', timestamp=datetime.now())
        Bot_Yasmeen = db_client(name= 'Yasmeen',user_id='Yasmeen', bot_uid='Yasmeen', voice= 'test', speaker= 1, personality= 'test', timestamp=datetime.now())

        bot_list = [Bot_Zak, Bot_Yasmeen]
        
        await self.db_get_users()
        quit()
        await self.db_add_user(userlist)

        listeners = []
        listener_names = []
        await self.db_add_user(clients=Bot_Yasmeen)
        await self.login_user(user_id=Bot_Yasmeen.user_id)
        listeners.append(Bot_Yasmeen.user_id)
        listener_names.append(Bot_Yasmeen.name)
        await asyncio.sleep(.1)
        await self.db_check_add_user(disc_member=Bot_Zak)
        await self.login_user(user_id=Bot_Zak.user_id)
        listeners.append(Bot_Zak.user_id)
        listener_names.append(Bot_Zak.name)
        await asyncio.sleep(.1)
        await self.db_check_add_user(disc_member=Alice)
        await self.login_user(user_id=Alice.user_id)
        listeners.append(Alice.user_id)
        listener_names.append(Alice.name)
        await asyncio.sleep(.1)
        print(listeners)
        await self.record_messages(disc_messages=[
            self.gen_message(
                user_name= Bot_Yasmeen.name,
                user_id= Bot_Yasmeen.user_id, 
                text= 'Hi there!',
                listeners=listeners,
                listener_names=listener_names)
                ])
        await asyncio.sleep(.1)
        await self.record_messages(disc_messages=[
            self.gen_message(
                user_name= Bot_Zak.name,
                user_id= Bot_Zak.user_id, 
                text= 'Hi there!',
                listeners=listeners,
                listener_names=listener_names)
            ])
        await asyncio.sleep(.1)
        
        await self.db_check_add_user(disc_member=Bob)
        await self.login_user(user_id=Bob.user_id)
        listeners.append(Bob.user_id)
        listener_names.append(Bob.name)
        await asyncio.sleep(.1)
        print(listeners)
        await self.record_messages(disc_messages=
            [self.gen_message(
                user_name= Bob.name,
                user_id= Bob.user_id,
                text ='Hello',
                listeners = listeners,
                listener_names=listener_names, 
                )])
        await asyncio.sleep(.1)
        await self.record_messages(disc_messages=
            [self.gen_message(
                user_name= Bot_Yasmeen.name,
                user_id= Bot_Yasmeen.user_id,
                text= 'Hi there!',
                listeners=listeners,
                listener_names=listener_names,
                )])
        await asyncio.sleep(.1)

        await self.db_check_add_user(disc_member=Cindy)
        await self.login_user(user_id=Cindy.user_id)
        await asyncio.sleep(.1)
        listeners.append(Cindy.user_id)
        listener_names.append(Cindy.name)
        print(listeners)
        await self.record_messages(disc_messages=
            [self.gen_message(
                user_name= Cindy.name,
                user_id = Bob.user_id,
                text ='Hello',
                listeners = listeners,
                listener_names=listener_names, 
                )])
        await asyncio.sleep(.1)
        await self.record_messages(disc_messages=
            [self.gen_message(
                user_name= Bot_Yasmeen.name,
                user_id= Bot_Yasmeen.user_id,
                text= 'Hi there!',
                listeners=listeners,
                listener_names=listener_names,
                )])
        await asyncio.sleep(.1)

        print(listeners)
        await self.record_messages(disc_messages=[self.gen_message(user_name =Bob.name, user_id= Bob.user_id, text ='Bye',  listeners = listeners, listener_names=listener_names)])
        await asyncio.sleep(.1)
        await self.logout_user(user_id= Bob.user_id)
        await asyncio.sleep(.1)
        listeners.remove(Bob.user_id)
        listener_names.remove(Bob.name)
        print(listeners)

        await asyncio.sleep(.1)
        await self.record_messages(disc_messages=[self.gen_message(user_name =Alice.name, user_id= Alice.user_id, text ='Bob left',  listeners = listeners, listener_names=listener_names)])
        await asyncio.sleep(.1)
        await self.record_messages(disc_messages=[self.gen_message(user_name =Cindy.name, user_id= Cindy.user_id, text ='bye bob',  listeners =  listeners, listener_names=listener_names)])
        await asyncio.sleep(.1)

        await self.record_messages(disc_messages=[self.gen_message(user_name =Alice.name, user_id= Alice.user_id, text ='Bye',  listeners = listeners, listener_names=listener_names)])
        await asyncio.sleep(.1)
        await self.logout_user(user_id= Alice.user_id)
        await asyncio.sleep(.1)
        listeners.remove(Alice.user_id)
        listener_names.remove(Alice.name)
        print(listeners)

        await self.record_messages(disc_messages=[self.gen_message(user_name =Cindy.name, user_id= Cindy.user_id, text ='I feel all alone',  listeners =  listeners, listener_names=listener_names)])
        await asyncio.sleep(.1)
        await self.record_messages(disc_messages=[self.gen_message(user_name=Bot_Yasmeen.name, user_id= Bot_Yasmeen.user_id, text= 'I am here' , listeners=listeners, listener_names=listener_names)])
        await asyncio.sleep(.1)
        await self.record_messages(disc_messages=[self.gen_message(user_name =Bot_Zak.name, user_id= Bot_Zak.user_id, text= 'You have us!' , listeners=listeners, listener_names=listener_names)])
        await asyncio.sleep(.1)

        await self.db_check_add_user(disc_member=Cindy)
        await self.login_user(user_id= Bob.user_id)
        await asyncio.sleep(.1)
        listeners.append(Bob.user_id)
        listener_names.append(Bob.name)
        print(listeners)
        await self.record_messages(disc_messages=[self.gen_message(user_name= Bob.name, user_id= Bob.user_id, text ='I  am back!',  listeners = listeners, listener_names=listener_names)])
        await asyncio.sleep(.1)

        await self.record_messages(disc_messages=
            [self.gen_message(
                user_name= Cindy.name, 
                user_id= Cindy.user_id, 
                text ='These bots are freaking me out',  
                listeners = listeners, 
                listener_names=listener_names, 
                )])
        await asyncio.sleep(.1)
        await self.record_messages(disc_messages=
            [self.gen_message(
                user_name= Bob.name, 
                user_id= Bob.user_id, 
                text ='yeah, lets get out of here',
                listeners = listeners,
                listener_names=listener_names,
            )])
        await asyncio.sleep(.1)

        await self.logout_user(user_id= Cindy.user_id)
        await asyncio.sleep(.1)
        listeners.remove(Cindy.user_id)
        listener_names.remove(Cindy.name)
        print(listeners)
        await self.logout_user(user_id= Bob.user_id)
        await asyncio.sleep(.1)
        listeners.remove(Bob.user_id)
        listener_names.remove(Bob.name)
        print(listeners)        


if __name__  == '__main__':
    async def main():
        import argparse    
        from dotenv import dotenv_values
        
        config = dotenv_values('./.env')

        parser = argparse.ArgumentParser()
        parser.add_argument("-tc", "--test_connection", action= 'store_true', help="Test the connection to the database")
        parser.add_argument("-lt", "--list_tables",  action='store_true', help="List all tables")
        parser.add_argument('-ct', '--create_tables', action='store_true', help="Create the tables in the database")
        parser.add_argument('-cht', '--check_tables', action='store_true', help="Check the tables in the database")
        parser.add_argument('-dt', '--drop_table', action='store_true', help="Drop(delete) the tables in the database")
        parser.add_argument('-pt', '--populate_tables', action='store_true', help="simulate login, logout, messages")
        parser.add_argument('-dh', '--display_history',action='store_true', help='Display message history')
        parser.add_argument('--user_id', type=int, help='ID of the member to display the message history for')# add a subarguemnt --user_id --displaty_history

        sql_object = SQL_Interface_Test(config)
        await sql_object.create_tables()
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
        #elif args.display_history:
        #    await sql_object.display_history()

        #await sql_object.create_tables()
        #if not await sql_object.check_tables():
        #    sql_object.create_tables()

        #await sql_object.list_tables()
        #await sql_object.drop_tables()
        await sql_object.populate_tables()
        #await sql_object.display_history()
        #print(await sql_object.get_message_history(user_id=1223476936219824128))

    asyncio.run(main())
