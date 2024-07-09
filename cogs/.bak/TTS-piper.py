'''
TTS cog that uses piper with the wyoming protocol (Home Assistant / Rasspy)

events listened for

    on_TTS_event - adds the event **kwargs to a deque and checks for the 
        the monitor to start processing the requests. The monitor runs 
        until the deque is empty

events dispatched

    TTS_play - dispatched when the piper has finished processing a request. 
        the only info passed is a filelike object to be played. Discord requires
        stereo 48khz 16bit audio, piper provides mono 22khz 16bit audio, 
        so we need to resample it here

task monitor - has a task monitor to act on a deque of jobs. Monitor
    initiates when first event is added to the deque. Monitor loop 
    self terminates when the deque is empty
'''

import logging, array, io, wave
from collections import deque

import numpy as np

import librosa

from discord.opus import Decoder as DiscOpus
from discord.ext import commands, tasks

import wyoming.client as wyClient
import wyoming.tts as wyTTS

logger = logging.getLogger(__name__)

class  TTS_Piper(commands.Cog):

    def __init__(self, bot:commands.Bot) -> None:
        self.bot = bot
        self.piper_host:str = bot.config['TTS_piper_host']
        self.piper_port:int = bot.config['TTS_piper_port']
        self.piper_model_name: str = bot.config['TTS_piper_model']
        self.piper_speaker:int = bot.config['TTS_piper_speaker']
        self.piper_model = wyTTS.SynthesizeVoice(self.piper_model_name, speaker=0)
        self.output_rate = DiscOpus.SAMPLING_RATE
        self.output_channels = DiscOpus.CHANNELS
        self.output_size = DiscOpus.SAMPLE_SIZE
        self.piper_rate = 22050
        self.piper_size = 2
        self.piper_channels = 1
        self.audio_data = array.array('h')
        self.resampled_audio = None
        self.incoming_requests = deque()
        self.processing_requests = False
        #self.wave_iter = 0

    @tasks.loop(seconds=0.1)
    async def tts_monitor(self):
        if len(self.incoming_requests) == 0:
            self.tts_monitor.stop()
            return
        while len(self.incoming_requests) > 0:
            logger.info(f'processing TTS request {self.incoming_requests[0]}')
            await self.process_requests()

    @tts_monitor.after_loop
    async def tts_monitor_after_loop(self):
        #self.tts_monitor.stop()
        logger.info(f'TTS monitor stopping')
        pass

    @tts_monitor.before_loop
    async def tts_monitor_before_loop(self):
        logger.info(f'TTS monitor starting')
        pass

    @commands.Cog.listener('on_TTS_event')
    async def on_TTS_event(self, **kwargs):
        logger.info(f'on TTS_event received {kwargs["data"]}')
        self.incoming_requests.append(kwargs)
        if not self.tts_monitor.is_running():
            await self.tts_monitor.start()

    async def process_requests(self):
        kwargs = self.incoming_requests.popleft()

        output_text = kwargs['data']
        my_client = wyClient.AsyncTcpClient(host=self.piper_host, port=self.piper_port)
        await my_client.connect()
        await my_client.write_event(wyTTS.Synthesize(text=output_text).event())

        event = await my_client.read_event()
        while event.type != 'audio-stop':
            if event.type == 'audio-chunk':
                self.audio_data.frombytes(event.payload)
            event = await my_client.read_event()
        
        #self.wave_iter += 1
        #with wave.open(f'piper_output_{self.wave_iter}.wav', 'wb') as wave_file:
        #    wave_file.setframerate(self.piper_rate)
        #    wave_file.setnchannels(self.piper_channels)
        #    wave_file.setsampwidth(self.piper_size)
        #    wave_file.writeframesraw(self.audio_data.tobytes())

        audio_data_np = np.array(self.audio_data, dtype=np.int16)
        self.audio_data = array.array('h')
        audio_data_np_float = np.divide(audio_data_np, 32768)
        resampled_audio_np_float = librosa.core.resample(
                audio_data_np_float, 
                orig_sr=self.piper_rate, 
                target_sr=self.output_rate,
                res_type='linear')
        resampled_audio_np = np.array(np.multiply(resampled_audio_np_float, 32786), dtype=np.int16)
        if (self.piper_channels != self.output_channels) and (self.piper_channels == 1):
            resampled_audio_np_stereo = np.repeat(resampled_audio_np, self.output_channels)
        else:
            resampled_audio_np_stereo = resampled_audio_np

        self.resampled_audio = None
        
        self.resampled_audio = io.BytesIO(resampled_audio_np_stereo)

        #with wave.open(f'piper_output_resampled_{self.wave_iter}.wav', 'wb') as wave_file:
        #    wave_file.setframerate(self.output_rate)
        #    wave_file.setnchannels(self.output_channels)
        #    wave_file.setsampwidth(self.output_size)
        #    wave_file.writeframesraw(resampled_audio_np_stereo)

        self.bot.dispatch(f'TTS_play', self.resampled_audio)
        logger.info(f'processed TTS request {kwargs}')
        
async def setup(bot: commands.Bot):
    await bot.add_cog(TTS_Piper(bot))