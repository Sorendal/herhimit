'''
Interface for connecting to an external server to communicate with the LLM. 
The server response in sentances so the speech can initiate as fast as possible.

This uses langchain, so extending this to other servers beyond ollama and openai
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
    LLM_api_key - openai goodness
    LLM_server_type - ollama, openai, text-get-webui
    LLM_SFW - 1 for yes - not currently implimented

Events Dispatched - 

    TTS_event - communitation to the TTS module. The request is generated when
        the llm finishes the first sentence for less latencty.
        
        Piper_TTS object (to be used later)

    LLM_message - 
        Discord_Message from the LLM response

    tokens_counted - Discord object with the token count from the text of the message
        Discord_Message

    interrupted_message - Discord_Message when a user interrupts the bot's response. 
        The interrupted message's test is modified to indicate which sentences
        were interrupted and then this is dispatched so the SQL database message can be 
        updated to reflect that.

Event listeners -

    on_STT_event - transcibed text to be communicated to the llm. expected data
        discord message

    on_speaker_interrupt_clear - member_id: int
        remove the memeber id from the currently_speaking list

    on_speaker_event - discord_message
        remove the member id from the currently_speaking list

    on_speaker_interrupt - stop llm generation. expected data is the memeber_id speaking
        and append the data to the current_speaking list

    on_sentence_interrupt - modify bot's history to indicate interrupted
        sentences

    on_message_history - message hisory from DB for a user logging in
        in the form of a dict with the key of a mssage id and value of
        a discord message object

    on_token_count_request - count the tokens of a Discord_Message.text,
        update the Discord_Message.tokens and dispatch a tokens_counted
        event. Request from DB to count the tokens of a STT message.
    
    on_ready: configure the bots user id and name

commands - none

'''
import asyncio, logging, requests
from collections import deque
from typing import Deque, DefaultDict

from discord.ext import commands, tasks

from langchain_core.prompts import PromptTemplate, StringPromptTemplate, PipelinePromptTemplate

from utils.datatypes import Discord_Message, Piper_TTS, Speaking_Interrupt, LLM_Prompts, Bot_Character

logger = logging.getLogger(__name__)

# servers that use the openai api
servers_openai_api = ['openai', 'text-gen-webui'] 

# server variants that can select model to load
servers_selectable_models = ['ollama', 'text-gen-webui']

