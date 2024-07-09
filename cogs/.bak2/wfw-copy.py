
import asyncio, time, array, time #, loggging
import logging  as logger

from dotenv import dotenv_values
from collections import defaultdict
from typing import TYPE_CHECKING, TypedDict, Union, Optional, Awaitable, TypeVar
from concurrent.futures import Future as CFuture

import discord
from discord.ext import commands, voice_recv, tasks
from discord.ext.voice_recv import AudioSink

import wyoming.mic as wyMic
import wyoming.asr as wyAsr
import wyoming.audio as wyAudio
import wyoming.client as wyClient

#discord.utils.setup_logging(root=False)
logging = logger.getLogger(__name__)

T = TypeVar('T')

MemberOrUser = Union[discord.Member, discord.User]

class StreamData(TypedDict):
    buffer: array.array #[int]
    last_time: time
    start_time: time = None
    ssrc: int
    member: str
    member_id: int
    iterrupt_sent: bool = False

class Wyoming_Faster_Whisper_Sink(voice_recv.AudioSink):
    def __init__(self,
                host: str,
                port: int,
                bot: commands.bot,
                text_channel_send = None,
                payload: int = 1000,
                min_audio_len: int = 500,
                end_speaking_delay: int = 200,
                interrupt_time: float = .1
                ):
        super().__init__()
        self.host: str = host
        self.port: int = port
        self.bot: commands.Bot = bot
        self.text_channel_send: discord.TextChannel.send = text_channel_send
        self.channels = discord.opus.Decoder.CHANNELS
        self.width = discord.opus.Decoder.SAMPLE_SIZE
        self.rate = discord.opus.Decoder.SAMPLING_RATE
        self.payload_size: int = payload
        self.min_audio_length: int = min_audio_len # in msec
        self.end_speaking_delay: int = end_speaking_delay # in msec
        self.ignore_silence_packets: bool = True
        self.interrupt_time:float = interrupt_time
        self.AudioBuffer: defaultdict[int, StreamData] = defaultdict(
            lambda: StreamData(buffer=array.array('B'), last_time=None, member=None, ssrc=None, member_id=None)
            )
        self.monitor.start()

    @tasks.loop(seconds=0.1)    
    async def monitor(self):
        logging.debug('monitor')
        #todo min speaker time
        min_buffer_length = int(self.width * self.channels * self.min_audio_length * self.rate / 1000)
        if len(self.AudioBuffer) == 0:
            logging.debug('wfwInfo Audio Buffer empty')
            return            
        current_time = time.time()
        for key in self.AudioBuffer.keys():
            sdata = self.AudioBuffer[key]
            if sdata['last_time'] == None:
                continue
            time_diff = current_time - sdata['last_time']
            logging.debug(f'wfw monior time diff {time_diff}')
            if time_diff > (self.end_speaking_delay / 1000):
                logging.debug(f'min size {min_buffer_length} buffer size {len(sdata["buffer"])}')
                if len(sdata['buffer']) < min_buffer_length:
                    logging.debug(f'buffer {len(sdata["buffer"])} expected {min_buffer_length}')
                else:
                    await self.wfw_transcribe(sdata)
                sdata['last_time'] = None

    @monitor.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @monitor.after_loop
    async def after(self):
        logging.info('wfwSink monitor stopped')

    def _drop(self, user_id: int) -> None:
        if user_id in self.AudioBuffer:
            del self.AudioBuffer[user_id]

    @monitor
    def _await(self, coro: Awaitable[T]) -> CFuture[T]:
        assert self.client is not None
        logging.info(f'wfwSink _await')
        return asyncio.run_coroutine_threadsafe(coro)#, self.client.loop)

    def wants_opus(self) -> bool:
        logging.debug(f'wfwSink wants_opus')
        return False

    def write(self, user: Optional[MemberOrUser], data: voice_recv.VoiceData) -> None:
        #todo min speaking interrupt
         
        if self.ignore_silence_packets and isinstance(data.packet, voice_recv.SilencePacket):
            logging.info(f'wfwSink write - self.ignore_silence and isinstance')
            return

        if user is None:
            logging.info(f'wfwSink write - user none')
            return

        sdata = self.AudioBuffer[user.id]

        if sdata['last_time'] == None:
            del sdata['buffer'][:]
            sdata['buffer'] = array.array('B')
            sdata['member'] = data.source.name
            sdata['ssrc'] = data.source.id
            sdata['member_id'] = user.id
            sdata['iterrupt_sent'] = False
            sdata['start_time'] = time.time()

        sdata['buffer'].extend(data.pcm)
        sdata['last_time'] = time.time()
        
        # send an event to stop bot voice playback when someone speaks in
        # the channel
        #logging.info(f'check for interrrupt {sdata["iterrupt_sent"]}')
        if sdata['iterrupt_sent'] == False:
            #logging.info(f"dif for cur time and start time {time.time() - sdata['start_time']}")
            if (time.time() - sdata['start_time']) > self.interrupt_time:
                self.bot.dispatch('speaking_interrupt')
                logging.info(f'speaking_interrupt sent')
                sdata['iterrupt_sent'] = True

        
        logging.debug(f'wfwSink write {user}')

    @AudioSink.listener()
    def on_voice_member_disconnect(self, member: discord.Member, ssrc: Optional[int]) -> None:
        self._drop(member.id)
        logging.info(f'wfwSink on_voice_member_disconenct')

    def cleanup(self, *args, **kwargs) -> None:
        logging.info(f'wfwSink cleanup {args} {kwargs}')
        if len(kwargs.keys()) > 0:
            if kwargs['local_call'] == True:
                for user_id in tuple(self.AudioBuffer.keys()):
                    self._drop(user_id)
        #for user_id in tuple(self.AudioBuffer.keys()):
        #    self._drop(user_id)

    def _drop(self, user_id: int) -> None:
        data = self.AudioBuffer.pop(user_id)

        buffer = data.get('buffer')
        if buffer:
            # arrays don't have a clear function
            del buffer[:]
            
        logging.info(f'wfwSink _drop')

    async def wfw_transcribe(self, audio_data: StreamData):
        timestamp: int = 0
        my_audio_chunks = []
        start = 0
        while len(audio_data['buffer']) > start:
            end = start +  self.payload_size
            audio_segment = audio_data['buffer'][start:end]
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
        my_client = wyClient.AsyncTcpClient(host=self.host, port=self.port)
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
        output = f'{audio_data["member"]} said {response.data["text"]}'
        logging.info(output)
        await self.text_channel_send(output)
        self.bot.dispatch('my_STT', 
                text=response.data['text'], 
                member=audio_data['member'], 
                ssrc=audio_data['ssrc'],
                member_id=audio_data['member_id'])
        return response.data['text']

