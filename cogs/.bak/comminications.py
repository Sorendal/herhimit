'''
communications cog for the discord bot that handles voice and text communication

configuation for the audio is

    minimum audio length(int in ms) - the smallest amount of audio you want to process

    end speaking delay(int in ms) - the amount of time to wait after a user stops 
        speaking before processing audio

    interrupt time(int in ms, converted to float in seconds during init) - the 
        amount of time before the an event is sent to allow other processes to 
        react (i.e. if an LLM response is speaking and someone starts talking 
        over it). 

    monitor frequency(float in seconds) hard coded .1 seconds (dont think python 
        decorators can be used with a varible) - how often the audio loop checks
        for new audio and sends an event if there is no new audio determined by
        the end speaking delay 

dispatched events:

    speaker_event - when a user stops speaking and after end_speaking_delay has 
        passed. Data passed is
    
        audio_data - the audio data in a byte array
        member - the discord user displayed name
        member_id - the discored user ID
        ssrc - probably the same ID as the member, 

    speaking_interrupt - when someone starts talking in the channel

    voice_client_connected 

    voice_client_disconnected

    text_client_connected

'''
import asyncio, time, array, time, logging, io

from dataclasses import dataclass
from collections import defaultdict, deque
from typing import TYPE_CHECKING, TypedDict, Union, Optional, Awaitable, TypeVar
from concurrent.futures import Future as CFuture

import discord
from discord.ext import commands, voice_recv, tasks
from discord.ext.voice_recv import AudioSink

#discord.utils.setup_logger(root=False)
logger = logging.getLogger(__name__)

T = TypeVar('T')

MemberOrUser = Union[discord.Member, discord.User]

class StreamData(TypedDict):
    buffer: array.array = array.array('B')#[int]
    last_time: time = None
    start_time: time = None
    ssrc: int = None
    member: str = None
    member_id: int = None
    iterrupt_sent: bool = False

class Speech_To_Text_Sink(voice_recv.AudioSink):
    def __init__(self,
                bot: commands.Bot, 
                play_queue:deque,
                min_audio_len: int = 500,
                end_speaking_delay: int = 200,
                interrupt_time: int = 100,
                ):
        super().__init__()
        self.bot: commands.Bot = bot
        self.channels = discord.opus.Decoder.CHANNELS
        self.width = discord.opus.Decoder.SAMPLE_SIZE
        self.rate = discord.opus.Decoder.SAMPLING_RATE
        self.min_audio_length: int = min_audio_len # in msec
        self.end_speaking_delay: int = end_speaking_delay # in msec
        self.ignore_silence_packets: bool = True
        self.interrupt_time:float = interrupt_time / 1000
        self.audio_buffer_dict: defaultdict[int, StreamData] = defaultdict(
            lambda: StreamData(buffer=array.array('b'), last_time=None, member=None, ssrc=None, member_id=None)
            )
        self.min_buffer_length = int(self.width * self.channels * self.min_audio_length * self.rate / 1000)
        self.play_queue = play_queue
        self.monitor.start()

    @tasks.loop(seconds=0.1)    
    async def monitor(self):
        #logger.debug('monitor')
        #todo min speaker time

        # check play queue
        if len(self.play_queue) > 0:
            if not self.bot.voice_clients[0].is_playing():
                try:
                    audio_source = discord.PCMAudio(self.play_queue.popleft())
                    self.bot.voice_clients[0].play(audio_source, 
                            after=lambda e: print(f'Error:  {e}') if e else None)
                except ValueError as e:
                    logger.info(f'Error: {e}')
            
        if len(self.audio_buffer_dict) == 0:
            logger.debug('STT Audio Buffer empty')
            return            
        current_time = time.time()
        for key in self.audio_buffer_dict.keys():
            sdata = self.audio_buffer_dict[key]
            if sdata['last_time'] == None:
                continue
            time_diff = current_time - sdata['last_time']
            #logger.debug(f'stt monior time diff {time_diff}')
            if time_diff > (self.end_speaking_delay / 1000):
                #logger.debug(f'min size {self.min_buffer_length} buffer size {len(sdata["buffer"])}')
                if len(sdata['buffer']) < self.min_buffer_length:
                    logger.debug(f'buffer {len(sdata["buffer"])} expected {self.min_buffer_length}')
                else:
                    self.bot.dispatch(f'speaker_event', 
                        audio_data = sdata['buffer'],
                        member = sdata['member'],
                        member_id = sdata['member_id'],
                        ssrc=sdata['ssrc'],
                    )
                    logger.info(f'speaker_event dispatched')
                sdata['last_time'] = None

    @monitor.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @monitor.after_loop
    async def after(self):
        logger.info('stt monitor stopped')

    def _drop(self, user_id: int) -> None:
        if user_id in self.audio_buffer_dict:
            del self.audio_buffer_dict[user_id]

    @monitor
    def _await(self, coro: Awaitable[T]) -> CFuture[T]:
        assert self.client is not None
        logger.info(f'stt sink _await')
        return asyncio.run_coroutine_threadsafe(coro)#, self.client.loop)

    def wants_opus(self) -> bool:
        logger.debug(f'stt sink wants_opus')
        return False

    def write(self, user: Optional[MemberOrUser], data: voice_recv.VoiceData) -> None:
        #todo min speaking interrupt
         
        if self.ignore_silence_packets and isinstance(data.packet, voice_recv.SilencePacket):
            logger.info(f'stt sink write - self.ignore_silence and isinstance')
            return

        if user is None:
            logger.info(f'stt sink write - user none')
            return

        sdata = self.audio_buffer_dict[user.id]

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
        #logger.info(f'check for interrrupt {sdata["iterrupt_sent"]}')
        if sdata['iterrupt_sent'] == False:
            #logger.info(f"dif for cur time and start time {time.time() - sdata['start_time']}")
            if (time.time() - sdata['start_time']) > self.interrupt_time:
                self.bot.dispatch('speaking_interrupt', interrupted_sentances=len(self.play_queue))
                logger.info(f'speaking_interrupt sent, {len(self.play_queue)} sentances interrupred')
                if self.voice_client.is_playing():
                    self.voice_client.pause()
                    self.play_queue.clear()
                sdata['iterrupt_sent'] = True

        logger.debug(f'stt sink write {user}')

    @AudioSink.listener()
    def on_voice_member_disconnect(self, member: discord.Member, ssrc: Optional[int]) -> None:
        self._drop(member.id)
        logger.info(f'stt sink on_voice_member_disconenct')

    #@commands.Cog.listener('on_communications_play_queue_request')
    #async def on_communications_play_queue_request(self):
    #,,    #self.bot.dispatch('communications_play_queue', self.play_queue)
    #    logger.info('communications play queue sent')

    def cleanup(self, *args, **kwargs) -> None:
        logger.info(f'stt sink cleanup {args} {kwargs}')
        if len(kwargs.keys()) > 0:
            for user_id in tuple(self.audio_buffer_dict.keys()):
                self._drop(user_id)

    def _drop(self, user_id: int) -> None:
        data = self.audio_buffer_dict.pop(user_id)

        buffer = data.get('buffer')
        if buffer:
            # arrays don't have a clear function
            del buffer[:]
            
        logger.info(f'stt sink _drop')

