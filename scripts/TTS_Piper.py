'''
TTS Script that fetches audio from piper using the wyoming protocol

The TTS_Audio dict contains the audio data and the audio details. 
'''

import logging, array

import wyoming.client as wyClient
import wyoming.tts as wyTTS

from utils.datatypes import TTS_Audio

logger = logging.getLogger(__name__)
'''
class Piper():
    def __init__(self, host: str, port: int) -> None:
        self.piper_host:str = None
        self.piper_port:int = None
        self.audio_data = array.array('h')
'''
async def request_TTS(text: str, 
            voice: wyTTS.SynthesizeVoice,
            host: str = None,
            port: int = None,
            ) -> TTS_Audio:

    audio_data = array.array('h')

    my_client = wyClient.AsyncTcpClient(host=host, port=port)
    await my_client.connect()
    await my_client.write_event(wyTTS.Synthesize(text=text, voice=voice).event())

    event = await my_client.read_event()
    while event.type != 'audio-stop':
        if event.type == 'audio-chunk':
            audio_data.frombytes(event.payload)
        event = await my_client.read_event()
    
    ouput = TTS_Audio({
        'audio': audio_data,
        'rate': 22050,
        'channels': 1,
        'width': 2,
        })
    
    return ouput
