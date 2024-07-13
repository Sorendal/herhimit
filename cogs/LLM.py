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
    LLM_speaker_pause_time - time to pause between speakers in ms.
    LLM_message_history_privacy - as the messages are processed in batches, there has 
        to be a way to limit the message history. Might need to impliment a responded to for the
        bot messages
        0 - everyone can see all messages
        1 - what the speakers have heard and said - implemnted
        2 - only the speakers have said
        3 - only mimial set of listeners (extremely restrictive - new user in the room will block all messages)

    behavior_track_text_interrupt : bool. If you want the message interrupts to be tracked

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

    STT_event_HC_passed - minimal halucination check passed, for the text interface
        Discord_Message

    speaker_event_append - checks to see if the previous message has completed transciption
        and dispatches a message if it has not. Data passed.
            previous_message: Discord_Message
            new_message: Discord_Message

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
import asyncio, logging, requests, time
from typing import DefaultDict, Callable

from discord.ext import commands, tasks

from langchain_core.prompts import PromptTemplate, StringPromptTemplate, PipelinePromptTemplate

from utils.datatypes import Discord_Message, Piper_TTS, Speaking_Interrupt, Halluicanation_Sentences, Commands_Bot, LLM_Prompts

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
                 message_store: dict[int, list[Discord_Message]],
                 message_history_privacy: int) -> None:
        self.host = host
        self.port = port
        self.api_key = api_key
        self.context_length: int = int(context_length)
        self.server_type: str = server_type
        
        self.message_store: DefaultDict[int, Discord_Message] = message_store        
        self.discord_user_messages: DefaultDict[int, set[int]] = {}

        self.last_bot_message: int = 0
        self.bot_id: int = None
        self.bot_name: str = None
        self.SFW  : bool = SFW
        self.message_history_privacy: int = message_history_privacy

        self.system_prompt: str = "StellaMae"
        self.voice_model: str = 'en_GB-vctk-medium'
        self.voice_number: int = 8

        self.prompt = self.update_system_prompt()

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

    def update_system_prompt(self) -> PromptTemplate:
        return PromptTemplate(
            template=f'<|system|>\n You are {{bot_name}} in a chatroom communicating with the {{listener_number}} members {{listeners}} in the room who are friends. Only respond to with users in the chatroom and only those users. ' \
                    + f' Do not mention that you are an assistant or that you are using a language model or AI model.'\
                    + f' This output will be sent to a text-to-speech program so it is impossible for you to imitate other users, so DO NOT TRY. Do not be too nice. Respond in a way '\
                    + f' that is natural to the conversation that address what is being discussed focusing on the messages in the user promp. Do do not repeat messages verbatium. If you do not know the answer to a question, '\
                    + f' say "I don\'t know" and move on to the next question. Do not use emoticons. Do not preface your response with your name' \
                    + f' Focus more on what the user is saying than on your own thoughts. ' \
                    + f' If you see ()~~SomeText~~, it means that the user in the () rudely interrupted you and did not let you finish speaking SomeText. Feel free to express if being interrupred annoyed you.' \
                    + f' The previous messages are as follows: {{history}}'\
                    + f''\
                    + f' Respond to the following messages<|user|>\n{{input}}\n<|assistant|>',
            input_variables=['input', 'bot_name', 'listeners', 'listener_number', 'history'],
            #partial_variables={'listeners': ''}
            #check pipelineprompt in the future
        )

    def store_message(self, message: Discord_Message, message_id: int = None):

        if message.member_id not in self.discord_user_messages.keys():
            self.discord_user_messages[message.member_id] = set()

        if len(self.message_store) == 0:
            message.message_id = 1
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

        message.text_user_interrupt = ' '.join(message.sentences)
        return self.message_store[self.last_bot_message]

    def get_member_message_history(self, member_id: int = None, member_ids: list[int] = None, max_tokens: int = 16768) -> str:
        
        member_history = []
        tokens = 0

        #single users message history
        if member_id != None:
            for message_id in self.discord_user_messages[member_id]:
                member_history.append(f'{self.message_store[message_id].member}: {self.message_store[message_id].text}')
                tokens += self.message_store[message_id].tokens
                if tokens > max_tokens:
                    break

        #multiple users message history with messages listend to
        if member_ids != None:
            keyset = set()
            for id in member_ids:
                if id not in self.discord_user_messages.keys():
                    self.discord_user_messages[id] = set()
                keyset.update(self.discord_user_messages[id])
            keylist = sorted(keyset)
            keylist.reverse()
            for message_id in keylist:
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
    
    async def wmh_stream_sentences(self, 
                message: Discord_Message = None, 
                messages: list[Discord_Message] = None,
                response_message: Discord_Message = None):

        sentence_seperators = ['.', '?', '\n', '!']
        sentence = ''

        if response_message:
            response = response_message
        else:
            response = Discord_Message(
                member= self.bot_name,
                member_id= self.bot_id,
                listeners= None,
                listener_names = None,
            )

        if message:
            message.tokens = self.LLM.get_num_tokens(message.text)
            self.store_message(message)
            query_history = self.get_member_message_history(message.member_id)
            query_input = f'{message.member}: {message.text}'

            response.listener_names = message.listener_names
            response.listeners = message.listeners
        
        elif messages:
            query_history = self.get_member_message_history(member_ids = set([message.member_id for message in messages]))
            query_input = ''
            for message in messages:
                message.tokens = self.LLM.get_num_tokens(message.text)
                if response.listeners:
                    response.listeners.union(set(message.listeners))
                else:
                    response.listeners = message.listeners.copy()
                if response.listener_names:
                    response_message.listener_names.union(message.listener_names)
                else:
                    response.listener_names = message.listener_names.copy()

                self.store_message(message)
                query_input += f'{message.member}: {message.text}\n'

        response.sentences = [] 
            # stupid mutibale varible shared between all instances of the class.

        try:
            sentence = ''
            async for chunk in self.chain.astream({
                    'bot_name': self.bot_name,
                    'input': query_input, 
                    'listeners': ', '.join(response.listener_names),
                    'history': query_history,
                    'listener_number': str(len(response.listeners))}):
                # chunks are strings upto 6ish chars long. Sentances are usually a single char
                #if len(chunk) != 1:
                #    sentence += chunk
                if chunk not in sentence_seperators:
                    sentence += chunk
                else:
                    sentence += chunk
                    sentence = sentence.strip()
                    if sentence.startswith(f'{self.bot_name}'):
                        sentence = sentence[len(f'{self.bot_name} + 1'):]
                    if len(sentence) >= 2:
                        response.sentences.append(sentence)
                        yield sentence
                    sentence = ''
                if self.stop_generation == True:
                    yield sentence
                    break

        finally:
            response.text = ' '.join(response.sentences).strip()
            response.tokens = self.LLM.get_num_tokens(response.text)
            self.store_message(response)
            self.last_bot_message =response.message_id
            for message in messages:
                message.reponse_message_id = response.message_id

    def _chain(self):
        return (self.prompt 
             | self.LLM)

