'''
Handles STT via wyoming faster whisper (part of the home assistant / rhasspy project).
Yes, the wyomining protocol is not well documented but it works.
'''
import array, logging

from typing import Union 

import wyoming.mic as wyMic
import wyoming.asr as wyAsr
import wyoming.audio as wyAudio
import wyoming.client as wyClient

logger = logging.getLogger(__name__)

async def transcribe(
        audio_data: array.array, 
        host: str, 
        port: int, input_rate: int, 
        input_channels: int, 
        input_width: int) -> Union[str, None]:
    timestamp: int = 0
    my_audio_chunks:list[wyAudio.AudioChunk] = []
    start = 0

    # wyoming protocol data list (home assistant voice)
    while len(audio_data) > start:
        payload_size = 1000
        end = start +  payload_size
        audio_segment = audio_data[start:end]
        my_audio_chunks.append(wyAudio.AudioChunk(
            rate = input_rate,
            width = input_width,
            channels= input_channels,
            audio=audio_segment.tobytes(),
            timestamp=timestamp            
            ))
        timestamp += my_audio_chunks[-1].timestamp + int(
            len(my_audio_chunks[-1].audio) / (input_channels * input_width * input_rate)  * 1000)
        start = end

    #wyoming tranmission start
    my_client = wyClient.AsyncTcpClient(host=host, 
                                        port=port)
    await my_client.connect()
    await my_client.write_event(wyAsr.Transcribe().event())
    await my_client.write_event(wyAudio.AudioStart(
        rate=input_rate, 
        width=input_width, 
        channels=input_channels).event())        
    for item in my_audio_chunks:
        await my_client.write_event(item.event())
    await my_client.write_event(wyAudio.AudioStop().event())        
    response = await my_client.read_event()
    
    return response.data['text']
