import io, array, logging
from datetime import datetime
from typing import TypedDict, NotRequired

from wyoming import tts as wyTTS
from .utils import strip_non_alphanum

logger = logging.getLogger(__name__)
# for the DB cog so the queues can
#   lint properly
#   length can be inspected

positive_responses = ('yes', '1', 'true')
negative_responses = ('no', '0', 'false')

class Prompt_Output(TypedDict):
    start: str
    end: str
    type: NotRequired[str]

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

class Discord_Message():
    def __init__(self, member: str, member_id: int, 
            listeners: set[int], listener_names: set[str], *args, **kwargs) -> None:
        self.member: str = member
        self.member_id: int = member_id
        self.listeners: set[str] = listeners
        self.listener_names: set[str] = listener_names
        if 'text' in kwargs:
            self.text = kwargs['text']
        else:
            self.text: str = ''
        self.text_llm_corrected: str = None
        self.text_user_interrupt: str = None
        self.sentences: list[str] = None
        self.message_id: int = None
        self.timestamp_Audio_Start: datetime = None
        self.timestamp_Audio_End: datetime = None
        self.timestamp_STT: datetime = None
        self.timestamp_LLM: datetime = None
        self.timestamp_TTS_start: datetime = None
        self.timestamp_TTS_end: datetime = None
        self.timestamp_creation: datetime = None
        self.reponse_message_id: int = None
        self.stored_in_db: bool = False
        self.discord_text_message_id: int = None # -1 if restored message from db
        self.discord_retry: int = 0

        self.prompt_tokens: int = 0
        self.prompt_start: int = None
        self.prompt_end: int = None
        self.prompt_type: str = None

class TTS_Message(TypedDict):
    text: str
    timestamp_request_start: float 
    wyTTSSynth: wyTTS.SynthesizeVoice
    alt_host: str # future plans: multiple servers to avoid loading lag for voice models
    alt_port: int
    disc_message: Discord_Message

class RResponse():
    def __init__(self, response_data: str):
        self.positive_responses = positive_responses
        self.negative_responses = negative_responses
        self.response_data: dict = response_data
        self.reasoning: str = None
        self.choice: bool = None
        working_substr = response_data[response_data.find('"response"')+len('"response"'):response_data.rfind('"done"')]
        choice_working = working_substr[working_substr.find('want_to_speak')+len('want_to_speak'):
                                        working_substr.find('reasoning')]
        reasoning_working = working_substr[working_substr.find('reasoning')+len('reasoning'):]

        choice_working = strip_non_alphanum(choice_working)
        self.reasoning = strip_non_alphanum(reasoning_working)

        if choice_working.lower() in self.positive_responses:
            self.choice = True
        else:
            self.choice = False

    def __bool__(self):
        if self.choice == None:
            logger.info(f"Response not set {self.response_data}")
            return False
        return self.choice

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
                timestamp_creation: datetime):
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