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
import logging, asyncio
from datetime import datetime
from time import perf_counter

from discord import TextChannel
from discord.ext import commands, tasks

from scripts.datatypes import Discord_Message, TTS_Message, Speaking_Interrupt
from scripts.discord_ext import Commands_Bot
from scripts.utils import time_diff

from scripts.LLM_main import Bot_LLM

logger = logging.getLogger(__name__)

class Bot_Manager(commands.Cog, Bot_LLM):
    def __init__(self, bot) -> None:
        self.bot: Commands_Bot = bot
        super().__init__(config=self.bot.custom.config, 
                    bot_name=self.bot.custom.bot_name,
                    bot_id=self.bot.custom.bot_id,
                    message_listened_to=self.bot.custom.message_listened_to,
                    message_store=self.bot.custom.message_store)

        self.speaker_pause_time = float(self.bot.custom.config['LLM_speaker_pause_time'])

        self.track_message_interrupt: bool = bool(
                int(self.bot.custom.config['behavior_track_text_interrupt']))
        
        self.user_speaking = self.bot.custom.user_speaking
        self.queues = self.bot.custom.queues
        self.show_timings = self.bot.custom.show_timings
        self.text_channel: TextChannel = self.bot.custom.text_channel
        self.display_history:bool = self.bot.custom.display_message_history

        self.wants_to_respond: bool = False
        self.wants_to_respond_reason: str = ''
        self.wants_to_respond_last_message: int = None
        self.choosing_to_respond_in_progress: bool = False
        self.wmh_in_progress: bool = False


    @tasks.loop(seconds=0.1)
    async def botman_monitor(self):
        if self.user_speaking:
            self.stop_generation = True
            self.llm.stop_generation = True
        else:
            self.stop_generation = False
            self.llm.stop_generation = False

        # close the aiohttp session if inactive
        #if (perf_counter() - self.llm.session_last) < 2:
        #    if not self.llm.session.closed:
        #        await self.llm.session.close()

        # check if the messages have been responded to in self.queue.llm and remove them
        if self.queues.llm != 0:
            process_list = self.queues.llm.copy()
            for item in process_list:
                if item.reponse_message_id:
                    self.queues.llm.remove(item)
        
        # check voice idle and process messages
        if (len(self.queues.llm) > 0):
            process_list = []
            for item in self.bot.custom.queues.llm:
                process_list.append(item)
            await self.process_user_messages(process_list)

                
    async def choose_to_respond(self):
        if self.choosing_to_respond_in_progress:
            return
        self.choosing_to_respond_in_progress = True

        query_messages = {i for i in range(self.last_bot_message, self.message_id_high + 1)}
        response = await self.make_a_choice_to_respond(messages=query_messages)

        if response:
            self.wants_to_respond = True
            self.wants_to_respond_reason = response['reason']
        else:
            self.wants_to_respond = False
            if self.bot.custom.show_choice_to_respond:
                await self.text_channel.send(str(response), delete_after=10)
            self.wants_to_respond_reason = response['reason']
        
        self.choosing_to_respond_in_progress = False
            
    async def process_user_messages(self, messages: list[Discord_Message]):
        if self.wmh_in_progress:
            return None
        self.wmh_in_progress = True

        response_message = Discord_Message(
                user_name= self.bot_name,
                user_id= self.bot_id,
                timestamp_Audio_End= messages[0].timestamp_Audio_End,
            )
        
        async for response in self.wmh_stream_sentences(
                    messages=messages, 
                    bot_response_mesg=response_message,
                    bot_info=self.prompts.bot_info,
                    display_history=self.display_history
                    ):
            if self.bot.custom.tts_enable:
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
        self.wmh_in_progress = False

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

    async def get_prompt_tokens(self):
        await asyncio.sleep(3)
        text = self.prompts.gen_prompt_chat(self.prompts.bot_info, {'Alice', 'Bob'})
        num_tokens = await self.llm.get_num_tokens(prompt=text)
        self.prompts.bot_info.set_tokens(prompt_name="CHAT",tokens=num_tokens)
        print(num_tokens)
        
        text = self.prompts.gen_prompt_ctr(bot_info=self.prompts.bot_info, listeners={'Alice', 'Bob'}, history= '')
        num_tokens = await self.llm.get_num_tokens(prompt=text)
        self.prompts.bot_info.set_tokens(prompt_name="CTR",tokens = num_tokens)
        print(num_tokens)

        self.llm.assistant_tokens = await self.llm.get_num_tokens(self.llm.prompt_assistant)
        print(self.llm.assistant_tokens)

    @commands.Cog.listener('on_speaking_interrupt')
    async def on_speaking_interrupt(self, speaking_interrupt: Speaking_Interrupt):
        if self.track_message_interrupt:
            message = self.interupt_sentences(interrupt = speaking_interrupt)
            self.queues.text_message.append(message)
        self.stop_generation = True

    @commands.Cog.listener('on_message_history')
    async def on_message_history(self, user_id: int, message_history: dict[datetime, Discord_Message]):
        logger.info(f'Storing message history for {user_id} with {len(message_history)} messages')
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
        self.prompts.bot_info.name = self.bot_name
        await self.get_prompt_tokens()
        logger.info('LLM model is ready')

    async def cleanup(self):
        if self.botman_monitor:
            self.botman_monitor.stop()
        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Bot_Manager(bot))