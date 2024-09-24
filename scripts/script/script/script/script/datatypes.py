import io, array, logging, json
from datetime import datetime
from typing import TypedDict, NotRequired, Any
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
    prompt_type: str

    
class TTS_Audio(TypedDict):
    audio: array.array
    rate: int
    width: int
    channels: int
'''
class Personal_Info

Occupation: What they do for a living.
Hobbies and Interests: Activities they enjoy in their free time.
Family: Basic information about family members and relationships.
Background: Where they grew up or have lived.
Education: Where they went to school or their level of education.
Favorite Things: Preferences in music, movies, books, food, etc.
Personality Traits: General characteristics such as being funny, kind, introverted, etc.
Current Events in Life: Major life events like recent travels, upcoming plans, or personal milestones.
Values and Beliefs: Core values, religious beliefs, or political views.
'''

@dataclass
class Discord_Message():
    '''
    Basic message in the bot.

    the first set of data is what is stored long term
    '''
    user_name: str
    user_id: int
    bot_id: str
    bot_name:str
    listener_ids: set[int] = field(default_factory=set)
    listener_names: set[str] = field(default_factory=set)
    text: str = None
    text_llm_corrected: str = None
    text_user_interrupt: str = None
    timestamp: datetime = None
    stored_in_db: bool|int = False
    tokens: int = None
    prompt_type: str = None
    info: dict[str, Any] = field(default_factory=dict)

    # first step is to pass it thought the 1st LLM to check for coherency 
    # and correct any errors and ask if it needs assistance.
    text_coherency_check: bool = False
    text_coherency_check_needs_review: bool = False
    #bot_thoughts: dict[] = field(default_factory=dict)
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

class Binary_Reasoning():
    '''
    This is a wrapper class for self.llm.generate with a question you want to have the 
    LLM to use along with a question you want a yes/no answer to. It will return a bool 
    and a reasoning string. 
    
    Some LLMs do not respond with proper json formatting, so the exception handling brute
    forces it.

    The choice of string for the question matters as the LLM will focus on that.
    My testing scripts simulate two people discussing favorite dog breeds (Shih Tzu and 
    Great Dane), at the time the word was choice, and it responded Great Dane instead of 
    as yes/no answer.

    The resulting object will act as a bool(decision) and a string(reason).
    '''
    def __init__(self, raw_response: Any, question: str = 'want_to_speak'):
#        self.response_data: dict = response_data
        self.response_data: Any = raw_response
        self.reasoning: str = None
        self.choice: bool = None
        
        response_dict = ''
        try:
            response_dict:dict = json.loads(self.response_data)
        except Exception as e:
            print('Error parsing JSON:', e, self.response_data)
            quit()
        if 'response' in response_dict.keys():
            r:dict = json.loads(response_dict['response'])
            if (question and 'reasoning') in r.keys():
                if str(r[question]).lower() in positive_responses:
                    self.choice = True
                else:
                    self.choice = False
                self.reasoning = strip_non_alphanum(r['reasoning'])
                self.response_data = r
                return
        print(self.response_data)        
        quit()
        ''' crufty crap I might need
        working_substr = response_data[response_data.find('"response"')+len('"response"'):response_data.rfind('"done"')]
        choice_working = working_substr[working_substr.find(question)+len(question):
                                        working_substr.find('reasoning')]
        reasoning_working = working_substr[working_substr.find('reasoning')+len('reasoning'):]

        choice_working = strip_non_alphanum(choice_working)
        self.reasoning = strip_non_alphanum(reasoning_working)

        if choice_working.lower() in positive_responses:
            self.choice = True
        else:
            self.choice = False
        '''

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
    
class corrected_text(TypedDict):
    """The corrected text and the original text as inferred by the LLM.
    STT word error rates are still above 6% in perfect conditions, and 
    they will never be perfect. """
    corrected: str
    original: str    

class info_table(TypedDict):
    """ Just easier to deal with the json dump while working this out
    instead of setting up a sql tables"""
    corrected_text: dict[int, corrected_text]

class Speaking_Interrupt(TypedDict):
        num_sentences: int
        user_id: int
        user_name: str

class Audio_Message():
    def __init__(self, audio_data: io.BytesIO, message: Discord_Message):
        self.audio_data: io.BytesIO = audio_data
        self.message: Discord_Message = message

class Prompt_SUA(TypedDict):
    system: str
    system_b: NotRequired[str]
    system_e: NotRequired[str]
    user: str
    user_b: NotRequired[str]
    user_e: NotRequired[str]
    assistant: NotRequired[str]

class Prompt_Split(TypedDict):
    begin: NotRequired[str]
    middle: NotRequired[str]
    end: NotRequired[str]
    tokens: NotRequired[int]

class db_in_out(TypedDict):
    user_id: NotRequired[int]
    bot_id: NotRequired[str]
    in_time: datetime
    out_time: datetime
    db_commit: NotRequired[bool]

@dataclass
class db_client():
    user_id: int
    name: str
    bot_uid: int #This is a string 
    global_name: str = None
    display_name: str = None
    bot: bool
    timestamp: datetime 
    checked_against_db: bool = False
    last_DB_InOut: db_in_out | None = None
    history_recalled: bool = False
    info: dict = field(default_factory=dict)
    voice: str = None
    speaker: int = None
    personality: str = None
    prompt_type: str = None
    prompts: dict[str, Prompt_Split] = field(default_factory=dict)
    knowledge_user: dict = field(default_factory=dict)
    knowledge_bot: dict = field(default_factory=dict)
    opinion_user: dict = field(default_factory=dict)
    opinion_bot: dict = field(default_factory=dict)

    def get_tokens(self, prompt_name: str):
        if prompt_name in self.prompts:
            return self.prompts[prompt_name]['tokens']
        else:
            raise ValueError(f"Prompt name '{prompt_name}' not found.")
        
    def set_tokens(self, prompt_name: str, tokens: int):
        if prompt_name in self.prompts:
            self.prompts[prompt_name]['tokens'] = tokens
        else:
            raise ValueError(f"Prompt name '{prompt_name}' not found.")
    
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