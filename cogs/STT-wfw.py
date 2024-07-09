'''
Handles STT via wyoming faster whisper (part of the home assistant / rhasspy project).
Yes, the wyomining protocol is not well documented but it works.

Events Dispatched - 

    STT_event - transcibed text to be communicated to the llm 
    data passed

        discord_message

Event listeners -

    on_speaker_event - audio even from the speaker to be transcribed.
    data expected 

        dicord_message
        audio_data: array.array,

'''
import array, logging

#import discord
from discord.ext import commands
from discord.opus import Decoder as DiscOpus

import wyoming.mic as wyMic
import wyoming.asr as wyAsr
import wyoming.audio as wyAudio
import wyoming.client as wyClient

from utils.datatypes import Discord_Message

logger = logging.getLogger(__name__)

class STT_Wyoming_Faster_Whisper(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.wfw_host:str = bot.config['STT_WFW_host']
        self.wfw_port:int = bot.config['STT_WFW_port']
        self.payload_size:int = 1000
        self.rate: int = DiscOpus.SAMPLING_RATE
        self.width: int = DiscOpus.SAMPLE_SIZE
        self.channels: int = DiscOpus.CHANNELS

    async def wfw_transcribe(self, 
            message: Discord_Message,
            audio_data: array.array,
            ):

        timestamp: int = 0
        my_audio_chunks = []
        start = 0
        # wyoming protocol data list (home assistant voice). messaging in the format
        while len(audio_data) > start:
            end = start +  self.payload_size
            audio_segment = audio_data[start:end]
            my_audio_chunks.append(wyAudio.AudioChunk(
                rate = self.rate,
                width = self.width,
                channels= self.channels,
                audio=audio_segment.tobytes(),
                timestamp=timestamp            
                ))
            timestamp += my_audio_chunks[-1].timestamp + int(
                len(my_audio_chunks[-1].audio) / (self.rate * self.width * self.rate)  * 1000)
            start = end

        #wyoming tranmission start
        my_client = wyClient.AsyncTcpClient(host=self.wfw_host, 
                                            port=self.wfw_port)
        await my_client.connect()
        await my_client.write_event(wyAsr.Transcribe().event())
        await my_client.write_event(wyAudio.AudioStart(
            rate=self.rate, 
            width=self.width, 
            channels=self.channels).event())        
        for item in my_audio_chunks:
            await my_client.write_event(item.event())
        await my_client.write_event(wyAudio.AudioStop().event())        
        response = await my_client.read_event()
        
        message.text = response.data['text']
        logger.info(f'{message.member} said {response.data["text"]}')

        self.bot.dispatch('STT_event', 
                message = message)
        #        text=response.data['text'], 
        #        member=member_name, 
        #        ssrc=member_ssrc,
        #        member_id=member_id)

    @commands.Cog.listener('on_speaker_event')
    async def on_speaker_event(self,
            message: Discord_Message,
            audio_data: array.array,
        ):
        logger.info(f'received on_speaker_event')
        await self.wfw_transcribe(message, audio_data)

    async def cleanup(self):
        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(STT_Wyoming_Faster_Whisper(bot))

