'''
Handles STT via wyoming faster whisper (part of the home assistant / rhasspy project).
Yes, the wyomining protocol is not well documented but it works.

Audio in is process through the deque audio_in containing Audio_Message(audio data and Discord_Message)
The text is added to the Discord_Message and sent to the deque LLM for further processing.
    if the last message in the LLM queue has the same member_id as the current message, it will be merged with that message.
'''
import array, logging, time

from discord.ext import commands, tasks
from discord.opus import Decoder as DiscOpus
from typing import Union 

import wyoming.mic as wyMic
import wyoming.asr as wyAsr
import wyoming.audio as wyAudio
import wyoming.client as wyClient

from utils.datatypes import Discord_Message, Commands_Bot, Audio_Message, Halluicanation_Sentences

logger = logging.getLogger(__name__)

class WFW():
    def __init__(self, host:str, port:int, input_rate: int, input_channels: int, input_width):
        self.host = host
        self.port = port
        self.rate = input_rate
        self.channels = input_channels
        self.width = input_width
        self.payload_size = 1000

    async def wfw_transcribe(self, audio_data: array.array) -> str:
        timestamp: int = 0
        my_audio_chunks = []
        start = 0

        # wyoming protocol data list (home assistant voice)
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
        my_client = wyClient.AsyncTcpClient(host=self.host, 
                                            port=self.port)
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

class STT_wfw(commands.Cog, WFW):
    def __init__(self, bot: Commands_Bot):
        self.bot: Commands_Bot = bot
        WFW.__init__(self=self, 
                host=bot.___custom.config['STT_WFW_host'], 
                port=bot.___custom.config['STT_WFW_port'], 
                input_rate=DiscOpus.SAMPLING_RATE, 
                input_channels=DiscOpus.CHANNELS, 
                input_width=DiscOpus.SAMPLE_SIZE)

        self.queues = self.bot.___custom.queues
        self.user_speaking: set[int] = self.bot.___custom.user_speaking
        self.user_last_message: dict[int, float] = self.bot.___custom.user_last_message
        self.time_between_messages: float = self.bot.___custom.config['behavior_time_between_messages']

        self.STT_monitor.start()

    def halluicanation_check(self, text: str) -> Union[str, None]:
        '''
          minimal verification that it wasnt a hallucination: returns the string if passed, None if not
          removes trailing punctuation and lowercases the text
        '''
        hc = True
        text = text.strip()
        hc_text = text[:-1].lower()
        if hc_text in Halluicanation_Sentences:
            if hc:
                logger.info(f'Hallucination - begin - {hc_text}')
            return None
        elif any(hc_text.startswith(item) for item in Halluicanation_Sentences):
            if any(hc_text.endswith(item) for item in Halluicanation_Sentences):
                if hc:
                    logger.info(f'Hallucination - begin and end - {hc_text}')
                return None
        else:
            return text

    @tasks.loop(seconds=0.1)
    async def STT_monitor(self):
        # process audio by looping through the first item in the queue and put results in the llm_queue
        if self.queues.audio_in:
            incoming_audio = self.queues.audio_in.popleft()
            message = incoming_audio.message
            response = await self.wfw_transcribe(incoming_audio.audio_data)
            message.text = self.halluicanation_check(response)
            if not message.text:
                # hallucination detected, discard the message and return
                return
            message.timestamp_STT = time.perf_counter()

        #check to see if the last message in the LLM queue is by the same member and update the data
            if self.queues.llm:
                if (self.queues.llm[-1].member_id == message.member_id) and ((self.queues.llm[-1].timestamp_Audio_End - message.timestamp_Audio_End) < self.time_between_messages):
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
                
    async def cleanup(self):
        if self.STT_monitor.is_running():
            self.STT_monitor.stop()

async def setup(bot: commands.Bot):
    await bot.add_cog(STT_wfw(bot))