from dataclasses import dataclass

@dataclass
class Discord_Message:
    member: str
    member_id: int
    #isteners: dict[int, str] # {member_id: name}
    listeners: list[int] 
    listener_names: list[str]
    text: str = ''
    tokens: int = 0
    sentences: list[str] = None
    message_id: int = None
    timestamp_Audio_Start: float = None
    timestamp_Audio_End: float = None
    timestamp_STT: float = None
    timestamp_LLM: float = None
    timestamp_TTS: float = None
    reponse_message_id: int = None

@dataclass
class Piper_TTS:
    text: str
    model: str
    voice: str
    timestamp_request_start: float = None
    timestamp_request_end: float = None
#    host: str # future plans: multiple servers to avoid loading lag for voice models
#    port: int

@dataclass
class Speaking_Interrupt:
    num_sentences: int
    member_id: int
    member_name: str

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

Halluicanation_Sentences = ('Thank you.', 'Bye-bye.', 'Thanks for watching!', 
    'Thank you for watching.', "I'll see you next time.", '  Thank you so much for watching.')

@dataclass
class LLM_Prompts:
    full_template = '{intro} {character} {instruction} {history} {input}'
    intro_template = 'You are playing {name} in a roleplay where you in an online chatroom.'
    character_template = 'Your name is {bot_name} and are {gender} {age} years old and your physical body is {body_description} wearing {clothes}. Your personality is {personality_list}. Your like {likes_list}. You dislike {dislikes_list}.'
    instuction_template = 'You are to respond as {bot_name} in the chat in a way that is natural and engaging using your personality. Do not use emoticons. If a message is (Jymbob)~~SomeText~~, that means Jymbob interrupted you while you were speaking. How rude!!!'
    history_template = 'Previous messages in the chatroom: {history}'
    single_message_template = '{member} just said {message}. How would you respond?'
    multiple_messages_template = 'Sense you last communicated, the following messages were sent in the chatroom: {messages}. How would you respond?'
     