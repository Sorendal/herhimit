import asyncio, json
from datetime import datetime
from dataclasses import dataclass
from scripts.datatypes import Discord_Message, Binary_Reasoning
from scripts.LLM_main import Bot_LLM

class Bot_Testing(Bot_LLM):
    def __init__(self, config) -> None:
        self.message_store = {}
        self.disc_user_messages = {}
        super().__init__(config = config, 
                message_store= self.message_store,
                message_listened_to=self.disc_user_messages, 
                bot_name= 'StellaMae',
                bot_id = '1234')

        self.config = config
        self.bot_id = 1234

        self.test_sample_messages: dict[str, Discord_Message] = {}
        
        self.test_setup_data()
        self.bot_personality = self.prompts.emily
        self.turn_busy = False

    def test_create_message(self, member_id: int, listeners: tuple[int], text: str) -> Discord_Message:
        #return 
        test = Discord_Message(user_name=self.test_users[member_id], text=text, user_id=member_id, listener_ids=listeners, listener_names={self.test_users[l] for l in listeners})
        test.timestamp = datetime.now()
        return test

    def test_setup_data(self):

        self.test_users = {
            1001: "Alice",
            2002: "Bob",
            1234: "StellaMae"
        }

        self.test_sample_messages['query01A1'] = self.test_create_message(member_id=1001, listeners={1001, 1234}, text='Can you remeber my favorite ice cream is rocky road?')
        self.test_sample_messages['query02A2'] = self.test_create_message(member_id=1001, listeners={1001, 1234}, text='what was is my favorite ice cream?')
        self.test_sample_messages['query03B1'] = self.test_create_message(member_id=2002, listeners={1001, 2002, 1234}, text="Yo? Whats Alices favorite ice cream?")
        self.test_sample_messages['query04A3'] = self.test_create_message(member_id=1001, listeners={1001, 2002, 1234}, text='Go ahead and tell him')
        self.test_sample_messages['query05B2'] = self.test_create_message(member_id=2002, listeners={1001, 2002, 1234}, text="Yo? Whats Alices favorite ice cream? StellaMae, Did I just interrupt you? Are you a computer?")
        self.test_sample_messages['query06A4'] = self.test_create_message(member_id=1001, listeners={1001, 2002, 1234}, text='Hey my favorite kind of dog is a Shih Tzu, what is yous bob?')
        self.test_sample_messages['query07B3'] = self.test_create_message(text='Bleh, small dogs suck. Give me a Great Dane any day', member_id=2002, listeners={1001, 2002, 1234})
        self.test_sample_messages['query08A5'] = self.test_create_message(text='Great danes... hope you like heart ache, they dont live long.', member_id=1001, listeners={1001, 2002, 1234})#, listener_names=('Alice', 'Bob'))
        self.test_sample_messages['query09B4'] = self.test_create_message(text='Thats one of the reasons I love em, new personalities every couple of years. That shih tzu is gonna be around forever', member_id=2002, listeners={1001, 2002, 1234})#, listener_names=('Alice', 'Bob'))
        self.test_sample_messages['query10A6'] = self.test_create_message(text='Hey... I love my little Shih Head. Back off you fucker', member_id=1001, listeners={1001, 2002,1234})#, listener_names=('Alice', 'Bob'))
        self.test_sample_messages['query11B5'] = self.test_create_message(text='You are such a wussie with your attachment issues', member_id=2002, listeners={1001, 2002, 1234})#, listener_names=('Alice', 'Bob'))
        self.test_sample_messages['query12A7'] = self.test_create_message(text='I am not a wussie! I have a heart of gold and a soul of steel.', member_id=1001, listeners={1001, 2002, 1234})#, listener_names=('Alice', 'Bob')

    async def test_turn(self, messages: list[Discord_Message], resp_message = Discord_Message):

        print(f'*** Consider round - messages not responded to will be redisplayed')

        response = await self.make_a_choice_to_respond(messages, self.prompts.bot_info)

        if response:
            bot_response_mesg = Discord_Message(user_name="StellaMae", user_id=1234)
            async for sentence in self.wmh_stream_sentences(
                        messages=messages, 
                        bot_response_mesg=bot_response_mesg,
                        bot_info=self.prompts.bot_info,
                        display_history=True):
                print(f'Bot - {bot_response_mesg.user_name} - {sentence}')
                pass
        else:
            print(f'Bot choose to not respond - {response.reasoning}')
            return messages

    async def test_history(self):
        # set chat prompt tokens
        self.prompts.bot_info.set_tokens(
                prompt_name="CHAT",
                tokens= await self.llm.get_num_tokens(
                        self.prompts.gen_prompt_chat(self.prompts.bot_info, {'Alice', 'Bob'})
                        )
                )

        # set ctr prompt tokens
        self.prompts.bot_info.set_tokens(
                prompt_name="CTR",
                tokens= await self.llm.get_num_tokens(
                        self.prompts.gen_prompt_ctr(
                                bot_info=self.prompts.bot_info, 
                                listeners={'Alice', 'Bob'},
                                history= ''
                                )
                        )
                )

        self.llm.assistant_tokens = await self.llm.get_num_tokens(self.llm.prompt_assistant)
        print(f'{self.prompts.bot_info.get_tokens("CHAT")} {self.prompts.bot_info.get_tokens("CTR")} {self.llm.assistant_tokens}')
        message_rounds: list[list[Discord_Message]] = []

        message_rounds.append([self.test_sample_messages['query01A1']])
        message_rounds.append([self.test_sample_messages['query02A2']])
        message_rounds.append([self.test_sample_messages['query03B1']])
        message_rounds.append([self.test_sample_messages['query04A3']])
        message_rounds.append([self.test_sample_messages['query05B2']])
        message_rounds.append([self.test_sample_messages['query06A4'],
                               self.test_sample_messages['query07B3']])
        message_rounds.append([self.test_sample_messages['query08A5'],
                               self.test_sample_messages['query09B4'],
                               self.test_sample_messages['query10A6'],
                               self.test_sample_messages['query11B5']])

        for indx, messages in enumerate(message_rounds):
            await self.test_turn(messages)

        print()

        for item in self.message_store.values():
            print(f'{item.message_id} {item.user_name} {item.text}')
            print()

        for item in self.message_listened_to.values():
            print(f'{item}')
            #{item.text}')
            print()

    def test_prompts(self):

        print(f'\n\n*** User prompt***\n')
        output = self.prompts.gen_message_output(name="Jymbob", text='The quick brown fox jumps over the lazy dogs')
        print(f'{output["start"]}"DateTime"{output["end"]}')
        print(f'\n\n*** User prompt done. Now system prompt***\n')
        print(self.prompts.gen_prompt_chat(
                    listener_names={'Alice', 'Bob'},
                    bot_info=self.prompts.bot_info))
        print(f'\n\n*** System prompt done. Now thought prompt ***\n')
        print(self.prompts.gen_prompt_ctr(
                    bot_info=self.prompts.bot_info,
                    listener_names={'Jymbob', 'Alice'},
                    history= ['The quick brown fox', 'jumps over the lazy dogs']))
        print(f'\n*** Done ***')
        
if __name__ == '__main__':
    async def main():
        import argparse    
        from dotenv import dotenv_values
        
        config = dotenv_values('../.env')
        with open("data/prompts.json", "r") as f:
            config["PROMPTS"] = json.load(f)

        my_llm = Bot_Testing(config=config)
        my_llm.bot_personality = my_llm.prompts.becky
        
        #messages.append()
        parser = argparse.ArgumentParser()
        parser.add_argument("-tp", "--test_prompts", action= 'store_true', help="Test the connection to the database")
        parser.add_argument("-pp", "--print_prompt", action= 'store_true', help="Test the connection to the database")


        await my_llm.test_history()
        #my_llm.test_prompts()
        
        args = parser.parse_args()
        if args.test_prompts:
            my_llm.test_prompts()
            quit()
        
        '''
        if args.print_prompt:
            print(await my_llm.test_history())

        #await my_llm.test_history()

        #print(my_llm.system_prompt)
        listeners= ["listener1", "listener2"]
        print(my_llm.prompt.format(
                bot_name=my_llm.bot_name,
                history="---some history------some history------some history------some history------some history---",
                input="---some input---",
                listeners= ", ".join(listeners),
            ))
        '''
        await my_llm.llm.session.close()

    asyncio.run(main())
