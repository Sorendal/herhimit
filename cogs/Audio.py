'''
communications cog for the discord bot that handles voice and text communication
this is a modified version of 

https://github.com/imayhaveborkedit/discord-ext-voice-recv

please thank him for giving me the idea to make this. I modified his speaker 
recoginition sink to pass the speech recognition to another cog. Some of 
this code is stuff from him that I hesitate to alter as I did not dive
into the source.

Note: Limitation of Discord Voice API: it requires 48khz, 16bit 2 channel audio
to play with a min lengh of 20ms.

Monitor Process - process loop occurs every .1 seconds (can be configured)
    
    Record - This works by storing all audio data in a dict[user_id:audio_data]. 
        if the speaker has stopped speaking for .2 seconds(com_end_speaking_delay), it will check the audio lenght
            if less than .5 sec, discard (com_min_audio_len)
            else, dispatch a STT_event to be processed
        when the speaker has spoken for more than .1 seconds and audio is playin
            it allows the bot to be talked over (bot stops playing audio)
    
    Play - Audio TTS events are caught and put in a deque. The monitor checks the
        deque and starts playing the audio (discord.py does this via a seperate thread)
        If interruped, deque is counted and the number of sentences is dispatched as an event
        and the deque is cleared

Configuation expected in the .env config file
    com_voice_channel - str - the name of the voice channel to join

    com_min_audio_len(int in ms) - the smallest amount of audio you want to process

    com_end_speaking_delay(int in ms) - the amount of time to wait after a user stops 
        speaking before processing audio

    com_interrupt_time(int in ms), converted to float in seconds during init) - the 
        amount of time before the an event is sent to allow other processes to 
        react (i.e. if an LLM response is speaking and someone starts talking 
        over it). 

dispatched events:

    speaker_event - when a user stops speaking and after end_speaking_delay has 
        passed. Data passed is
            Discord_Message:  
            audio_data : array.array
    
    speaker_interrupt - when someone starts talking in the channel
        data passed is a Speaking_Interrupt object
            num_sentences: int
            member_id: int
            member_name: str

    speaker_interrupt_clear - message to notify the speaker has stopped talking. Data 
        passed
            member_id: int

    voice_client_connected - when the bot joins a voice channel
        data passed is:
            members - list of discord.Member objects in the channel
            voicechannel - discord.VoiceChannel object - may be cruft

    voice_client_disconnected

event listeners:

    on_ready: connects to the voice and text channels

    on_TTS_play: adds audio data to the play deque. Expects
        audio: io.BytesIO object

    on_voice_state_update: checks if a user has joined the voice channel
        and updates the members dict [member_id: StreamData]
    
    on_voice_member_disconnect - special voice-recv listener
        removes a member from the members dict

'''
import asyncio, time, array, time, logging, io

from dataclasses import dataclass
from collections import defaultdict
from typing import TYPE_CHECKING, TypedDict, Union, Optional, Awaitable, TypeVar
from concurrent.futures import Future as CFuture

import discord
from discord.ext import commands, voice_recv, tasks
from discord.ext.voice_recv import AudioSink

from utils.datatypes import Discord_Message, Speaking_Interrupt, Audio_Message, Commands_Bot

logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)

T = TypeVar('T')

MemberOrUser = Union[discord.Member, discord.User]

class StreamData(TypedDict):
    buffer: array.array = array.array('B')#[int]
    last_time: time = None
    ssrc: int = None
    member: str = None
    member_id: int = None
    #iterrupt_sent: bool = False
    last_sequence: int = None
    start_time: float = None