class Bot_Manager(commands.Cog, Bot_LLM):
    def __init__(self, bot) -> None:
        self.bot: Commands_Bot = bot
        self.requests: list[Discord_Message] = []
        self.currently_speaking: list[int] = []

        self.speaker_pause_time = int(self.bot.___custom.config['LLM_speaker_pause_time']) / 1000

        self.track_message_interrupt: bool = bool(
                int(self.bot.___custom.config['behavior_track_text_interrupt']))

        Bot_LLM.__init__(self, 
                host = self.bot.___custom.config["LLM_host"], 
                port = self.bot.___custom.config["LLM_port"], 
                model = self.bot.___custom.config['LLM_model'],
                context_length= self.bot.___custom.config['LLM_context_length'],
                server_type= self.bot.___custom.config['LLM_server_type'],
                api_key= self.bot.___custom.config['LLM_api_key'],
                SFW= self.bot.___custom.config['LLM_SFW'],
                message_store = self.bot.___custom.message_store,
                message_history_privacy = self.bot.___custom.config['LLM_message_history_privacy'])
        
        self.check_voice_idle = self.bot.___custom.check_voice_idle
        self.user_speaking = self.bot.___custom.user_speaking
        self.queues = self.bot.___custom.queues

    @tasks.loop(seconds=0.1)
    async def botman_monitor(self):

        if self.user_speaking:
            self.stop_generation = True
        else:
            self.stop_generation = False

        # check if the messages have been responded to in self.queue.llm and remove them
        while (self.queues.llm and self.queues.llm[0].reponse_message_id):
            self.queues.llm.popleft()

        # check voice idle and process messages
        if self.check_voice_idle(idle_time=self.speaker_pause_time) and self.queues.llm:
            result = await self.process_user_messages(self.queues.llm.copy())
            
    @botman_monitor.after_loop
    async def botman_monitor_after_loop(self):
        #self.tts_monitor.stop()
        logger.debug(f'monitor stopping')
        pass
    @botman_monitor.before_loop
    async def botman_monitor_before_loop(self):
        logger.debug(f'monitor starting')
        pass

    async def process_user_messages(self, messages: list[Discord_Message]) -> bool:
        response_message = Discord_Message(
                member= self.bot_name,
                member_id= self.bot_id,
                listener_names= None,
                listeners= None,
                message_id= self.bot.___custom.get_message_store_key(),
            )
        
        async for response in self.wmh_stream_sentences(messages=messages, 
                response_message = response_message):
            self.queues.tts.append(Piper_TTS(
                text = response,
                model = self.voice_model,
                voice = self.voice_number,
                timestamp_request_start=messages[0].timestamp_Audio_End
            ))
        self.queues.text_message.append(response_message)

    @commands.Cog.listener('on_token_count_request')
    async def on_token_count_request(self, message: Discord_Message) -> int:
        message.tokens =  self.LLM.get_num_tokens(message.text)
        self.bot.dispatch('tokens_counted', message=message)

    @commands.Cog.listener('on_message_history')
    async def on_message_history(self, message_history: dict[int, Discord_Message]):
        for key, message in message_history.items():
            self.message_store.update({key: message})

    @commands.Cog.listener('on_speaking_interrupt')
    async def on_speaking_interrupt(self, speaking_interrupt: Speaking_Interrupt):
        if self.track_message_interrupt:
            message = self.interupt_sentences(interrupt = speaking_interrupt)
            self.queues.text_message.append(message)

    @commands.Cog.listener('on_ready')
    async def on_ready(self):
        logger.info(f'LLM interface is ready')
        self.bot_id = self.bot.user.id
        self.bot_name = self.bot.user.name
        self.botman_monitor.start()
        # delay with library load
        self.LLM.get_num_tokens('The quick brown fox')

    async def cleanup(self):
        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Bot_Manager(bot))

