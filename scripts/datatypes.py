import io, array, logging
from datetime import datetime
from typing import TypedDict, NotRequired
from dataclasses import dataclass, field

from wyoming import tts as wyTTS
from scripts.utils import strip_non_alphanum

logger = logging.getLogger(__name__)

positive_responses = ('yes', '1', 'true')
negative_responses = ('no', '0', 'false')

class Prompt_Output(TypedDict):
    string_start: str
    string_end: str
    tokens: int

class DB_InOut(TypedDict):
    member_id: int
    in_time: datetime
    out_time: datetime
    db_commit: NotRequired[bool]
    
class TTS_Audio(TypedDict):
    audio: array.array
    rate: int
    width: int
    channels: int

@dataclass
class Discord_Message():
    '''
    Basic message in the bot.

    the first set of data is what is stored long term
    '''
    user_name: str
    user_id: int
    listener_ids: set[int] = field(default_factory=set)
    listener_names: set[str] = field(default_factory=set)
    text: str = None
    text_llm_corrected: str = None
    text_user_interrupt: str = None
    timestamp: datetime = None
    prompt_tokens: int = 0
    prompt_start: str = None
    prompt_end: str = None
    prompt_type: str = None
    db_stored: bool = False
    db_id: int = None #used for prompt regen
    
    # the following data is temp data
    sentences: list[str] = field(default_factory=list)
    message_id: int = None
    timestamp_Audio_Start: datetime = None
    timestamp_Audio_End: datetime = None
    timestamp_STT: datetime = None
    timestamp_LLM: datetime = None
    timestamp_TTS_start: datetime = None
    timestamp_TTS_end: datetime = None
    reponse_message_id: int = None
    discord_text_message_id: int = None # -1 if restored message from db
    discord_text_retry: int = 0

class TTS_Message(TypedDict):
    text: str
    timestamp_request_start: float 
    wyTTSSynth: wyTTS.SynthesizeVoice
    alt_host: str # future plans: multiple servers to avoid loading lag for voice models
    alt_port: int
    disc_message: Discord_Message

class CTR_Reasoning():
    '''
    the response:

    acts as bool and a str
    '''
    def __init__(self, response_data: str):
        self.response_data: dict = response_data
        self.reasoning: str = None
        self.choice: bool = None
        working_substr = response_data[response_data.find('"response"')+len('"response"'):response_data.rfind('"done"')]
        choice_working = working_substr[working_substr.find('want_to_speak')+len('want_to_speak'):
                                        working_substr.find('reasoning')]
        reasoning_working = working_substr[working_substr.find('reasoning')+len('reasoning'):]

        choice_working = strip_non_alphanum(choice_working)
        self.reasoning = strip_non_alphanum(reasoning_working)

        if choice_working.lower() in positive_responses:
            self.choice = True
        else:
            self.choice = False

    def __bool__(self):
        if self.choice == None:
            logger.info(f"Response not set {self.response_data}")
            return False
        return self.choice
    
    def __str__(self) -> str:
        if self.choice == None or self.reasoning == None:
            logger.info(f"Response not set {self.response_data}")
            return ''
        elif not self.reasoning:
            logger.info(f"Reasoning not set {self.response_data}")
            return f'{self.choice}'
        return f"{self.choice} - {self.reasoning}"

class Speaking_Interrupt():
    def __init__(self, num_sentences: int, 
                 members: set[int], 
                 member_names: set[str]):
        self.num_sentences: int = num_sentences
        self.members: set[int] = members
        self.member_names: set[str] = member_names

class Audio_Message():
    def __init__(self, audio_data: io.BytesIO, message: Discord_Message):
        self.audio_data: io.BytesIO = audio_data
        self.message: Discord_Message = message

class Cog_User_Info():
    def __init__(self, member_id: int,
                name: str,
                global_name: str,
                display_name: str,
                bot: bool,
                timestamp_creation: datetime,
                last_DB_InOut: bool):
        self.member_id: int = member_id
        self.name: str = name
        self.global_name: str = global_name
        self.display_name: str = display_name
        self.bot: bool = bot
        self.timestamp_creation: datetime = timestamp_creation
        self.checked_against_db: bool = False
        self.last_DB_InOut: DB_InOut = None
        self.history_recalled: bool = False

Halluicanation_Sentences = (
    'thank you', 
    'bye-bye', 
    'thanks for watching',
    'thank you for watching',
    "i'll see you next time", 
    "i will see you next time", 
    'thank you so much for watching',
    "next time",
    "i'll see you in the next video")