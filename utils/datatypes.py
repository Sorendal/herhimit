import io, time, asyncio
from dataclasses import dataclass
from collections import deque

from discord.ext import commands

from wyoming import tts as wyTTS

@dataclass
class Discord_Message:
    member: str
    member_id: int
    listeners: set[int] 
    listener_names: set[str]
    text: str = ''
    text_llm_corrected: str = ''
    text_user_interrupt: str = ''
    tokens: int = 0
    sentences: list[str] = None
    message_id: int = None
    timestamp_Audio_Start: float = None
    timestamp_Audio_End: float = None
    timestamp_STT: float = None
    timestamp_LLM: float = None
    timestamp_TTS: float = None
    reponse_message_id: int = None
    stored_in_db: bool = False
    discord_text_message_id: int = None # -1 if restored message from db

@dataclass
class Piper_TTS:
    text: str
    model: str
    voice: str
    timestamp_request_start: float = None
    timestamp_request_end: float = None
    wyTTSSynth: wyTTS.SynthesizeVoice = None
#    host: str # future plans: multiple servers to avoid loading lag for voice models
#    port: int

@dataclass
class Speaking_Interrupt:
    num_sentences: int
    members: list[int]
    member_names: list[str]

@dataclass
class Audio_Message:
    audio_data: io.BytesIO
    message: Discord_Message

Halluicanation_Sentences = ('Thank you.', 'Bye-bye.', 'Thanks for watching!', 'Thanks for watching.',
    'Thank you for watching.', "I'll see you next time.", '  Thank you so much for watching.', "Next time.")

@dataclass
class Commands_Bot(commands.Bot):
    def __init__(self, command_prefix, intents, config:dict):
        super().__init__(command_prefix=command_prefix, intents=intents)

        self.___custom = Discord_Container(config=config)

        # not entirely sure why this is necessary, but its probably due to discord.py and contexts
        self._TextInterface___custom = self.___custom
        self._Bot_Manager___custom = self.___custom
        self._Audio_Cog___custom = self.___custom
        self._SQL_Interface___custom = self.___custom
        self._TTS_Piper___custom = self.___custom
        self._STT_wfw___custom = self.___custom
        self._Speech_To_Text_Sink___custom = self.___custom

@dataclass
class Queue_Container():
    def __init__(self):
        #self.audio_in: asyncio.Queue[Audio_Message] = asyncio.Queue(maxsize=10)
        #self.audio_out: asyncio.Queue[Audio_Message] = asyncio.Queue(maxsize=30)
        #self.llm: asyncio.Queue[Discord_Message] = asyncio.Queue()
        #self.tts: asyncio.Queue[Piper_TTS] = asyncio.Queue()
        #self.db_message: asyncio.Queue[Discord_Message] = asyncio.Queue()
        #self.text_message: asyncio.Queue[Discord_Message] = asyncio.Queue()
        
        #self.audio_in: list[Audio_Message] = []
        #self.audio_out: list[io.BytesIO] = []
        #self.llm: list[Discord_Message] = []
        #self.tts: list[Piper_TTS] = []
        #self.db_message: list[Discord_Message] = []
        #self.text_message: list[Discord_Message] = []

        self.audio_in: deque[Audio_Message] = deque()
        self.llm: deque[Discord_Message] = deque()
        self.tts: deque[Piper_TTS] = deque()
        self.audio_out: deque[io.BytesIO] = deque()
        self.db_message: deque[Discord_Message] = deque()
        self.text_message: deque[Discord_Message] = deque()

@dataclass
class Discord_Container():
    def __init__(self, config:dict):
        self.queues = Queue_Container()
        self.config: dict = config
        self.user_speaking: set = set()
        self.user_last_message: dict = {} #for some reason, my funky setup causes a bug if it fully linted
        self.current_listeners: dict = {}
        self.message_store: dict = {}
        self.message_store_latest_key: int = 0

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

@dataclass
class Bot_Character:
    name: str
    gender: str
    age: int
    body_description: str
    clothes: str
    personality: str
    likes: str
    dislikes: str


@dataclass
class LLM_Prompts:
    full_template = '{intro} {character} {instruction} {history} {input}'
    intro_template = 'You are playing {name} in a roleplay where you in an online chatroom.'
    character_template = 'Your name is {bot_name} and are {gender} {age} years old and your physical body is {body_description} wearing {clothes}. Your personality is {personality_list}. Your like {likes_list}. You dislike {dislikes_list}.'
    instuction_template = 'You are to respond as {bot_name} in the chat in a way that is natural and engaging using your personality. Do not use emoticons. If a message is (Jymbob)~~SomeText~~, that means Jymbob interrupted you while you were speaking. How rude!!!'
    history_template = 'Previous messages in the chatroom: {history}'
    single_message_template = '{member} just said {message}. How would you respond?'
    multiple_messages_template = 'Sense you last communicated, the following messages were sent in the chatroom: {messages}. How would you respond?'