class Communications_Cog(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.voice_client: discord.VoiceClient = None
        self.voice_channel: discord.VoiceChannel = None
        self.voice_channel_title = bot.config['voice_channel']
        self.text_channel_title = bot.config['text_channel']
        self.text_channel: discord.TextChannel = None
        self.stt_sink: Speech_To_Text_Sink = None
        self.play_queue = deque()
        
    async def cog_load(self) -> None:
        return await super().cog_load()

    @commands.Cog.listener('on_ready')
    async def on_ready(self):
        await self._connect_text()
        await self._connect_voice()

    @commands.Cog.listener('on_speaker_event')
    async def on_speaker_event(self, **kwargs) -> None:
        members = {} 
        for member in self.voice_channel.members:
            if member.global_name is not None:
                members.update({member.id: [member.global_name, member.bot]})
            else:
                members.update({member.id: [member.name, member.bot]})
        
        self.bot.dispatch('speaker_event_listeners', members)

    async def _connect_voice(self):
        self.voice_channel = discord.utils.get(self.bot.get_all_channels(), name=self.voice_channel_title)
        
        if self.voice_channel is None:
            logger.info("Voice channel not found.")
            return

        self.voice_client = await self.voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        self.stt_sink = Speech_To_Text_Sink(bot=self.bot, play_queue=self.play_queue)
        logger.info(f"Connected to {self.voice_channel_title}")
        self.bot.dispatch('voice_client_connected', channel=self.voice_channel_title) 
        self.voice_client.listen(self.stt_sink)

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
            logger.info(f"Text channel '{self.text_channel_title}' not found.")
            self.bot.dispatch('text_client_connected')
            return

    @commands.command()
    async def connect_text(self, ctx: commands.Context):
        await self._connect_text()

    @commands.command()
    async def stop(self, ctx):
        logger.info("Stopping...")
        if self.stt_sink != None:
            self.stt_sink.cleanup()
            self.stt_sink = None
        if self.voice_client != None:
            await self.voice_client.disconnect()
            self.voice_client = None
            self.bot.dispatch('voice_client_disconnected')

    @commands.Cog.listener('on_speaking_interrupt')
    async def on_speaking_interrupt(self, **kwargs):
        pass #probably legacy

    @commands.Cog.listener('on_TTS_play')
    async def on_TTS_play(self, audio:io.BytesIO):
        logger.info('on TTS play received')
        self.play_queue.append(audio)

async def setup(bot: commands.Bot):
    await bot.add_cog(Communications_Cog(bot))