class Speech_To_Text_Sink(voice_recv.AudioSink):
    def __init__(self,
                bot: Commands_Bot, 
                play_queue: list,
                listeners: dict[int, str],
                min_audio_len: int = 500,
                end_speaking_delay: int = 200,
                interrupt_time: int = 100,
                ):
        super().__init__()
        self.bot: Commands_Bot = bot
        self.members: list = []
        self.channels = discord.opus.Decoder.CHANNELS
        self.width = discord.opus.Decoder.SAMPLE_SIZE
        self.rate = discord.opus.Decoder.SAMPLING_RATE
        self.min_audio_length: int = min_audio_len # in msec
        self.end_speaking_delay: int = end_speaking_delay # in msec
        self.interrupt_time:float = interrupt_time / 1000
        self.ignore_silence_packets: bool = True
        self.audio_buffer_dict: defaultdict[int, StreamData] = defaultdict(
            lambda: StreamData(buffer=array.array('b'), last_time=None, member=None, ssrc=None, member_id=None)
            )

        self.min_buffer_length = self.width * self.channels * self.min_audio_length * self.rate // 1000
        self.user_speaking:set[int] = self.bot.___custom.user_speaking
        self.user_last_message:dict[int, float] = self.bot.___custom.user_last_message

        self.listeners: dict[int, str] = self.bot.___custom.current_listeners #listeners
        self.audio_packet_length = self.rate * self.width * self.channels // 20
        #self.audio_buffer_padding: float = .25 #attempt to padd the audio to see if it impoves speech recognition
        self.queues = self.bot.___custom.queues
        self.monitor.start()


    @tasks.loop(seconds=0.1)    
    async def monitor(self):
        #Check if there is audio in the play queue and if so, play it
        if self.user_speaking and self.voice_client.is_playing():
            self.bot.dispatch('speaking_interrupt', speaking_interrupt = 
                    Speaking_Interrupt(num_sentences = (len(self.queues.audio_out) +1), 
                    members=[self.user_speaking], member_names=[self.listeners[key] for key in self.user_speaking]))
            self.voice_client.pause()
            self.queues.audio_out.clear()
            # did not have a line for the list

        #Check if there is audio in the play queue and if so, play it
        elif self.queues.audio_out:
            if not self.voice_client.is_playing():
                try:
                    audio_source = discord.PCMAudio(self.queues.audio_out.popleft())
                    self.voice_client.play(audio_source, 
                    #bot.voice_clients[0].play(audio_source, 
                            after=lambda e: print(f'Error:  {e}') if e else None)
                except ValueError as e:
                    logger.info(f'Error: {e}')
        
        #checking the audio buffer dict is empty 
        if not self.audio_buffer_dict:
            logger.debug('STT Audio Buffer empty')
                    
        current_time = time.perf_counter()
        for key in self.audio_buffer_dict.keys():
            sdata = self.audio_buffer_dict[key]
            if sdata['last_time'] == None:
                continue
            time_diff = current_time - sdata['last_time']
            logger.debug(f'time diff {time_diff:.3f} sdata last time {sdata["last_time"]:3f}')

            message = Discord_Message(
                    member = sdata['member'],
                    member_id = sdata['member_id'],
                    listeners= set(self.listeners.keys()),
                    listener_names= set(self.listeners.values()),
                    timestamp_Audio_Start=sdata['start_time'],
                    timestamp_Audio_End=current_time,
                )

            #check for time diff for end of speaking delay (min_audio_len)
            if time_diff > (self.end_speaking_delay / 1000):
                if len(sdata['buffer']) > self.min_buffer_length:
                    self.queues.audio_in.append(Audio_Message(message=message, audio_data=sdata['buffer']))
                    self.user_speaking.discard(sdata['member_id'])
                    logger.info(f'Audio added to the STT queue for {message.member}')
                else:
                    #this state should never occur
                    logger.info(f'buffer {len(sdata["buffer"])} expected {self.min_buffer_length}')
                
                #either case, setting the last_time to none will have the write method clear the data
                sdata['last_time'] = None

            #check if an interrupt was sent but not enough to process the audio and remove member id from self.user_speakign
            elif (time_diff > self.interrupt_time) and (len(sdata['buffer']) < self.min_buffer_length):
                logger.debug(f'speaker_interrupt_clear sent')
                sdata['last_time'] = None
                self.user_speaking.discard(sdata['member_id'])

    @monitor.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @monitor.after_loop
    async def after(self):
        logger.debug('stt monitor stopped')

    def _drop(self, user_id: int) -> None:
        if user_id in self.audio_buffer_dict:
            del self.audio_buffer_dict[user_id]

    @monitor
    def _await(self, coro: Awaitable[T]) -> CFuture[T]:
        assert self.client is not None
        logger.info(f'stt sink _await')
        return asyncio.run_coroutine_threadsafe(coro)#, self.client.loop)

    def wants_opus(self) -> bool:
        #logger.debug(f'stt sink wants_opus')
        return False

    def write(self, user: Optional[MemberOrUser], data: voice_recv.VoiceData) -> None:

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
            #sdata['iterrupt_sent'] = False
            sdata['start_time'] = time.perf_counter()
            sdata['last_sequence'] = data.packet.sequence

        #logger.info(f'{data.packet.sequence}')
        #discord does not trasmit silence packets, so we have to check for silence here
        if data.packet.sequence > (sdata['last_sequence'] + 1):
            missing_packets = data.packet.sequence - (sdata['last_sequence']+ 1)
            sdata['buffer'].extend([0] * missing_packets * self.audio_packet_length)

        sdata['buffer'].extend(data.pcm)
        sdata['last_time'] = time.perf_counter()
        sdata['last_sequence'] = data.packet.sequence
        
        # add member_id to self.user_speaking when someone speaks in the channel
        self.user_speaking.add(sdata['member_id'])

        logger.debug(f'stt sink write {user}')

    def cleanup(self, *args, **kwargs) -> None:
        logger.debug(f'communications cleanup')
        self.queues.audio_out.clear()
        if self.voice_client.is_playing():
            self.voice_client.pause()
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