class Bot_Testing(Bot_LLM):
    def __init__(self, config) -> None:
        self.message_store = {}

        Bot_LLM.__init__(self, 
                host = config["LLM_host"], 
                port = config["LLM_port"], 
                model = config['LLM_model'],
                context_length= config['LLM_context_length'],
                server_type= config['LLM_server_type'],
                api_key= config['LLM_api_key'],
                message_store= self.message_store,
                SFW= config['LLM_SFW'],
                message_history_privacy=None)
        self.message_store = {}
        self.bot_name = 'Yasmeen'
        self.bot_id = 1234567890
        #self.update_system_prompt(system_prompt=self.bot_id)
        
    async def test_history(self):
        queryA1 = Discord_Message(member='Alice', text='Can you remeber my favorite ice cream is rocky road?', member_id=1001, listeners=[1001], listener_names=['Alice'])
        queryA2 = Discord_Message(member='Alice', text='what was is my favorite ice cream?', member_id=1001, listeners=[1001], listener_names=['Alice'])
        queryB1 = Discord_Message(member='Bob', text='Yo? Whats Alices favorite ice cream?', member_id=2002, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryA3 = Discord_Message(member='Alice', text='Go ahead and tell him', member_id=1001, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryB2 = Discord_Message(member='Bob', text='Yo? Whats Alices favorite ice cream? Did I just interrupt you? Are you a computer?', member_id=2002, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryA4 = Discord_Message(member='Alice', text='Hey my favorite kind of dog is a Shih Tzu, what is yous bob?', member_id=1001, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryB3 = Discord_Message(member='Bob', text='Bleh, small dogs suck. Give me a Great Dane any day', member_id=2002, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryA5 = Discord_Message(member='Alice', text='Great danes... hope you like heart ache, they dont live long. Yasmeen, my name is Alice, not ice.', member_id=1001, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryB5 = Discord_Message(member='Bob', text='Thats one of the reasons I love em, new personalities every couple of years. That shih tzu is gonna be around forever', member_id=2002, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryA6 = Discord_Message(member='Alice', text='Hey... I love my little Shih Head. Back off you fucker', member_id=1001, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])
        queryB6 = Discord_Message(member='Bob', text='You are such a wussie with your attachment issues', member_id=2002, listeners=[1001, 2002], listener_names=['Alice', 'Bob'])

        async for chunk in self.wmh_stream_sentences(messages=[queryA1]):
            pass
        async for chunk in self.wmh_stream_sentences(messages=[queryA2]):
            pass
        async for chunk in self.wmh_stream_sentences(messages=[queryB1]):
            pass
        async for chunk in self.wmh_stream_sentences(messages=[queryA3]):
            pass
        self.interupt_sentences(Speaking_Interrupt(num_sentences=1, member_id=2002, member_name='Bob'))
        async for chunk in self.wmh_stream_sentences(messages=[queryB2]):
            pass
        async for chunk in self.wmh_stream_sentences(messages=[queryA4, queryB3]):
            pass
        async for chunk in self.wmh_stream_sentences(messages=[queryA5, queryB5, queryA6, queryB6]):
            pass

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

        await my_llm.test_history()
        '''listeners= ["listener1", "listener2"]
        print(my_llm.prompt.format(
                bot_name=my_llm.bot_name,
                history="---some history------some history------some history------some history------some history---",
                input="---some input---",
                listeners= ", ".join(listeners),
            ))
        '''
    asyncio.run(main())
