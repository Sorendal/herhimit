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

from utils.datatypes import Discord_Message

logger = logging.getLogger(__name__)

@dataclass
class STT_request:
    message:Discord_Message
    audio_list: list[array.array]

class STT_wfw(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.wfw_host:str = bot.config['STT_WFW_host']
        self.wfw_port:int = bot.config['STT_WFW_port']
        self.payload_size:int = 1000
        self.rate: int = DiscOpus.SAMPLING_RATE
        self.width: int = DiscOpus.SAMPLE_SIZE
        self.channels: int = DiscOpus.CHANNELS
        self.requests: list[STT_request] = []
        #self.currently_processing: bool = False
        self.min_process_time: float = None
        self.user_message_prefix: dict[int, Discord_Message] = {}

    async def wfw_transcribe(self, audio_data: list[array.array]) -> str:

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
    
    @tasks.loop(seconds=0.1)
    async def TTS_monitor(self):
        if len(self.requests) != 0:
            tts_request = self.requests[0]
            while len(tts_request.audio_list) != 0:
                response = await self.wfw_transcribe(tts_request.audio_list.pop(0))
                tts_request.message.text += ' ' + response
            tts_request.message.timestamp_STT = time.perf_counter()
            tts_request.message.text = tts_request.message.text.strip()
            if tts_request.message.member_id in self.user_message_prefix:
                prefix_message = self.user_message_prefix.pop(tts_request.message.member_id)
                tts_request.message.text = prefix_message.text + ' ' + tts_request.message.text
                tts_request.message.timestamp_Audio_Start = prefix_message.timestamp_Audio_Start
            self.bot.dispatch('STT_event', message = tts_request.message)

            # Adjust the timing for when a message is to be considered old and delay LLM generation
            if self.min_process_time == None:
                self.min_process_time = tts_request.message.timestamp_STT - tts_request.message.timestamp_Audio_End
            elif (tts_request.message.timestamp_STT - tts_request.message.timestamp_Audio_End) < self.min_process_time:
                self.min_process_time = tts_request.message.timestamp_STT - tts_request.message.timestamp_Audio_End

            # need to wait to remove the request until the transcription is compelete as
            # more audio data may be incoming
            self.requests.pop(0)

        if len(self.requests) == 0:
            self.TTS_monitor.stop()

    @TTS_monitor.after_loop
    async def botman_monitor_after_loop(self):
        logger.debug(f'monitor stopping')
        pass

    @TTS_monitor.before_loop
    async def botman_monitor_before_loop(self):
        logger.debug('monitor starting')
        pass

    @commands.Cog.listener('on_speaker_event_prefix_text')
    async def on_speaker_event_prefix_text(self, message: Discord_Message):
        logger.info(f'Prefix Text {message.member}')
        self.user_message_prefix[message.member_id] = message
        pass

    @commands.Cog.listener('on_speaker_event')
    async def on_speaker_event(self, message: Discord_Message, audio_data: array.array):
        logger.info(f'received on_speaker_event')

        # if list is empty, add request to the list and start monitor
        if len(self.requests) == 0:
            self.requests.append(STT_request(message=message, audio_list=[audio_data]))
            logger.info(f'new message')
            if self.TTS_monitor.is_running() is False:
                self.TTS_monitor.start()
        else:
            current_time = time.perf_counter()
            # check the list of requests to see if any match the speaker
            indx = len(self.requests)
            new_message_threshold = time.perf_counter() - self.min_process_time
            while indx > 0:
                indx += -1
                tts_request = self.requests[indx]
                if tts_request.message.member_id == message.member_id:
                    if tts_request.message.timestamp_Audio_End < new_message_threshold:
                        # this is a continuation of the message, append the audio_data and update the end
                        # time of the message
                        tts_request.audio_list.append(audio_data)
                        logger.info(f'continuatin message')
                        tts_request.message.timestamp_Audio_End = message.timestamp_Audio_End
                    else:
                        # this is a new message, insert it at the end of the requests
                        logger.info(f'new message by a user with one in the queue')
                        self.requests.append(STT_request(message=message, audio_list=[audio_data]))
                    return
            #assume that this is a new message and append to the list
            logger.info(f'new message from a user that is not in the queue')
            self.requests.append(STT_request(message=message, audio_list=[audio_data]))

    async def cleanup(self):
        if self.TTS_monitor.is_running():
            self.TTS_monitor.stop()
        del self.requests

async def setup(bot: commands.Bot):
    await bot.add_cog(STT_wfw(bot))