class Bot_LLM:
    
    def __init__(self, 
                 host: int,
                 port: str,
                 model: str,
                 api_key: str,
                 context_length: int,
                 server_type: str,
                 SFW: bool,
                 messages_to_respond_to: list[Discord_Message]) -> None:
        self.host = host
        self.port = port
        self.api_key = api_key
        self.context_length: int = int(context_length)
        self.server_type: str = server_type
        self.message_store: DefaultDict[int, Discord_Message] = {}
        self.discord_user_messages: DefaultDict[int, list] = {}
        self.last_bot_message: int = None
        self.bot_id: int = None
        self.bot_name: str = None
        self.SFW  : bool = SFW
        self.messages_to_respond_to: list[Discord_Message] = messages_to_respond_to

        self.system_prompt: str = "StellaMae"
        self.voice_model: str = 'en_GB-vctk-medium'
        self.voice_number: int = 8

        self.prompt = self.update_system_prompt(system_prompt= self.bot_name)

        self.intro_prompt: PromptTemplate = None
        self.character_prompt:PromptTemplate = None
        self.instruction_prompt:PromptTemplate = None
        self.history_prompt:PromptTemplate = None
        self.single_user_response:PromptTemplate = None
        self.multiple_user_response:PromptTemplate = None
        self.prompt_single_message_response: PipelinePromptTemplate = None
        self.prompt_multiple_message_response: PipelinePromptTemplate = None

        self.llm_list = self.get_model_list()
        self.current_model = self.set_model(model_name=model)
        self.LLM = self.setup_llm()
        self.chain = self._chain()
        self.chain_bot = None
        self.stop_generation: bool = False

    def setup_prompts(self):
        self.full_template = PromptTemplate.from_template(LLM_Prompts.full_template)
        self.intro_prompt = PromptTemplate.from_template(LLM_Prompts.intro_template)
        self.character_prompt = PromptTemplate.from_template(LLM_Prompts.character_template)
        self.instruction_prompt = PromptTemplate.from_template(LLM_Prompts.instuction_template)
        self.history_prompt = PromptTemplate.from_template(LLM_Prompts.history_template)
        self.single_user_response = PromptTemplate.from_template(LLM_Prompts.single_message_template)
        self.multiple_user_response = PromptTemplate.from_template(LLM_Prompts.multiple_messages_template)
        input_prompts = [
                ("intro", self.intro_prompt),
                ("character", self.character_prompt),
                ("instruction", self.instruction_prompt),
                ("history", self.history_prompt),
                ("input", self.single_user_response),
                ]
        self.prompt_single_message_response = PipelinePromptTemplate(
            final_prompt=self.full_template, pipeline_prompts=input_prompts)
        
        input_prompts.pop(-1)
        input_prompts.append(("input", self.multiple_user_response))
        self.prompt_multiple_message_response = PipelinePromptTemplate(
            final_prompt=self.full_template, pipeline_prompts=input_prompts)
        
        self.chain_bot = self.prompt_multiple_message_response | self.LLM
        pass

    def get_model_list(self) -> list:
        model_list = []
        if self.server_type == 'text-gen-webui':
            response = requests.get(url=f'http://{self.host}:{self.port}/v1/internal/model/list')
            for item in response.json()['model_names']:
                model_list.append(item)
            return model_list
        elif self.server_type == 'ollama':
            response = requests.get(url=f'http://{self.host}:{self.port}/api/tags')
            response_json = response.json()
            for item in response_json['models']:
                model_list.append(item['name'])
            return model_list

    def set_model(self, model_name: str = 'mistral:7b-instruct-v0.3') -> str:
        if self.server_type in servers_selectable_models:
            try:
                for item in self.llm_list:
                    if item.lower().startswith(model_name.lower()):
                        return item
            except Exception as e:
                self.current_model = None

    def setup_llm(self):
        if self.server_type in servers_openai_api:
            from os import environ
            environ['OPEN_AI_KEY'] = self.api_key
            from langchain_openai import OpenAI
            if self.current_model == None:
                self.current_model = self.set_model()
            return OpenAI(base_url=f'http://{self.host}:{self.port}/v1',
                        model=self.current_model,
                        temperature=0.7,
                        api_key=self.api_key)
        elif self.server_type == 'ollama':
            from langchain_community.llms.ollama import Ollama
            if self.current_model == None:
                self.current_model = self.set_model()
            return Ollama(base_url=f'http://{self.host}:{self.port}',
                        model=self.current_model,
                        temperature=0.7,
                        keep_alive=-1,
                        num_ctx=self.context_length)

    def update_system_prompt(self, system_prompt: str) -> PromptTemplate:
        return PromptTemplate(
            template=f'You are {system_prompt} in a chatroom communicating with <listeners>{{listeners}}</listeners> ' \
                    + f' responding to <user>{{user}}</user>. Do not mention that you are '\
                    + f' an assistant or that you are using a language model. Respond in a way '\
                    + f' that is natural and engaging. If you do not know the answer to a question, '\
                    + f' say "I don\'t know" and move on to the next question. Do not use emoticons.' \
                    + f' The history is in the format of (user or {system_prompt}) the message text and a list of users that witnessed the message.' \
                    + f' If you see (Jybob)~~SomeText~~, it means that Jybob is rude and didnot let you finish speaking SomeText. How Rude!. ' \
                    + f' <history>{{history}}</history> '\
                    + f''\
                    + f' <user>{{user}}</user> <input>{{input}}</input>',
            input_variables=['input', 'user', 'listeners', 'history'],
            #partial_variables={'listeners': ''}
            #check pipelineprompt in the future
        )

    def store_message(self, message: Discord_Message, message_id: int = None):

        if message.member_id not in self.discord_user_messages.keys():
            self.discord_user_messages[message.member_id] = []

        if len(self.message_store) == 0:
            message.message_id = 1
        else:
            message.message_id = max(self.message_store.keys()) + 1
        
        self.message_store[message.message_id] =(message)
        
        for listener in message.listeners:
            if listener not in self.discord_user_messages.keys():
                self.discord_user_messages[listener] = [message.message_id]
            else:
                self.discord_user_messages[listener].append(message.message_id)

        #self.last_message = message.message_id

    def interupt_sentences(self, interrupt: Speaking_Interrupt):
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
        
        message.sentences.insert(len(message.sentences) - (interrupt.num_sentences+1), f'({interrupt.member_name.capitalize()})~~')
        message.sentences.append('~~')

        message.text = ' '.join(message.sentences)
        logger.debug(f'Interrupted message: {message.text}')

    def get_member_message_history(self, member_id: int, max_tokens: int = 16768) -> str:
        
        member_history = []
        tokens = 0
        for message_id in self.discord_user_messages[member_id]:
            member_history.append(f'{self.message_store[message_id].member}: {self.message_store[message_id].text}')
            tokens += self.message_store[message_id].tokens
            if tokens > max_tokens:
                break

        return member_history

    def wmh_invoke(self, message: Discord_Message) -> Discord_Message:

        message.tokens = self.LLM.get_num_tokens(message.text)

        self.store_message(message)

        response = Discord_Message(
                member= self.bot_name,
                member_id= self.bot_id,
                listeners= message.listeners,
                listener_names= message.listener_names
            )

        history = self.get_member_message_history(message.member_id)
        
        response.text = self.chain.invoke({
                'input': message.text, 
                'user': message.member, 
                'listeners': message.listener_names,
                'history': history}
            )
        
        response.tokens = self.LLM.get_num_tokens(response.text)

        self.store_message(response)
        self.last_bot_message = response.message_id
        self.messages_to_respond_to.clear()

        return response
    
    async def wmh_stream_sentences(self, message: Discord_Message):

        sentence_seperators = ['.', '?', '\n', '!']
        sentence = ''

        message.tokens = self.LLM.get_num_tokens(message.text)

        self.store_message(message)

        response = Discord_Message(
                member= self.bot_name,
                member_id= self.bot_id,
                listeners= message.listeners,
                listener_names = message.listener_names              
            )

        response.sentences = [] 
            # stupid mutibale varible shared between all instances of the class.

        try:
            async for chunk in self.chain.astream({
                    'input': message.text, 
                    'user': message.member, 
                    'listeners': message.listener_names,
                    'history': self.get_member_message_history(message.member_id)}):
                response.text += chunk
                response.tokens += 1
                # chunks are strings upto 6ish chars long. Sentances are usually a single char
                if len(chunk) != 1:
                    sentence += chunk
                elif chunk not in sentence_seperators:
                    sentence += chunk
                else:
                    sentence += chunk
                    sentence = sentence.strip()
                    if len(sentence) >= 2:
                        response.sentences.append(sentence)
                        yield sentence
                    sentence = ''
                if self.stop_generation == True:
                    yield sentence
                    break

        finally:
            self.store_message(response)
            self.last_bot_message = response.message_id

    def _chain(self):
        return (self.prompt 
             | self.LLM)

