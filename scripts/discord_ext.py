import io, time
from datetime import datetime

from dataclasses import dataclass
from collections import deque

from discord import TextChannel, VoiceChannel
from discord.ext import commands

from utils.datatypes import Discord_Message, Audio_Message, TTS_Message, Halluicanation_Sentences, DB_InOut

class Commands_Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.___custom = Discord_Container(*args, **kwargs)

        # not entirely sure why this is necessary, but its probably due to discord.py and contexts
        self._TextInterface___custom = self.___custom
        self._Bot_Manager___custom = self.___custom
        self._Audio_Cog___custom = self.___custom
        self._SQL_Interface___custom = self.___custom
        self._TTS_Piper___custom = self.___custom
        self._STT_wfw___custom = self.___custom
        self._Speech_To_Text_Sink___custom = self.___custom
        self._TTS___custom = self.___custom

class Queue_Container():
    def __init__(self):
        self.audio_in: deque[Audio_Message] = deque()
        self.llm: deque[Discord_Message] = deque()
        self.tts: deque[TTS_Message] = deque()
        self.audio_out: deque[io.BytesIO] = deque()
        self.db_message: deque[Discord_Message] = deque()
        self.text_message: deque[Discord_Message] = deque()
        self.db_loginout: deque[DB_InOut] = deque()

class Discord_Container():
    def __init__(self, *args, **kwargs):
        self.queues = Queue_Container()
        self.config: dict = kwargs["config"]
        self.user_speaking: set = set()
        self.user_last_message: dict = {} #for some reason, my funky setup causes a bug if it fully linted
        self.current_listeners: dict = {}
        self.message_store: dict = {}
        self.member_info: dict = {}
        self.disc_user_messages: dict = {}
        self.message_store_latest_key: int = 0
        self.text_channel: TextChannel  = None
        self.voice_channel: VoiceChannel = None
        self.show_timings: bool = False
        self.show_text: bool = True
        self.TTS_enable: bool = True
        self.db_always_connected: bool = False
        self.display_message_history: bool = True

    def get_message_store_key(self, get_current: bool = False, set: int = None) -> int:
        '''
        increments the self.message_store_latest_key then returns the new value
        if get_current, it returns the current key only
        if set is not None, it sets the key to that value and returns the new value
        '''
        if (not get_current) and (not set):
            self.message_store_latest_key += 1
            return self.message_store_latest_key
        elif set != None:
            self.message_store_latest_key = set
            return self.message_store_latest_key
        else:
            return self.message_store_latest_key

    def halluicanation_check(self, text: str) -> str:
        '''
          minimal verification that it wasnt a hallucination: returns the string if passed, '' if not
        '''
        if text in Halluicanation_Sentences:
            return ''
        elif any(text.startswith(item) for item in Halluicanation_Sentences):
            if any(text.endswith(item) for item in Halluicanation_Sentences):
                return ''
        else:
             return text
        
    def _time_since_last_message(self) -> float:
        current_time = time.perf_counter()
        if len(self.user_last_message) == 0:
            return 60
        else:
            return current_time - max(self.user_last_message.values())
        
    def check_voice_idle(self, idle_time: float, quick_num_members: int = 1, quick_idle_time: float = 0) -> bool:
        '''
        Returns true if the voice channel is idle for a certain amount of time based off a single user or multiple users.
        idle_time is a float in seconds for multiple users since last voice message
        quick_num_members: defaults to 1 for a single user experience, set 0 to disabe, increase if desired (not recommeded)
        quick_idle_time: time before returning true if only one person has spoken, defaults to 0
        '''
        if not idle_time:
            idle_time = 0
        if self.user_speaking:
            return False

        time_since_last_msg = self._time_since_last_message()
        num_quick_speakers = sum(val > (time.perf_counter() - quick_idle_time) for val in self.user_last_message.values())

        if quick_num_members == 0:
            return time_since_last_msg > idle_time
        elif num_quick_speakers <= quick_num_members:
            return time_since_last_msg > quick_idle_time
        else:
            return time_since_last_msg > idle_time
