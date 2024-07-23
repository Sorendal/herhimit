'''
Interface for connecting to an external server to communicate with the LLM. 
The server response in sentances so the speech can initiate as fast as possible.

This uses httpx for commnications using the ollama interface. Extending it to openai
should be easy. Fetching the model list is not standard, coded in ollama and 
text-gen-webui. Methods to modify are in the class 
    Bot_LLM
        def get_model_list(self) -> list: 
        def set_model(self, model_name: str = 'mistral:7b-instruct-v0.3') -> str:
        def setup_llm(self):

This incorporates a custom message history that associates the messages 
witnessed per user, not interaction. So user a can ask what user b said 
in if user a was present for it.

Context lenght is tricky. Longer to the better, to a point. See needle in the 
haystack tests per model before going too large (models can also become incoherant,
well insane really). Check your hardware. 

Warning - the context length can be quite high at 32k, so even with a token cost 
of .0001 cents per token, it still could cost 3c per message sent to the LLM. So a 
long conversation could get expensive. Be warned before hooking this bot to a 
commercial LLM and letting randos talk to it.

Configuration - expected in the .env config
    LLM_host
    LLM_port
    LLM_model - name of the model to use
        text-gen-webui and ollama will get a model list and you dont have dont have
        to match case and can use shorhand 
    LLM_context_length - default is 16k, but if your model supports it,
        you can increase this.
    LLM_server_type - ollama, openai, text-get-webui
    LLM_SFW - sets how lewd you want the bot to be. I use 2 or 1....
        0 - SFW - LLM is instructed to be safe (use a censored model to be safe)
        1 - NSFW - LLM is instructed respond as an adult, but not encouraged to be lewd
        2 - NSFW - LLM is instructed to respond as an adult and can be lewd
        3 - NSFW - LLM is instructed to respond as an adult and will be lewd
    LLM_speaker_pause_time - time to pause between speakers in ms.
    LLM_message_history_privacy - Work in progress, currently implemented to filter history
        for messages anyone in the room has listened to. 
            
        Should be fairly easy to not filter anything, but the context lenght will limit
            previous conversations.
        Should be fairly easy to filter out any messages so only those that all current 
            members of the channel have heard are sent to the LLM.
        
        The bot may be a gossip and repeat stuff that a user who is not logged in has said.

    behavior_track_text_interrupt : bool. If you want the message interrupts to be tracked.
        LLMs might figure out the interrupts are happening as their text messages are modified
        with (InterruptingUserName)~~SentencesInterrupted~~, and might get snarky about it. 
        I didnt put it in the prompt cause the LLM gets creative and thinks it can interrupt you.

    LLM_server_type: ollama, openai, text-gen-webui...
    LLM_prompt_format: see the LLM_prompts.py for more info.

'''
import logging
from datetime import datetime
from typing import DefaultDict, Union
from collections import deque

from .datatypes import Discord_Message, Speaking_Interrupt
from .LLM_interface import LLM_Interface
from .LLM_prompts import LLM_Prompts
from .utils import strip_non_alphanum

logger = logging.getLogger(__name__)

sentence_seperators = ['.', '?', '\n', '!']


