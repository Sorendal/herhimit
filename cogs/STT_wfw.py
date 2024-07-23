'''
Handles STT via wyoming faster whisper (part of the home assistant / rhasspy project).
Yes, the wyomining protocol is not well documented but it works.

Audio in is process through the deque audio_in containing Audio_Message(audio data and Discord_Message)
The text is added to the Discord_Message and sent to the deque LLM for further processing.
    if the last message in the LLM queue has the same member_id as the current message, it will be merged with that message.
'''
import logging
from datetime import datetime

from discord.ext import commands, tasks
from discord.opus import Decoder as DiscOpus
from typing import Union 

from scripts.STT_wfw import transcribe
from scripts.discord_ext import Commands_Bot
from utils.datatypes import Discord_Message, Halluicanation_Sentences
from utils.utils import time_diff

logger = logging.getLogger(__name__)

class STT_wfw(commands.Cog):
    def __init__(self, bot: Commands_Bot):
        self.bot: Commands_Bot = bot

        self.queues = self.bot.___custom.queues
        self.user_speaking: set[int] = self.bot.___custom.user_speaking
        self.user_last_message: dict[int, float] = self.bot.___custom.user_last_message
        self.time_between_messages: float = float(self.bot.___custom.config['behavior_time_between_messages'])
        self.host = self.bot.___custom.config['STT_host']
        self.port = self.bot.___custom.config['STT_port']

        self.STT_monitor.start()

    def halluicanation_check(self, text: str) -> Union[str, None]:
        '''
          minimal verification that it wasnt a hallucination: returns the string if passed, None if not
          removes trailing punctuation and lowercases the text.

          this usually happens when from silence being fed to whisper and its training data.
          Yes, it probably was trained with youtu
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
            response = await transcribe(
                    audio_data=incoming_audio.audio_data,
                    host=self.host,
                    port=self.port,
                    input_channels=DiscOpus.CHANNELS,
                    input_rate=DiscOpus.SAMPLING_RATE,
                    input_width=DiscOpus.SAMPLE_SIZE)
            message.text = self.halluicanation_check(response)
            if not message.text:
                # hallucination detected, discard the message and return
                return
            message.timestamp_STT = datetime.now()

        #check to see if the last message in the LLM queue is by the same member and update the data
            if self.queues.llm:
                if (self.queues.llm[-1].member_id == message.member_id) and ((self.queues.llm[-1].timestamp_Audio_End - message.timestamp_Audio_End).total_seconds() < self.time_between_messages):
                    current_message = self.queues.llm[-1]
                    current_message.text += ' ' + message.text
                    current_message.timestamp_Audio_End = message.timestamp_Audio_End
                    current_message.timestamp_STT = message.timestamp_STT
                    current_message.listener_names.union(message.listener_names)
                    current_message.listeners.union(message.listeners)
                    logger.info(f'STT - Update LLM message {time_diff(current_message.timestamp_STT, current_message.timestamp_Audio_End)} {current_message.member} {current_message.text}')
            else:
                # new messages are added to the DB and LLM queues. 
                message.message_id = self.bot.___custom.get_message_store_key()
                self.queues.llm.append(message)
                self.queues.db_message.append(message)
                self.queues.text_message.append(message)
                logger.info(f'STT - New LLM message {(time_diff(message.timestamp_Audio_End, message.timestamp_STT))}')#.total_seconds():.3f} {message.member} {message.text}')
                
    async def cleanup(self):
        if self.STT_monitor.is_running():
            self.STT_monitor.stop()

async def setup(bot: commands.Bot):
    await bot.add_cog(STT_wfw(bot))