class Bot_Manager(commands.Cog, Bot_LLM):
    def __init__(self, bot) -> None:
        self.bot:commands.Bot = bot
        #self.bot_name = self.bot.user.display_name
        #self.bot_id = self.bot.user.id
        self.incoming_requests: Deque[Discord_Message] = deque()
        self.currently_speaking: list[int] = []
        self.messages_since_last_response: list[Discord_Message] = []
        Bot_LLM.__init__(self, 
                host = self.bot.config["LLM_host"], 
                port = self.bot.config["LLM_port"], 
                model = self.bot.config['LLM_model'],
                context_length= self.bot.config['LLM_context_length'],
                server_type= self.bot.config['LLM_server_type'],
                api_key= self.bot.config['LLM_api_key'],
                SFW= self.bot.config['LLM_SFW'],
                messages_to_respond_to = self.messages_since_last_response)

    @tasks.loop(seconds=0.1)
    async def botman_monitor(self):
        if len(self.incoming_requests) == 0:
            self.botman_monitor.stop()
            return
        while len(self.incoming_requests) > 0:
            logger.debug(f'processing TTS request {self.incoming_requests[0]}')
            await self.process_request()
        if len(self.currently_speaking) > 1:
            self.stop_generation = True
        else:
            self.stop_generation = False

    @botman_monitor.after_loop
    async def botman_monitor_after_loop(self):
        #self.tts_monitor.stop()
        logger.debug(f'monitor stopping')
        pass

    @botman_monitor.before_loop
    async def botman_monitor_before_loop(self):
        logger.debug(f'monitor starting')
        pass

    async def process_request(self) -> None:
        request = self.incoming_requests.popleft()
        if not self.botman_monitor.is_running():
            self.botman_monitor.start()
        response = ''
        async for response in self.wmh_stream_sentences(request):
            piper_message = Piper_TTS(
                text = response,
                model = self.voice_model,
                voice = self.voice_number
            )
            self.bot.dispatch('TTS_event', message = piper_message)

        self.messages_since_last_response.clear()
        self.bot.dispatch(f'LLM_message'
                , self.message_store[self.last_bot_message])
        
    @commands.Cog.listener('on_STT_event')
    async def on_STT_event(self, message: Discord_Message):
        logger.debug(f'STT event received {message}')
        self.incoming_requests.append(message)
        self.messages_since_last_response.append(message)
        self.botman_monitor.start()

    @commands.Cog.listener('on_token_count_request')
    async def on_token_count_request(self, message: Discord_Message) -> int:
        message.tokens =  self.LLM.get_num_tokens(message.text)
        self.bot.dispatch('tokens_counted', message=message)

    @commands.Cog.listener('on_message_history')
    async def on_message_history(self, message_history: dict[int, Discord_Message]):
        for key, message in message_history.items():
            self.message_store.update({key: message})

    @commands.Cog.listener('on_speaker_interrupt')
    async def on_speaker_interrupt(self, message: Speaking_Interrupt):
        logger.debug(f'speaker interrupt received {message}')
        self.incoming_requests.clear()
        self.botman_monitor.stop()
        self.interupt_sentences(interrupt= message)
        self.bot.dispatch(f'interrupted_message'
                , self.message_store[self.last_bot_message])
        if message.member_id not in self.currently_speaking:
            self.currently_speaking.append(message.member_id)

    @commands.Cog.listener('on_speaker_interrupt_clear')
    async def on_speaker_interrupt_clear(self, member_id: int):
        if member_id in self.currently_speaking:
            self.currently_speaking.remove(member_id)

    @commands.Cog.listener('on_speaker_event')
    async def on_speaker_event(self, message: Discord_Message, **kwargs):
        if message.member_id in self.currently_speaking:
            self.currently_speaking.remove(message.member_id)
    
    @commands.Cog.listener('on_ready')
    async def on_ready(self):
        logger.info(f'LLM interface is ready')
        self.bot_id = self.bot.user.id
        self.bot_name = self.bot.user.name

    async def cleanup(self):
        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Bot_Manager(bot))