class Bot_LLM(LLM_Interface):
    
    def __init__(self, 
                  host: int,
                 port: str,
                 llm_model: str,
                 api_key: str,
                 context_length: int,
                 server_type: str,
                 SFW: int,
                 message_store: dict[int, Discord_Message],
                 disc_user_messages: dict[int, Discord_Message],
                 message_history_privacy: int,
                 bot_name: int,
                 prompt_format: str,
                 max_response_tokens: int,
                 config: dict,
                 temperature: float = 0.7, ) -> None:
        #LLM_Prompts.__init__(self)
        self.host = host
        self.port = port
        super().__init__(llm_uri = f'http://{self.host}:{self.port}',
                llm_model = llm_model, server_type=server_type,
                temperature = temperature, context_length = int(context_length),
                max_response_tokens=int(max_response_tokens))

        self.api_key = api_key
        
        self.message_store: DefaultDict[int, Discord_Message] = message_store        
        self.discord_user_messages: DefaultDict[int, set[int]] = disc_user_messages

        self.last_bot_message: int = 0
        self.bot_id: int = None
        self.bot_name: str = bot_name
        self.SFW  : bool = SFW
        self.message_history_privacy: int = message_history_privacy

        self.voice_model: str = 'en_GB-vctk-medium'
        self.voice_number: int = 8

        self.prompts = LLM_Prompts(SFW=SFW, 
                model_prompt_template=prompt_format)

        self.max_response_tokens = int(max_response_tokens)
        self.bot_personality: str = self.prompts.jade
        self.stop_generation: bool = False
        self.prompt_format: str = prompt_format
        self.get_tokens = []

    def store_message(self, message: Discord_Message, 
                      message_id: int = None, 
                      prepend: bool=False):
        '''
        Stores a message in the message store. If no message_id is provided, it will be assigned one.
         If prepend is True, the message will be added to the beginning of the message store.
        '''

        if message.member_id not in self.discord_user_messages.keys():
            self.discord_user_messages[message.member_id] = set()

        if len(self.message_store) == 0:
            message.message_id = 1
        elif prepend:
            message.message_id = min(self.message_store.keys()) - 1
        elif not message.message_id:
            message.message_id = max(self.message_store.keys()) + 1
        
        self.message_store[message.message_id] =(message)
        
        for listener in message.listeners:
            if listener not in self.discord_user_messages.keys():
                self.discord_user_messages[listener] = set()
                self.discord_user_messages[listener].add(message.message_id)
            else:
                self.discord_user_messages[listener].add(message.message_id)

        #self.last_message = message.message_id

    def interupt_sentences(self, interrupt: Speaking_Interrupt) -> Discord_Message:
        '''
        insert '(member_name)~~' into the sentences list before the first sentence 
        that was interrupted and append '~~' to the end of the list. Join the sentences
        and replace the message.text with the joined sentences and dispatch an
        interrupted message event.
        '''
        message = self.message_store[self.last_bot_message]

        if interrupt.num_sentences == None:
            logger.info('ValueError: num_sentences cannot be less than 1')
            return
        elif interrupt.num_sentences > len(message.sentences):
            logger.info('ValuteError: num_sentences is greater than the number of sentences in the last message')
            return

        message.sentences.insert(len(message.sentences) - (interrupt.num_sentences), 
                ('(' + ', '.join(member_name.capitalize() for member_name in interrupt.member_names) + ')~~'))
        message.sentences.append('~~')

        message.text_user_interrupt = message.text

        message.text = ' '.join(message.sentences)
        return self.message_store[self.last_bot_message]

    def get_member_message_history(self, member_id: int = None, 
                member_ids: set[int] = None, 
                max_tokens: int = 16768,
                current_time: datetime = None, prompted = False) -> str:
        
        member_history = ""
        tokens = 0
        if not current_time:
            current_time = datetime.now()

        if not member_ids and member_id:
            member_ids = [member_id]
        else:
            member_id = list(member_ids)

        #multiple users message history with messages listend to
        if member_ids:
            keyset = set()
            for id in member_ids:
                if id not in self.discord_user_messages.keys():
                    self.discord_user_messages[id] = set()
                keyset.update(self.discord_user_messages[id])
            keylist = sorted(keyset)
            #keylist.reverse()
            for message_id in keylist:
                message = self.message_store[message_id]
                output_str = self.prompts.get_formatted_message(
                        message=message,
                        current_time=current_time,
                        prompted=prompted)
                if message.prompt_tokens == None:
                    self.get_tokens.append(Discord_Message)
                    #self.queue_get_tokens.append(message.message_id)
                #tokens += message.prompt_tokens
                #if tokens > max_tokens:
                #    break
                member_history += (output_str+'\n')
                
        #print(f"{' '.join(member_history)}")
        return member_history
        
    def process_sentences(self, sentence: str, previous_sentences: list[str]) -> str:
        if len(previous_sentences) == 0:
            sentence = self.format_sentences(
                sentence=sentence, previous_sen=(
                    '', 
                    ''))
        elif len(previous_sentences) == 1:
            sentence = self.format_sentences(
                sentence=sentence, 
                previous_sen=(
                    previous_sentences[-1],
                    ''))
        if len(previous_sentences) > 1:
            sentence = self.format_sentences(
                sentence=sentence, 
                previous_sen=(
                    previous_sentences[-1],
                    previous_sentences[-2]))
        return sentence

    def format_sentences(self, sentence: str, 
                previous_sen: tuple[str, str]) -> Union[str, None]:
        '''
        previous_sen is a tuple of 2 elements for formatting reponses. 
        
        Sometimes 2 newlines are good for formatting purposes, 
        but no more than 2 is wanted in this context. 
        
        Sometimes the llm will respond (bots name): (timestamp) (response). 
        This function removes the bots name and fake timestamp from the 
        response.
        '''
        # Check for repitition of newlines and return None if there 
        # are more than 2 in a row.
        if sentence == '\n':
            if (previous_sen[0] != '\n') and (previous_sen[1] != '\n'):
                return None
        # do not repeat sentences after the newline check
        elif sentence == previous_sen[0]:
            return None
        # Check to see if the previous sentence is empty. If yes, 
        # then this is the first sentence.
        elif previous_sen[0] == '':
            # Check if the bot name is present at the beginning of 
            # the sentence. If yes, remove it from the sentence
            bot_name_loc = sentence.find(self.bot_name)
            if bot_name_loc != -1 and bot_name_loc < 4:
                sentence = sentence[len(self.bot_name)+bot_name_loc:]
            # Check for a timestamp pattern at the beginning of the 
            # sentence
            time_endings = ('day', 'hour', 'minute', 'second')
            word_len = 0
            time_loc = 0
            for item in time_endings:
                if item in sentence:
                    _ = sentence.find(item) + len(item)
                    if _ > time_loc and time_loc < 15:
                        word_len = len(item)
                        time_loc = _
            # If a timestamp pattern is found, remove it from the 
            # sentence
            if time_loc != 0:
                sentence = sentence[word_len + time_loc:]
            # Remove any formatting crap from the start of the sentence
            sentence = strip_non_alphanum(input_string = sentence, 
                                        suffix=sentence[-1])
        else:
            sentence = strip_non_alphanum(input_string = sentence, 
                                        suffix=sentence[-1])
        return sentence
    
    async def wmh_stream_sentences(self, messages: list[Discord_Message],
            response: Discord_Message, display_history: bool = False):

        system_prompt = self.prompts.system.gen(name= self.bot_name, 
                chat_prompt=self.prompts.system_str_personality,
                personality=self.bot_personality)

        user_prompt = ''

        if not self.prompts.system.tokens:
            self.prompts.system.tokens = await self.get_num_tokens(system_prompt)

        avaible_tokens = self.context_length - self.max_response_tokens - self.prompts.system.tokens
        sentence_seperators = ['.', '?', '\n', '!']

        
        current_time = datetime.now()

        for message in messages:

            if not response.listeners:
                response.listeners = message.listeners.copy()
            else:
                response.listeners.union(message.listeners)

            if not response.listener_names:
                response.listener_names = message.listener_names.copy()
            else:
                response.listener_names.union(message.listener_names)

            cur_prompt = self.prompts.get_formatted_message(
                    message = message,
                    current_time = current_time,
                    prompted=True)

            if message.prompt_tokens == 0:
                self.get_tokens.append(message)
                avaible_tokens -= len(cur_prompt) // 4
            else:
                avaible_tokens -= message.prompt_tokens

        user_prompt = self.get_member_message_history(
                member_ids = response.listeners,
                max_tokens=avaible_tokens, 
                current_time=current_time, prompted=True) + user_prompt

        for message in messages:
            self.store_message(message=message)

        assistant_prompt = self.prompts.assistant.gen(name=self.bot_name)
        response.sentences = [] 
        # stupid mutibale varible shared between all instances of the class.
        if display_history:
            print('---------------------------------------------------------')
            print(f'{system_prompt}\n\n{user_prompt}\n\n{assistant_prompt}')
            print()

        try:
            sentence:str = ''
            async for chunk_undecoded in self.stream(
                        system=system_prompt, 
                        user=user_prompt, 
                        assistant=assistant_prompt):
                #chunk = self.process_chunk(chunk)
                if self.stop_generation == True:
                    self.stop_generation = False
                    break
                chunk = chunk_undecoded#= self.decode_chunk(chunk_undecoded)
                if chunk not in sentence_seperators:
                    sentence += chunk
                else:
                    sentence += chunk
                    sentence = self.process_sentences(
                        sentence=sentence,
                        previous_sentences=response.sentences
                        )
                    if sentence is not None:
                        if sentence != '':
                            if len(sentence) > 0:
                                response.sentences.append(sentence)
                                yield sentence
                    sentence = ''
        finally:
            current_time = datetime.now()
            response.text = ' '.join(response.sentences)
            response.timestamp_creation = current_time
            response.timestamp_LLM = current_time
            self.store_message(response)
            self.last_bot_message =response.message_id
            for message in messages:
                message.reponse_message_id = response.message_id

