'''
Interface for connecting to an external server to communicate with the LLM. 
The server response in sentances so the speech can initiate as fast as possible

Events Dispatched - 

    TTS_event - communitation to the TTS module (piper)
                data - text to be sent to the TTS module
                (future) - voice 
                (future) - piper server (so multiple voice modles can be used)

Event listeners -

    on_STT_event - transcibed text to be communicated to the llm (botman)
                text
                member
                ssrc
                member_id

'''

import asyncio, json, logging

from discord.ext import commands

logger = logging.getLogger(__name__)

class Bot_Manager(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot:commands.Bot = bot
        self.host:str = bot.config['botman_host']
        self.port:int = bot.config['botman_port']

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
                logger.info(f'TTS_event  {response.decode()}')
                self.bot.dispatch('TTS_event', data=response.decode())
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
                logger.info(f'TTS_event  {response}')
                self.bot.dispatch('TTS_event', data=response)
        finally:
            writer.close()
    
    @commands.Cog.listener('on_STT_event')
    async def on_STT_event(self, **kwargs):
        logger.info(f'STT event received {kwargs}')
        await self.send_data_to_server(kwargs)
        
async def setup(bot: commands.Bot):
    await bot.add_cog(Bot_Manager(bot))