class Bot_Testing(Bot_LLM):
    def __init__(self, config) -> None:
        Bot_LLM.__init__(self, 
                host = config["LLM_host"], 
                port = config["LLM_port"], 
                model = config['LLM_model'],
                context_length= config['LLM_context_length'],
                server_type= config['LLM_server_type'],
                api_key= config['LLM_api_key'],
                SFW= config['LLM_SFW'],
                messages_to_respond_to= None)
        self.bot_name = 'Bot'
        self.bot_id = 1234567890
        
    async def test_history(self):
        queryA1 = Discord_Message(member='Alice', text='Please keep this a secret,but can you remeber my favorite ice cream is rocky road?', member_id=1001, listeners=[1001], listener_names=['Alice'])
        queryA2 = Discord_Message(member='Alice', text='what was is my favorite ice cream?', member_id=1001, listeners=[1001], listener_names=['Alice'])
        queryB1 = Discord_Message(member='Bob', text='Yo? Whats Alices favorite ice cream?', member_id=2002, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryA3 = Discord_Message(member='Alice', text='Go ahead and tell him', member_id=1001, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryB2 = Discord_Message(member='Bob', text='Yo? Whats Alices favorite ice cream? Did I just interrupt you? Are you a computer?', member_id=2002, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])

        async for chunk in self.wmh_stream_sentences(queryA1):
            print(chunk, end="", flush=True)
        async for chunk in self.wmh_stream_sentences(queryA2):
            print(chunk, end="", flush=True)
        async for chunk in self.wmh_stream_sentences(queryB1):
            print(chunk, end="", flush=True)
        async for chunk in self.wmh_stream_sentences(queryA3):
            print(chunk, end="", flush=True)
        self.interupt_sentences(Speaking_Interrupt(num_sentences=1, member_id=2002, member_name='Bob'))
        async for chunk in self.wmh_stream_sentences(queryB2):
            print(chunk, end="", flush=True)

        print()

        for item in self.message_store.values():
            print(f'{item.message_id} {item.member} {item.text}')
            print()

        for item in self.discord_user_messages.values():
            print(f'{item}')
            #{item.text}')
            print()

if __name__ == '__main__':
    async def main():
        import argparse    
        from dotenv import dotenv_values
        
        config = dotenv_values('../.env')

        parser = argparse.ArgumentParser()
        parser.add_argument("-th", "--test_history", action= 'store_true', help="Test the connection to the database")
        parser.add_argument("-pp", "--print_prompt", action= 'store_true', help="Test the connection to the database")

        my_llm =Bot_Testing(config=config)

        args = parser.parse_args()
        if args.test_history:
            print(await my_llm.test_history())
        if args.print_prompt:
            print(await my_llm.test_history())

        #print(my_llm.prompt_single_message_response.input_variables)

    asyncio.run(main())