class WFW_Speech_Recog(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.wfw_host = None
        self.wfw_port = None
        self.voice_client: discord.VoiceClient = None
        self.voice_channel: discord.VoiceChannel = None
        self.voice_channel_title = None
        self.text_channel_title = None
        self.text_channel: discord.TextChannel = None
        self.wfw_reco_sink: Wyoming_Faster_Whisper_Sink = None
        
    async def cog_load(self) -> None:
        config  = dotenv_values('.env')
        self.wfw_host = config['wfw_host']
        self.wfw_port = config['wfw_port']
        self.voice_channel_title = config['voice_channel']
        self.text_channel_title = config['text_channel']
        return await super().cog_load()

    @commands.Cog.listener('on_ready')
    async def on_ready(self):
        await self._connect_text()
        await self._connect_voice()
    
    async def _connect_voice(self):
        self.voice_channel = discord.utils.get(self.bot.get_all_channels(), name=self.voice_channel_title)
        
        if self.voice_channel is None:
            logging.info("Voice channel not found.")
            return

        self.voice_client = await self.voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        self.wfw_reco_sink = Wyoming_Faster_Whisper_Sink(
            host=self.wfw_host, 
            port= self.wfw_port,
            bot= self.bot,
            text_channel_send=self.text_channel.send)
        logging.info(f"Connected to {self.voice_channel_title}")
        self.bot.dispatch('my_Voice_Client_Connected', 
                          client = self.voice_client, 
                          channel = self.voice_channel) 
        self.voice_client.listen(self.wfw_reco_sink)

    
    @commands.command()
    async def connect_voice(self, ctx: commands.Context):
        await self._connect_voice()
    
    async def _connect_text(self):
        if self.text_channel == None:
            self.text_channel = discord.utils.get(self.bot.get_all_channels(), 
                name=self.text_channel_title, 
                type=discord.ChannelType.text)
            #await self.text_channel.send("Hello, world!")
        else:
            logging.info(f"Text channel '{self.text_channel_title}' not found.")
            return

    @commands.command()
    async def connect_text(self, ctx: commands.Context):
        await self._connect_text()

    @commands.command()
    async def my_stop(self, ctx):
        logging.info("Stopping...")
        if self.wfw_reco_sink != None:
            self.wfw_reco_sink.cleanup(local_call=True)
            self.wfw_reco_sink = None
        if self.voice_client != None:
            await self.voice_client.disconnect()
            self.voice_client = None

    @commands.command()
    async def die(self, ctx):
        await self.my_stop(ctx)
        await ctx.bot.close()
    
'''
    @commands.Cog bot.event
    async def on_my_TTS(**kwargs):
        print(f'{kwargs["member"]} said {kwargs["text"]}')

    @bot.event
    async def on_voice_member_speaking_state(
            member: discord.Member, 
            ssrc: int, 
            state: int):
        print(f'on_voice_member_speaking_state: {member} ssrc:{ssrc} state:{state}')
    
    @bot.event
    async def on_voice_member_disconnect(
            member: discord.Member, 
            ssrc: int | None):
        logging.info(f'on_voice_member_disconnect: {member} ssrc:{ssrc}')
'''

async def setup(bot: commands.Bot):
    await bot.add_cog(WFW_Speech_Recog(bot))