class Audio_Cog(commands.Cog):
    def __init__(self, bot: Commands_Bot):
        self.bot: Commands_Bot = bot
        self.voice_client: discord.VoiceClient = None
        self.voice_channel: discord.VoiceChannel = None
        self.voice_channel_title = self.bot.___custom.config['com_voice_channel']
        self.stt_sink: Speech_To_Text_Sink = None
        self.queues = self.bot.___custom.queues
        self.listeners: dict[int, str] = self.bot.___custom.current_listeners
        self.user_speaking: set[int] = self.bot.___custom.user_speaking

    @commands.Cog.listener('on_connect')
    async def on_connect(self):
        await asyncio.sleep(5)
        await self._connect_voice()
        logger.info(f'voice_client_connected {self.voice_client.supported_modes}')

#    @commands.Cog.listener('on_speaker_event')
#    async def on_speaker_event(self, **kwargs) -> None:
#        pass

    async def _connect_voice(self):
        self.voice_channel = discord.utils.get(self.bot.get_all_channels(), name=self.voice_channel_title)
        
        if self.voice_channel is None:
            logger.info("Voice channel not found.")
            return
        
        self.voice_client = await self.voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        self.stt_sink = Speech_To_Text_Sink(
                bot = self.bot, 
                play_queue = self.queues.audio_out, 
                listeners = self.listeners,
                min_audio_len= int(self.bot.___custom.config['com_min_audio_len']),
                end_speaking_delay= int(self.bot.___custom.config['com_end_speaking_delay']),
                interrupt_time= int(self.bot.___custom.config['com_interrupt_time']))
        
        logger.info(f"Connected to {self.voice_channel_title}")
        self.bot.dispatch('voice_client_connected', 
                members = self.voice_channel.members,
                voicechannel=self.voice_channel_title) 

        for member in self.voice_channel.members:
            if member not in self.listeners.keys():
                self.listeners.update({member.id: member.name})

        self.voice_client.listen(self.stt_sink)

    '''        
    @commands.Cog.listener('on_TTS_play')
    async def on_TTS_play(self, audio:io.BytesIO, **kwargs):
        logger.debug('on TTS play received')
        self.queues.audio_out.append(audio)
    '''

    @AudioSink.listener()
    def on_voice_member_disconnect(self, member: discord.Member, ssrc: Optional[int]) -> None:
        if member.id in self.listeners.keys():
            self.listeners.popitem(member.id)
            logger.info(f'listener {member.name} id {member.id} removed')
        else:
            logger.info(f'Error: {member.name} id {member.id} not in listeners')

    @commands.Cog.listener('on_voice_member_speaking_state')
    async def on_voice_member_speaking_state(self, member: discord.Member, *args, **kwargs):
        if member.id not in self.listeners.keys():
            self.listeners.update({member.id : member.name})
        self.user_speaking.add(member.id)
            
    async def cleanup(self):
        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Audio_Cog(bot))