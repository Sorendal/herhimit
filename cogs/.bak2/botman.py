import asyncio, json, logging
from dotenv import dotenv_values

from discord.ext import commands

class Bot_Manager(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot:commands.Bot = bot
        config = dotenv_values('.env')
        self.host = config['botman_host']
        self.port = config['botman_port']
        if 'botman_model' in config.keys():
            self.model = config['botman_model']

async def send_data_to_server(self, data) -> None:
    reader, writer = await asyncio.open_connection(self.host, self.port)
    request_json = json.dumps(data)
    writer.write(request_json.encode())
    writer.write_eof()
    await writer.drain()

    try:
        while True:
            response = await reader.readline()
            if not response:
                break
            logging.info(f'on_my_STT  {response.decode()}')
            self.bot.dispatch('my_STT', data=response.decode())
    finally:
        writer.close()
        await writer.wait_closed()

    async def send_data_to_server_bak(self, data) -> None:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        request_json = json.dumps(data)
        writer.write(request_json.encode())
        writer.write_eof()
        await writer.drain()
        writer.close()

        try:
            for response in await reader.readline():
                logging.info(f'on_my_STT  {response}')
                self.bot.dispatch('my_STT', data=response)
        finally:
            writer.close()
    
    @commands.Cog.listener('on_my_STT')
    async def on_my_STT(self, **kwargs):
        logging.info(f'on_my_STT received {kwargs}')
        await self.send_data_to_server(kwargs)
        
async def setup(bot: commands.Bot):
    await bot.add_cog(Bot_Manager(bot))