import io, time
from datetime import datetime

from collections import deque

from discord import TextChannel, VoiceChannel
from discord.ext import commands

from scripts.datatypes import Discord_Message, Audio_Message, TTS_Message, Halluicanation_Sentences, bot_user_info, db_client_user, db_client_in_out

class Commands_Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.custom = Discord_Container(config = kwargs['config'])

        # not entirely sure why this is necessary, but its probably due to discord.py and contexts
        self._Commands_Bot___custom = self.custom
        self._TextInterface___custom = self.custom
        self._Bot_Manager___custom = self.custom
        self._Audio_Cog___custom = self.custom
        self._SQL_Interface___custom = self.custom
        self._TTS_Piper___custom = self.custom
        self._STT_wfw___custom = self.custom
        self._Speech_To_Text_Sink___custom = self.custom
        self._TTS___custom = self.custom

class Discord_Container():
    def __init__(self, config: dict):
        self.config: dict = config
        self.queues = Queue_Container()
        self.user_speaking: set = set()
        self.message_listened_to: dict = {} #for some reason, my funky setup causes a bug if it fully linted
        self.message_store: dict = {}
        self.current_listeners: dict = {}
        self.last_user_audio: dict[int, float] = {}
        self.user_info: dict[int, db_client_user] = {}
        self.bot_info: dict[str, bot_user_info] = {} 


        self.text_channel: TextChannel  = None
        self.voice_channel: VoiceChannel = None
        self.bot_id: int = None
        self.bot_name: int = None


        self.show_timings: bool = False
        self.show_text: bool = True
        self.tts_enable: bool = True
        self.db_always_connected: bool = False
        self.display_message_history: bool = True
        self.show_choice_to_respond: bool = False

    def voice_busy_count(self, idle_time: float, quick_num_members: int = 1, quick_idle_time: float = 0) -> int:
        '''
        Returns true if the voice channel is idle for a certain amount of time based 
        off a single user or multiple users.
        idle_time is a float in seconds for multiple users since last voice message
        quick_num_members: defaults to 1 for a single user experience, set 0 to disabe, increase if desired (not recommeded)
        quick_idle_time: time before returning true if only one person has spoken, defaults to 0

        returns 2 : check the num_quick_speakers and compare to quick_num_members
        returns 1 : check the num_slow_speakers and compare to idle_time
        returns 0 : if no one has spoken in a while
        '''
        if not idle_time:
            idle_time = 0
        if self.user_speaking:
            return False

        time_since_last_msg = self.time_since_last_message()
        num_quick_speakers = sum(val > (time.perf_counter() - quick_idle_time) for val in self.last_user_audio.values())
        num_slow_speakers = sum(val > (time.perf_counter() - quick_idle_time) for val in self.last_user_audio.values())

        if num_quick_speakers >= quick_num_members:
            return 2
        elif num_slow_speakers > 0 and time_since_last_msg > idle_time:
            return 1
        else:
            return 0

    def time_since_last_message(self) -> float:
        current_time = time.perf_counter()
        if len(self.last_user_audio) == 0:
            return 0
        else:
            return current_time - max(self.last_user_audio.values())

class Queue_Container():
    def __init__(self):
        self.audio_in: deque[Audio_Message] = deque()
        self.llm: deque[Discord_Message] = deque()
        self.tts: deque[TTS_Message] = deque()
        self.audio_out: deque[io.BytesIO] = deque()
        self.db_message: deque[Discord_Message] = deque()
        self.text_message: deque[Discord_Message] = deque()
        self.db_loginout: deque[db_client_in_out] = deque()

    """ should be defined in the llm_main
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
    """
    
    """ should be defined in the tts
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
    """

""" was thinking on needing a way to see how many tokens are availible - future issue
class Token_Reserves():
    def __init__(self, config: dict):
        self.LLM_reserve_tokens_thoughts: int = config["LLM_token_reserve_thoughts"]
        self.LLM_reserve_tokens_conversaion: int = config["LLM_token_reserve_conversation"]

    def __int__(self) -> int:
        return int(sum(vars(self).values()))
"""