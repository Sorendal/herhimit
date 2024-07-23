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

Event listeners -

    on_speaker_interrupt - stop llm generation. expected data is the memeber_id speaking
        and append the data to the current_speaking list

    on_message_history - message hisory from DB for a user logging in
        in the form of a dict with the key of a mssage id and value of
        a discord message object
   
commands - none

'''
import logging
from datetime import datetime
from typing import DefaultDict

from discord.ext import commands, tasks

from utils.datatypes import Discord_Message, TTS_Message, Speaking_Interrupt
from scripts.discord_ext import Commands_Bot
from utils.utils import time_diff

from scripts.LLM_main import Bot_LLM

logger = logging.getLogger(__name__)

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
                message_history_privacy = self.bot.___custom.config['LLM_message_history_privacy'],
                disc_user_messages=self.bot.___custom.disc_user_messages,
                bot_name='StellaMae',
                prompt_format=self.bot.___custom.config['LLM_prompt_format'],
                max_response_tokens=self.bot.___custom.config['LLM_max_response_tokens'],
                temprature=self.bot.___custom.config['LLM_temprature'])
        
        self.user_speaking = self.bot.___custom.user_speaking
        self.queues = self.bot.___custom.queues
        self.show_timings = self.bot.___custom.show_timings

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
        if self.bot.___custom.check_voice_idle(idle_time=self.speaker_pause_time) and self.queues.llm:
            result = await self.process_user_messages(self.queues.llm.copy())
            
    async def process_user_messages(self, messages: list[Discord_Message]) -> bool:
        response_message = Discord_Message(
                member= self.bot_name,
                member_id= self.bot_id,
                listener_names= None,
                listeners= None,
                message_id= self.bot.___custom.get_message_store_key(),
                timestamp_Audio_End= messages[0].timestamp_Audio_End,
            )
        
        async for response in self.wmh_stream_sentences(messages=messages, 
                    response=response_message, 
                    display_history=self.bot.___custom.display_message_history):
            if self.bot.___custom.TTS_enable:
                self.queues.tts.append(TTS_Message({
                    'text': response, 
                    'timestamp_request_start' : messages[-1].timestamp_Audio_End,
                    'wyTTSSynth' : None,
                    'alt_host' : None,
                    'alt_port' : None,
                    'disc_message' : response_message,
                    }))
        response_message = self.cleanup_interrupt(response_message)
        self.queues.db_message.append(response_message)
        self.queues.text_message.append(response_message)
        if self.show_timings:
            logger.info(f'LLM request processed {time_diff(response_message.timestamp_LLM, response_message.timestamp_Audio_End)}')

    def cleanup_interrupt(self, disc_message: Discord_Message) -> Discord_Message:
        if disc_message.text_user_interrupt is None:
            return disc_message
        interrupt_list = []
        sentence_list = []
        int_start = False
        for sentence in disc_message.sentences:
            if sentence.startswith('~(') and sentence.endswith(')'):
                if not int_start:
                    int_start = True
                else:
                    interrupt_list.append(sentence)
            elif sentence == '~~':
                pass
            else:
                interrupt_list.append(sentence)
                sentence_list.append(sentence)
        disc_message.text_user_interrupt = ' '.join(sentence_list)
        disc_message.text = ' '.join(interrupt_list)
        return disc_message

    @commands.Cog.listener('on_message_history')
    # wow this looks buggy
    async def on_message_history(self, message_history: dict[int, Discord_Message]):
        for key, message in message_history.items():
            self.message_store.update({key: message})

    @commands.Cog.listener('on_speaking_interrupt')
    async def on_speaking_interrupt(self, speaking_interrupt: Speaking_Interrupt):
        if self.track_message_interrupt:
            message = self.interupt_sentences(interrupt = speaking_interrupt)
            self.queues.text_message.append(message)
        self.stop_generation = True

    @commands.Cog.listener('on_message_history')
    async def on_message_history(self, member_id: int, message_history: dict[datetime, Discord_Message]):
        logger.info(f'Storing message history for {member_id} with {len(message_history)} messages')
        if len(message_history) == 0:
            return
        for key in sorted(message_history.keys()):
            self.store_message(message = message_history[key], prepend=True)

    @commands.Cog.listener('on_connect')
    async def on_connect(self):
        self.bot_id = self.bot.user.id
        self.bot_name = self.bot.user.name
        self.botman_monitor.start()
        # delay with library load
        logger.info('LLM model is ready')

    async def cleanup(self):
        if self.botman_monitor:
            self.botman_monitor.stop()
        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Bot_Manager(bot))