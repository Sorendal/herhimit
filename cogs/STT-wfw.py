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
import array, logging, time
from dataclasses import dataclass


#import discord
from discord.ext import commands, tasks
from discord.opus import Decoder as DiscOpus

import wyoming.mic as wyMic
import wyoming.asr as wyAsr
import wyoming.audio as wyAudio
import wyoming.client as wyClient

from utils.datatypes import Discord_Message, Commands_Bot, Audio_Message, Halluicanation_Sentences

logger = logging.getLogger(__name__)

class STT_wfw(commands.Cog):
    def __init__(self, bot):
        self.bot: Commands_Bot = bot
        self.wfw_host:str = self.bot.___custom.config['STT_WFW_host']
        self.wfw_port:int = self.bot.___custom.config['STT_WFW_port']
        self.payload_size:int = 1000
        self.rate: int = DiscOpus.SAMPLING_RATE
        self.width: int = DiscOpus.SAMPLE_SIZE
        self.channels: int = DiscOpus.CHANNELS
        #self.requests: list[STT_request] = []
        #self.currently_processing: bool = False
        #self.min_process_time: float = None
        #self.user_message_prefix: dict[int, Discord_Message] = {}

        self.queues = self.bot.___custom.queues
        self.user_speaking: set[int] = self.bot.___custom.user_speaking
        self.user_last_message: dict[int, float] = self.bot.___custom.user_last_message

        self.user_idle_time: float = float(60)
        self.new_mess_time_diff: float = float(1)

    async def wfw_transcribe(self, audio_data: array.array) -> str:

        if not self.STT_monitor.is_running():
            self.STT_monitor.start()

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
        
        return response.data['text']
    
    def halluicanation_check(self, text: str) -> str:
        '''
          minimal verification that it wasnt a hallucination: returns the string if passed, '' if not
        '''
        if text in Halluicanation_Sentences:
            return ''
        elif any(text.startswith(item) for item in Halluicanation_Sentences):
            if any(text.endswith(item) for item in Halluicanation_Sentences):
                return ''
        else:
             return text

    
    @tasks.loop(seconds=0.1)
    async def STT_monitor(self):
        # process audio by looping through the first item in the queue and put results in the llm_queue
        if self.queues.audio_in:
            incoming_audio = self.queues.audio_in.popleft()
            message = incoming_audio.message
            #message = self.queues.audio_in[0].message
            #while (len(self.queues.audio_in[0].audio_data)) != 0:
                #response = await self.wfw_transcribe(self.queues.audio_in[0].audio_data[0])
            response = await self.wfw_transcribe(incoming_audio.audio_data)
                #self.queues.audio_in[0].audio_data.pop(0)
                #incoming_audio.message.text += self.bot.___custom.halluicanation_check(text=response)
            message.text = self.halluicanation_check(response)
            #self.queues.audio_in.pop(0)
            message.timestamp_STT = time.perf_counter()

        #check to see if the last message in the LLM queue is by the same member and update the data
            if self.queues.llm:
                if (self.queues.llm[-1].member_id == message.member_id) and ((time.perf_counter() - message.timestamp_Audio_End) < 5):
                    current_message = self.queues.llm[-1]
                    current_message.text += ' ' + message.text
                    current_message.timestamp_Audio_End = message.timestamp_Audio_End
                    current_message.listener_names.union(message.listener_names)
                    current_message.listeners.union(message.listeners)
                    logger.info(f'STT - Update LLM message {(message.timestamp_STT - message.timestamp_Audio_End):.3f} {message.member} {message.text}')
            else:
                # new messages are added to the DB and LLM queues. 
                message.message_id = self.bot.___custom.get_message_store_key()
                self.queues.llm.append(message)
                self.queues.db_message.append(message)
                self.queues.text_message.append(message)
                logger.info(f'STT - New LLM message {(message.timestamp_STT - message.timestamp_Audio_End):.3f} {message.member} {message.text}')
                

    @STT_monitor.after_loop
    async def botman_monitor_after_loop(self):
        logger.debug(f'monitor stopping')
        pass

    @STT_monitor.before_loop
    async def botman_monitor_before_loop(self):
        logger.debug('monitor starting')
        pass

    @commands.Cog.listener('on_ready')
    async def on_ready(self):
        if not self.STT_monitor.is_running():
            self.STT_monitor.start()

    async def cleanup(self):
        if self.STT_monitor.is_running():
            self.STT_monitor.stop()

async def setup(bot: commands.Bot):
    await bot.add_cog(STT_wfw(bot))

