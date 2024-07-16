'''
TTS cog that uses piper with the wyoming protocol (Home Assistant / Rasspy)

events listened for

    on_TTS_event - adds the event to a deque and checks for the 
        the monitor to start processing the requests. The monitor runs 
        until the deque is empty
        data expected

        piper_tts

events dispatched

    TTS_play - dispatched when the piper has finished processing a request. 
        the only info passed is a filelike object to be played. Discord requires
        stereo 48khz 16bit audio, piper provides mono 22khz 16bit audio, 
        so we need to resample it here
        data_sent

        discord_message
        audio_data: filelike object containing the audio data
'''

import logging, array, io, asyncio, time#, wave
from dataclasses import dataclass
from collections import deque

import numpy as np

import librosa

from discord.opus import Decoder as DiscOpus
from discord.ext import commands, tasks

import wyoming.client as wyClient
import wyoming.tts as wyTTS

from utils.datatypes import TTS_Message, Commands_Bot

logger = logging.getLogger(__name__)

class Piper():
    def __init__(self) -> None:
        self.piper_host:str = None
        self.piper_port:int = None
        self.piper_speaker:int = None
        self.output_rate = DiscOpus.SAMPLING_RATE
        self.output_channels = DiscOpus.CHANNELS
        self.output_size = DiscOpus.SAMPLE_SIZE
        self.piper_rate = 22050
        self.piper_size = 2
        self.piper_channels = 1
        self.audio_data = array.array('h')
        self.resampled_audio = None
        self.processing_requests = False

    async def process_request(self, text: str, 
                voice: wyTTS.SynthesizeVoice,
                alt_host: str = None,
                alt_port: int = None) -> io.BytesIO:

        if alt_host and alt_port:
            my_client = wyClient.AsyncTcpClient(host=alt_host, port=alt_port)
        else:
            my_client = wyClient.AsyncTcpClient(host=self.piper_host, port=self.piper_port)
        await my_client.connect()
        await my_client.write_event(wyTTS.Synthesize(text=text, voice=voice).event())

        event = await my_client.read_event()
        while event.type != 'audio-stop':
            if event.type == 'audio-chunk':
                self.audio_data.frombytes(event.payload)
            event = await my_client.read_event()
        
        #with wave.open(f'piper_output_{self.wave_iter}.wav', 'wb') as wave_file:
        #    wave_file.setframerate(self.piper_rate)
        #    wave_file.setnchannels(self.piper_channels)
        #    wave_file.setsampwidth(self.piper_size)
        #    wave_file.writeframesraw(self.audio_data.tobytes())

        audio_data_np = np.array(self.audio_data, dtype=np.int16)
        self.audio_data = array.array('h')
        audio_data_np_float = np.divide(audio_data_np, 32768)

        await asyncio.sleep(0.001)
        resampled_audio_np_float = librosa.core.resample(
                audio_data_np_float, 
                orig_sr=self.piper_rate, 
                target_sr=self.output_rate,
                res_type='linear')
        await asyncio.sleep(0.001)

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

        return self.resampled_audio

class TTS_Piper(commands.Cog, Piper):

    def __init__(self, bot: Commands_Bot) -> None:
        Piper.__init__(self)
        self.bot: Commands_Bot = bot
        self.queues = self.bot.___custom.queues
        self.show_timings = self.bot.___custom.show_timings
        self.setconfig()
        self.tts_monitor.start()

    def setconfig(self):
        self.piper_host = self.bot.___custom.config['TTS_piper_host']
        self.piper_port = self.bot.___custom.config['TTS_piper_port']
        self.piper_speaker = self.bot.___custom.config['TTS_piper_speaker']
        self.piper_model_name = self.bot.___custom.config['TTS_piper_model']

    @tasks.loop(seconds=0.1)
    async def tts_monitor(self):
        while self.queues.tts:

            tts_message = self.queues.tts.popleft()

            output = await self.process_request(text = tts_message['text'], 
                    voice= tts_message['wyTTSSynth'],
                    alt_host=tts_message['alt_host'],
                    alt_port=tts_message['alt_port'])
            
            self.queues.audio_out.append(output)

            if self.show_timings:
                logger.info(f'TTS request processed {(time.perf_counter() - tts_message["timestamp_request_start"]):.3f}')
    
    async def cleanup(self):
        pass
        
async def setup(bot: commands.Bot, ):
    await bot.add_cog(TTS_Piper(bot=bot))
