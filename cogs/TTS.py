'''
TTS cog 

Designed around Piper, but just set None to the field fothat uses piper with the wyoming protocol (Home Assistant / Rasspy)
'''

import logging, array, io, asyncio#, time#, wave
from datetime import datetime

import numpy as np

import librosa

from discord.opus import Decoder as DiscOpus
from discord.ext import commands, tasks

import wyoming.tts as wyTTS

from utils.datatypes import TTS_Message, TTS_Audio
from scripts.discord_ext import Commands_Bot

from scripts.TTS_Piper import request_TTS

logger = logging.getLogger(__name__)

class TTS(commands.Cog):

    def __init__(self, bot: Commands_Bot) -> None:
        self.bot: Commands_Bot = bot
        self.output_rate = DiscOpus.SAMPLING_RATE
        self.output_size = DiscOpus.FRAME_SIZE
        self.output_channels = DiscOpus.CHANNELS
        self.queues = self.bot.___custom.queues
        self.show_timings = self.bot.___custom.show_timings
        self.tts_host = self.bot.___custom.config['TTS_host']
        self.tts_port = int(self.bot.___custom.config['TTS_port'])
        self.tts_monitor.start()
    '''
    async def process_request(self, text: str, 
                voice: wyTTS.SynthesizeVoice,
                alt_host: str = None,
                alt_port: int = None) -> io.BytesIO:
        pass
    '''
    async def resample_audio(self, tts_audio: TTS_Audio):
        '''
        quick and dirty resampling and converting to stereo. Yes,
        its not the best resample, but it works for this purpose.

        Caveats:
            - only converts mono to stereo
            - does not change sample width (i.e. 16bit expected)
        '''
        audio_data_np = np.array(tts_audio['audio'], dtype=np.int16)

        # resample first
        if tts_audio['rate'] != self.output_rate:
            audio_data_np_float = np.divide(audio_data_np, 32768)
            resampled_audio_np_float = librosa.core.resample(
                    audio_data_np_float, 
                    orig_sr=tts_audio['rate'], 
                    target_sr=self.output_rate,
                    res_type='linear')
            # just to make this as non-blocking as possible
            await asyncio.sleep(0.0001)
            audio_data_np = np.array(np.multiply(resampled_audio_np_float, 32786), dtype=np.int16)

        # convert to stereo if needed
        if (tts_audio['channels'] != self.output_channels) and (tts_audio['channels'] == 1):
                audio_data_np = np.repeat(audio_data_np, self.output_channels)

        return audio_data_np.tobytes()        

    @tasks.loop(seconds=0.1)
    async def tts_monitor(self):
        while self.queues.tts:

            tts_message = self.queues.tts.popleft()

            if tts_message['alt_host'] or tts_message['alt_port']:
                output = await request_TTS(text = tts_message['text'], 
                    voice= tts_message['wyTTSSynth'], 
                    alt_host=tts_message['alt_host'],
                    alt_port=tts_message['alt_port'])
            else:
                output = await request_TTS(text = tts_message['text'], 
                    voice= tts_message['wyTTSSynth'], 
                    host=self.tts_host,
                    port=self.tts_port)

            if (output['rate'] != self.output_rate) or (output['channels'] != self.output_channels):
                output_audio = await self.resample_audio(output)
            else:
                output_audio = output['audio']

            self.queues.audio_out.append(io.BytesIO(output_audio))
            disc_message = tts_message['disc_message']
            if not disc_message.timestamp_TTS_start:
                disc_message.timestamp_TTS_start = datetime.now()
            else:
                disc_message.timestamp_TTS_end = datetime.now()
    
    @commands.Cog.listener('on_connect')
    async def on_connect(self, *args, **kwargs):
        #initial library loading        
        await request_TTS(text='testing',
                voice=None, port=self.tts_port, host=self.tts_host)

    async def cleanup(self):
        pass
        
async def setup(bot: commands.Bot):
    await bot.add_cog(TTS(bot=bot))
