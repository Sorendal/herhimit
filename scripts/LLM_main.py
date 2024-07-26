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
    LLM_message_history_privacy - what information the bot has when crafting a response. 
        It might be gosspy, but it might not be. Levels 3 and 4 might be a little too
        restrictive (i.e. a new user hops in a quiet channel and talks and the bot is
        responds to the 1st message as if they are talking to themselves).
        0 - all history
        1 - only what any listeners have heard 
        2 - only what all listeners has heard (default)
        3 - only what any speakers have heard 
        4 - only what all speakers have heard 
        
    behavior_track_text_interrupt : bool. If you want the message interrupts to be tracked.
        LLMs might figure out the interrupts are happening as their text messages are modified
        with (InterruptingUserName)~~SentencesInterrupted~~, and might get snarky about it. 
        I didnt put it in the prompt cause the LLM gets creative and thinks it can interrupt you.

    LLM_server_type: ollama, openai, text-gen-webui...
    LLM_prompt_format: see the LLM_prompts.py for more info.

'''
import logging, asyncio
from datetime import datetime
from typing import DefaultDict, Union
from collections import deque

from scripts.datatypes import Discord_Message, Speaking_Interrupt, CTR_Reasoning
from scripts.LLM_interface import LLM_Interface
from scripts.LLM_prompts import LLM_Prompts, Assistant_Prompt, System_Prompt, CTR_Prompt, Prompt_SUA
from scripts.utils import strip_non_alphanum

logger = logging.getLogger(__name__)

class Bot_LLM():
    
    def __init__(self, 
                    config: dict, 
                    message_store: dict, 
                    message_listened_to: dict,
                    bot_name: str,
                    bot_id: int):
        
        self.llm = LLM_Interface(config)
        self.prompts = LLM_Prompts(bot_name=bot_name,
                        model_prompt_template=config["LLM_prompt_format"],
                        SFW=config["LLM_SFW"])

        self.message_store: DefaultDict[int, Discord_Message] = message_store        
        self.message_listened_to: DefaultDict[int, set[int]] = message_listened_to
        
        self.bot_name = bot_name
        self.bot_id = bot_id

        #message tracking
        self.last_bot_message: int = 0
        self.message_id_high: int = 0
        self.message_id_low : int = -1

        self.bot_id: int = bot_id
        self.bot_name: str = bot_name

        self.message_history_privacy: int = config['LLM_message_history_privacy']

        self.voice_model: str = 'en_GB-vctk-medium'
        self.voice_number: int = 8

        self.tokens_chat = ((int(config['LLM_context_length']) * 3) // 4)
        self.tokens_chat_response = int(config['LLM_token_response'])
        self.tokens_thoughts = self.tokens_chat // 3
        self.tokens_thoughts_response = self.tokens_chat_response // 2

        self.stop_generation: bool = False

        self.get_token_queue = deque()

    def get_ctr_prompts(self, 
                    disc_messages: list[Discord_Message],
                    ctr_prompt: CTR_Prompt,
                    assistant_prompt: Assistant_Prompt) -> Prompt_SUA:

        available_tokens = self.tokens_thoughts - self.tokens_thoughts_response 
        available_tokens -= assistant_prompt.tokens - ctr_prompt.ctr_tokens

        asstiant_str = assistant_prompt.gen()
        cur_time = datetime.now()
        new_messages = []
        user_ids = set()
        listener_ids = set()
        listener_names = set()

        for message in disc_messages:
            user_ids.add(message.user_id)
            for id in message.listener_ids:
                listener_ids.add(id)
            for name in message.listener_names:
                listener_names.add(name)
            new_messages.append(self.prompts.get_formatted_message(
                message = message,
                current_time = cur_time,
                prompted = True))
            if message.prompt_tokens:
                available_tokens -= message.prompt_tokens
            else:
                available_tokens -= len(new_messages[-1]) // 4

        history = self.get_message_history(
                user_ids=user_ids,
                listener_ids=listener_ids,
                max_tokens=available_tokens,
                current_time=cur_time,
                prompted=False)

        ctr_str = ctr_prompt.gen(listener_names, history)

        prompts = Prompt_SUA({
                "system": ctr_str,
                "user": "\n".join(new_messages),
                "assistant": asstiant_str
                })

        return prompts

    async def make_a_choice_to_respond(self, 
                disc_messages: list[Discord_Message],
                ctr_prompt: CTR_Prompt,
                assistant_prompt: Assistant_Prompt) -> CTR_Reasoning:

        prompts = self.get_ctr_prompts(disc_messages=disc_messages, 
                ctr_prompt=ctr_prompt, 
                assistant_prompt=assistant_prompt)

        response = await self.llm.generate(
                prompts = prompts,
                output_class=CTR_Reasoning,
                raw=True)

        return response

    def store_message(self, messages: Union[list[Discord_Message]|Discord_Message], 
                      prepend: bool=False):
        '''
        Stores a message in the message store. 
        If prepend is True, the message will be added to the beginning of the message store.
        '''
        if type(messages) != list:
            messages: list[Discord_Message] = [messages]

        min_key = self.message_id_low        
        max_key = self.message_id_high

        for message in messages:
            if message.prompt_tokens is None:
                if not message in self.get_token_queue:
                    self.get_token_queue.append(message)
            if not message.user_id in self.message_listened_to.keys():
                self.message_listened_to[message.user_id] = set()
            if prepend:
                min_key -= 1
                message.message_id = min_key
            else:
                max_key += 1
                message.message_id = max_key
            self.message_store[message.message_id] = message
            for listener in message.listener_ids:
                if listener not in self.message_listened_to.keys():
                    self.message_listened_to[listener] = set()
                self.message_listened_to[listener].add(message.message_id)

        self.message_id_high = max_key
        self.message_id_low = min_key

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

    def _get_message_history_keys(self, 
                    user_ids: set[int], 
                    listener_ids: set[int], 
                    ignore_keys: set[int] = None) -> list[int]:
        '''
        Helper function for get_message_history. Returns a sorted 
        list of keys that are in the message store and
        not in the ignore_keys set. Respects privacy settings.
        '''
        for id in user_ids:
            if id not in self.message_listened_to:
                self.message_listened_to[id] = set()

        keyset = set()

        if self.message_history_privacy == 0:
            keyset.update(self.message_store.keys())
        elif self.message_history_privacy == 1:
            keyset |= {element for id in listener_ids for element in self.message_listened_to[id]}
        elif self.message_history_privacy == 2:
            keyset &= {element for id in listener_ids for element in self.message_listened_to[id]}
        elif self.message_history_privacy == 3:
            keyset |= {element for id in user_ids for element in self.message_listened_to[id]}
        elif self.message_history_privacy == 4:
            keyset &= {element for id in user_ids for element in self.message_listened_to[id]}

        if ignore_keys != None:
            keyset - ignore_keys
        
        keylist = list(keyset)
        keylist.sort(reverse=True)

        return keylist

    def get_message_history(self, 
                user_ids: set[int], 
                listener_ids: set[int], 
                max_tokens: int, 
                current_time: datetime = None, 
                prompted:bool = False,
                ignore_messages: set[int] = None) -> list[str]:

        keylist = self._get_message_history_keys(user_ids, 
                    listener_ids, ignore_messages)
        
        member_history = []
        tokens = 0
    
        if not current_time:
            current_time = datetime.now()

        for message_id in keylist:
            message = self.message_store[message_id]
            output_str = self.prompts.get_formatted_message(
                    message=message,
                    current_time=current_time,
                    prompted=prompted)
            if message.prompt_tokens == None:
                self.get_token_queue(Discord_Message)
                tokens += (message.prompt_end + message.prompt_end) // 4
            else:
                tokens += message.prompt_tokens
            if tokens > max_tokens:
                break
            member_history.append(output_str)

        member_history = reversed(member_history)
        return member_history
        
    def process_sentences(self, sentence: str, previous_sentences: list[str]) -> str:
        '''
        previous_sen is a tuple of 2 elements for formatting reponses. 
        
        Sometimes 2 newlines are good for formatting purposes, 
        but no more than 2 is wanted in this context. 
        
        Sometimes the llm will respond (bots name): (timestamp) (response). 
        This function removes the bots name and fake timestamp from the 
        response.
        '''
        num_previous = min(2, len(previous_sentences))  # limit to last two sentences
        previous_sen = ('', '') if not previous_sentences else tuple(previous_sentences[-num_previous:])
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
            # sentence example 2 minutes, 26 seconds 
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
    
    def get_wmh_prompts(self,messages: Union[list[Discord_Message]|Discord_Message],
            response: Discord_Message, 
            system_prompt:System_Prompt, 
            assistant_prompt:Assistant_Prompt,
            display_history: bool = False) -> Prompt_SUA:
        """
        Get the prompts for the wmh streaming.
        """
        current_time = datetime.now()
        #print(messages)
        avaible_tokens = self.tokens_chat - self.tokens_chat_response
        avaible_tokens -= self.prompts.system.tokens - self.prompts.assistant.tokens
        new_messages = ""

        user_ids = set()

        if type(messages) != list:
            messages:list[Discord_Message] = [messages]

        for message in messages:
            user_ids.add(message.user_id)
            response.listener_ids.update(message.listener_ids)
            response.listener_names.update(message.listener_names)
            #self.store_message(message)
            new_messages += self.prompts.get_formatted_message(message, current_time, prompted=True) + '\n'

        assistant_str = assistant_prompt.gen()
        system_str = system_prompt.gen(listener_names=response.listener_names)

        prompt_list = '\n'.join(self.get_message_history(
                listener_ids = response.listener_ids,
                user_ids=user_ids,
                max_tokens=avaible_tokens, 
                current_time=current_time, prompted=True)) + '\n' + new_messages
        print(prompt_list)
        
        results = Prompt_SUA({
            'system': system_str,
            'assistant': assistant_str,
            'user': '\n'.join(prompt_list)
            })

        if display_history:
            logger.info(f'{"*-"*25}*\n{system_str}{results["user"]}{assistant_str}\n{"*-"*25}*')

        return results
    
    async def wmh_stream_sentences(self, 
                messages: list[Discord_Message],
                bot_response_mesg: Discord_Message, 
                system_prompt:System_Prompt, 
                assistant_prompt:Assistant_Prompt,
                display_history: bool = False):

        prompts = self.get_wmh_prompts(messages = messages, 
                        response=bot_response_mesg, 
                        system_prompt=system_prompt, 
                        assistant_prompt=assistant_prompt,
                        display_history=display_history)

        if self.llm.stop_generation:
            await asyncio.sleep(0.1)
            self.llm.stop_generation = False
            return


        try:
            sentence_seperators = ['.', '?', '\n', '!']        
            sentence:str = ''
            async for chunk_undecoded in self.llm.stream(prompts=prompts):
                #chunk = self.process_chunk(chunk)
                if self.llm.stop_generation == True:
                    await asyncio.sleep(0.1)
                    self.llm.stop_generation = False
                    break
                chunk = chunk_undecoded#= self.decode_chunk(chunk_undecoded)
                if chunk not in sentence_seperators:
                    sentence += chunk
                else:
                    sentence += chunk
                    sentence = self.process_sentences(
                        sentence=sentence,
                        previous_sentences=bot_response_mesg.sentences
                        )
                    if sentence is not None:
                        if sentence != '':
                            if len(sentence) > 0:
                                bot_response_mesg.sentences.append(sentence)
                                yield sentence
                    sentence = ''
        finally:
            #update time
            current_time = datetime.now()
            bot_response_mesg.text = ' '.join(bot_response_mesg.sentences)
            bot_response_mesg.timestamp = current_time
            bot_response_mesg.timestamp_LLM = current_time
            self.store_message(messages)
            self.store_message(bot_response_mesg)
            self.last_bot_message =bot_response_mesg.message_id
            for message in messages:
                message.reponse_message_id = bot_response_mesg.message_id
