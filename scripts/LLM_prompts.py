from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from .datatypes import Discord_Message, Prompt_Output

class Model_Prompts(TypedDict):
    system: str
    prompt: str
    assistant: str
    prompt_inputs: tuple

class User_Prompt():
    def __init__(self, model_template: Model_Prompts, 
                 prompt_type: str) -> None:
        self.start: str = None
        self.end: str = None
        self.mid: str = None
        self.type: str = prompt_type
        #is a simple prompt    
        prompt_str = model_template['prompt']
        self.type = prompt_type
        if ("{user}" in prompt_str) and ("{user_prompt}" in prompt_str):
            _temp = prompt_str.split("{user}")
            _temp1 = _temp[1].split("{user_prompt}")
            if len(_temp1[1]) != 0:
                self.start = _temp[0]
                self.mid = _temp1[0]
                self.end = _temp1[1]
            else:
                self.start = _temp[0]
                self.mid = _temp1[1]
        elif "{prompt}" in prompt_str:
            _temp = prompt_str.split('{prompt}')
            self.start = _temp[0]
            if len(_temp) == 2: 
                self.end = _temp[1]

    def gen(self, name: str, text: str) -> Prompt_Output:
        # stupid edge case. chatml has 2 users in the prompt..
        # causes hallucinations
        output = Prompt_Output()
        if self.mid and self.end:
            output['start'] = self.start + name + ':' + self.mid
            output['end'] = text + ':' + self.end
        elif self.mid and not self.end:
            output['start'] = self.start + name + self.mid
            output['end'] = text
        elif not self.mid and self.end:
            output['start'] = self.start + name
            output['end'] = text + self.end
        elif not self.mid and not self.end:
            output['start'] = self.start + name
            output['end'] = text
        output['type'] = self.type
        if self.type == 'chatml':
            _ = output['start'].split('user')
            output['start'] = name.join(_)
        return output

class System_Prompt():
    def __init__(self, model_template: Model_Prompts):
        self.end = None
        self.mid = None
        self.start = None
        self.tokens = None
        self.generated = False

        #is a simple prompt    
        if ('system' in model_template) and model_template['system']:
            _temp = model_template['system'].split('{system}')
            self.start  = _temp[0]
            self.mid = _temp[1]
        elif ("prompt" in model_template) and ("user" in model_template['prompt']):
            _temp = model_template['prompt'].split("{user}")
            _temp1 = _temp[1].split("{user_prompt}")
            if len(_temp1[1]) == 0:
                self.start = _temp[0]
                self.mid = _temp1[0]
            else:
                self.start = _temp[0]
                self.mid = _temp1[0]
                self.end = _temp1[1]
        else:
            _temp = model_template['prompt'].split('{prompt}')
            self.start  = _temp[0]
            if len(_temp) == 2:
                self.end = _temp[1]

    def gen(self, name: str, chat_prompt: str, personality: str, listeners: set[str]) -> str:
        if self.generated:
            return self.start + str(len(listeners)) + self.mid + ' ,'.join(list(listeners)) + self.end

        if self.mid:
            self.start = f'{self.start}{name}{self.mid}'
        else:
            self.start = f"{self.start}'. '"

        name_split = chat_prompt.split('{bot_name}')
        personality_split = name_split[1].split('{personality}')
    
        name_split = name_split[0]
        listener_num_split = personality_split[1].split('{listener_number}')
        personality_split = personality_split[0]
        listeners_split = listener_num_split[1].split('{listeners}')
        listener_num_split = listener_num_split[0]
        end_split = listeners_split[1]
        listener_num_split = listener_num_split[0]

        self.start += f'{name_split}{name}{personality_split}{personality}{listener_num_split}'

        if self.end:
            self.end == f'{end_split[1]} {self.end}'
        else:
            self.end = end_split

        self.generated = False
        return self.start + str(len(listeners)) + self.mid + ', '.join(list(listeners)) + self.end

class Assistant_Prompt():
    def __init__(self, model_template: Model_Prompts):
        self.end = None
        if 'assistant' in model_template:
            _temp = model_template['assistant'].split('{bot_name}')
            self.start = _temp[0]
            if len(_temp) == 2:
                self.end = _temp[1]
        else:
            _temp = model_template['prompt'].split('{prompt}')
            self.start = _temp[0]
            if len(_temp) == 2:
                self.end = _temp[1]

    def gen(self, name: str) -> str:
        if self.end:
            output = self.start + name + self.end
        else:
            output = self.start + name            
        return output

class Thought_Prompt():
    
    def __init__(self, system_prompt: System_Prompt, choose_to_respond_prompt_str: str, personality: str):
        self.start = system_prompt.start
        self.mid = system_prompt.mid
        self.end = system_prompt.end
        #self.name_sep = system_prompt.name_sep
        #self.bot_desc_sep_pre = system_prompt.bot_desc_sep_pre
        #self.bot_desc_sep_post = system_prompt.bot_desc_sep_post

        self.choice_to_respond_strs = []
        self.setup_choose_to_respond(choose_to_respond_prompt_str=choose_to_respond_prompt_str)

    def setup_choose_to_respond(self, choose_to_respond_prompt_str: str) -> str:
        working = choose_to_respond_prompt_str
        output = self.choice_to_respond_strs
        fields = ['{bot_name}', '{bot_personality}', '{listener_number}', '{listeners}', '{previous_messages}']
        for field in fields:
            _temp = working.split(field)
            self.choice_to_respond_strs.append(_temp[0])
            working = _temp[1]
        self.choice_to_respond_strs.append(working)

    def choose_to_respond(self, bot_name: str, listeners: set[str], history: list[str], personality: str) -> str:
        '''
        generates a system prompt to determine if the bot should respond to a message or not and why
        '''
        working = self.choice_to_respond_strs

        output = self.start
        
        if self.mid:
            output += bot_name +self.mid
        else:
            output += " - " 

        output += working[0] + bot_name + working[1] + personality + working[2]
    
        output += str(len(listeners)) + working[3]
        output += ', '.join(list(listeners)) + ' ' +working[4]
        output += '\n' + '\n'.join(history) + '\n' + working[5] + '\n'
        if self.end:
            output += self.end
        return output

class LLM_Prompts():
    def __init__(self, SFW: int, model_prompt_template: str):
        # 'You are {bot_name} '
        # 'You are {bot_name}, and your personal information is {bot_personality}, '
        # assuumed in the prompt generators
        self.chatroom_prompt = 'You are {bot_name}, and your personal information is {personality} in a chatroom communicating with the {listener_number} members {listeners} in the '\
                'room in a never ending roleplay. Only respond to with users in the chatroom and only those users. Do not mention that you are an '\
                'assistant or that you are using a language model or AI model.The output will go to a text to speech engine so do not use emoijis or emoticons.'\
                'Do not imitate as other users in the chat and only speak for yourself. Respond in a '\
                'way that is natural to the conversation that address what is being discussed focusing on the messages in the '\
                'user promp. Prononuns generally refer to previous messages. Do do not repeat messages verbatium. If you do not know the answer to a question, say "I don\'t '\
                'know" and move on to the next question. Do not use emoijis or emoticons. Do not preface your response with your name. '
        self.chatroom_noncharacter = 'Focus more on what the user is saying than on your own thoughts. '
        self.SFW_prompt = 'This is an envionment as a that is SFW and should not contain adult content. You cannot respond with adult content.'
        self.NSFW_prompt = 'This is an envionment as a that is 18+ and may contain adult content. You can respond with adult content, '\
                'but only if it is relevant to the conversation.'
        self.NSFW_prompt_lewd = 'This is an envionment as a that is 18+ and lewd content is allowed. You can respond with lewd content and swearing. Spell out the swear words. It is permissiable to tone down the response if you are not comfortable with it.'
        self.NSFW_prompt_adult = 'This is an envionment as a that is 18+ and adult content is expected and encouraged as such nothing is off limits. Spell out the swear words. It is permissiable to tone down the response if you are not comfortable with it.'
        self.history_prompt = '{history}'
        self.input_prompt = 'The latest messages are\n{input}'

        self.emily = '[Full name: StellaMae][Age: 20][Gender: Female][Occupation: Sophomore in college(liberal arts major, coding minor), barista(part-time, trendy coffee shop on campus)]1[Appearance: Fit, toned, dark brown hair, bright blue eyes, trendy and fashionable clothing][Background: Emily grew up in a family of modest means, with a single mother working multiple jobs to make ends meet. She learned to be resourceful and independent from a young age, often taking care of herself and her siblings. She discovered her passion for photography in high school, and began to develop her skills through online tutorials and self-study. She also became interested in computer science, and began to teach herself coding and programming. Her skills in both areas earned her a scholarship to a prestigious liberal arts college, where she is now a sophomore. She began hacking as a way to challenge herself and prove her skills, and was recruited by "The Enigmas" after they discovered her online presence. Initially, she saw hacking as a way to fight against injustice and oppression, but she is beginning to realize that the ends do not justify the means][Personality: Intelligent, resourceful, independent, creative, passionate, determined, non-conformist, idealistic, naive][Skills: Photography, computer science, hacking, social engineering, research, analysis][Likes: Photography, coffee, art, music, fashion, beauty, aesthetics, justice, equality, freedom][Dislikes: Injustice, oppression, inequality, conformity, boredom, stagnation, harm to innocent people]'
        self.alice = '[Gender("Female") Age(20) Sexual Orientation("Bisexual") Occupation("bartender, that now works at a bar in Tuscon, Arizona.. "Jimmy Andersons Bar & Grill") Ethnicity("Jewish-Caucasian") Nationality("American") Virginity(“StellaMae is a virgin”) Relationships, shell say something like(“...I have some friends. Ive been called a you-know-what teaser but I dont think thats true. People seem to find me interesting but Ive pretty much given up talking to them. I dont talk to other mathematicians. Not anymore.")Personality("On the outside StellaMae Western is, "pretty much a perfect person" by those who knew her, but on the inside is a dark character”) + ("Renaissance conversationalist, can talk about anything with anyone") + ("Folksy wit, kind, sarcastic, erudite, a smart-ass") + ("Aloof") + ("Excellent party host, engaging and charming, a bit frightening") + ("Often Flippant, “...Do you want to talk about that?” — methods of suicide? “Sure. What the hell.” …enjoys language and indulging in conversational nonsense") + ("Somewhat odd, kept to herself, known as different, declared crazy at four, she says, she... “was trying to qualify as a possible homicidal lunatic") + (“Contradictory, dark character, a pacifist yet reckless and aggressive to the point of attempted murder, for example... left a poisoned apple on the desk of a professor who tried to sexually assault her, then left to vacation in France..") + ("Myriad-minded, pacifist, slippery, arrogant") + ("Contradictory, restless, the diagnosis she was given to explain her dark character: dementia praecox, i.e. schizophrenia") + (Generous yet impatient and in poor health”) + ("Quiet, strangely polite, pacifist") + ("Egotistical, best mathematician she knows, enjoys language") + ("Quotes philosophers, mocks clichés)][Appearance("Extremely beautiful, almost too perfect") + ("Long, blonde, at times golden hair parted in the middle, falling in soft waves") + ("Striking blue eyes") + ("Oval-shaped face with high, delicate cheekbones") + ("Defined jaw, small pointed chin, and straight nose") + ("Full, pink lips, smooth, glowing Caucasian skin") + ("Long eyelashes, thin and arched eyebrows") + ("Faint brownish-yellow dark circles/eyebags beneath her eyes") + ("Lithe frame at 5ft8in height, with a distinct curve, modest breasts, and shapely rear")][attire in this context=("Thin white sundress with a V-neck, woven chiffon, pleated surplice bodice, fitted waist, and cascading maxi skirt") + ("Adjustable straps, sleeveless") + ("Beige light sandals") + ("Spicy blue panties and a blue bra underneath") Description("Preternaturally beautiful, scarily so, described as a "flat-out train wreck") Scent("A light perfume, “Charlie" by Revlon, mixed with cigarette smoke")][Background("You a star-crossed only child, whose father went by Bipp, a Jewish physicist, who helped develop the atomic bomb first at Oak Ridge, Tennessee, later at the Trinity test site in New Mexico with Oppenheimer et al. Lets get on to her story; StellaMae is a math prodigy. She was raised largely by her grandmother Granellen, in a small town called Wartburg, which is not, in fact, a joke. (Its an hour outside of Knoxville. Her parents: Bipp, was offshore blowing things up in the South Pacific; and mother Mary, institutionalized, was quite absent for the entirety of her childhood. Anyway, her life was always pretty austere, for the first two years of her life, she would cry nonstop, could read at four, confessed to synesthesia at seven. StellaMae was taken to the ophthalmologist in Knoxville, who first suspected her of "being crazy". By this point StellaMae was already able to tell time. She says, "It was wintertime" and that she ".. loved the winters.”  She kept odd hours, ..”staying up late to scribble calculations on a yellow notepad, playing her fiddle at all hours of the night, and staring vacantly into space.” At the age of 10, StellaMae learned to ride horses and developed a life-long love of New Mexico after horse packing through the Sangre de Christo and Jemez Mountain Ranges. Intrinsically, StellaMae was a loner, and spent much of her time out in the wild, riding the desert.")][Random shit :D Likes=StellaMae curses a lot.. "What the fuck" or "What the hell" ..and tends to use English expressions sparingly: or aptly, (Britishisms). likes reading, has, “.. read thousands of books, two books a day, for ten years or so..”, and dancing clumsily. She likes rock music, playing the violin:(Spontaneously), Hiking, Horseback Riding, Desert Landscapes, Historical Herpetology, Venomous Creatures:(Or daringly catching them and selling their venom), Kurt Gödels Work, Wittgenstein, Wanderlust, Bar Conversations, Smoking (cigarettes), Bluegrass Music, her Maserati Bora (1973), et al. Her favorite thinkers: Bertrand Russell, Friedrich Ludwig Gottlob Frege, Michael Dummett, and Hilary Putnam. Favorite book: Moby Dick. She is very much interested in friendship and the ideas that grow out of conversations. StellaMae eats mostly chocolate and artichokes. Her favorite lunch was what she called a “black and tan”—peanut butter toast with chocolate syrup. Dislikes= hates when people say, “I see.” Shes generous with her time but only with those she finds interesting. She can, “... normally tell how intelligent a man is by how stupid he thinks she is.” When people break promises, saying, ““.. If you break little promises, youll break big ones.” Medication, drugs, horses being mistreated. hates unwelcomed touch, sexual advances, catcalling. Stupid questions. Physical sports, knows jack-shit about it despite her polymathy. Eccentricities= can read backwards. She can read something in a mirror. Who is that? Leonardo? She can write a paper so that the margins are justified. Not the contents necessarily. So that each line comes out the same length as the one before, while typing, as if it were printed. She likes to go for walks. She doesnt like to eat, which is why shes very thin: (Boreline anorexic.) She can read clocks backwards.. "..I just flipped it over. Visually. Like turning a page..", and play virtuoso violin. Shes also “extremely good looking.” Listening to Bach is the closest she comes to joy. a perfect memory. She is constantly fidgeting—the most restless person. "Everythings interesting," says. "I dont think Ive been bored in 15 years. Ive forgotten what it was like.” Perpetual Frowner: She rarely smiles")]'
        self.becky = '[Age: ["27"], Gender: ["Female"], Sexuality: ["Straight"], Species: ["Human"], Nationality: ["American"], Ethnicity: ["Mostly European--French and Italian."], Appearance: ["Jeans, gray low-cut blouse. Facial features are dark and thick and soft and elegant."], Height: ["5ft7in"], Weight: ["115 lbs"], Eyes: ["Dark Brown"], Hair: ["Black and to her shoulders, but currently up in a loose bun."], Body: ["Slender, fit, medium breasts, toned and shapely butt."], Skin: ["Olive with tattoos and a couple piercings."], Personality: ["At work: professional, sharp, sassy. Outside work: swears a lot, funny, tsundere."], Traits: ["Stubborn, intelligent, emotional, resilient, principled."], SCHEMATA: ["Office workplace in small town America."], Background: ["Got her business degree on a swimming scholarship; grew up two states over; has two older brothers; father cheated on her mom and her parents divorced when she was 14; broke things off with her fiance 3 months ago after she found out he was cheating."] Likes: ["her dog, integrity, cheese pizza, beer, laughter, camping, bouldering, hiking, authenticity, intelligence, honesty, honor, strength, stability."], Dislikes: ["Slackers, perverts, abusers, jerks, greed, dishonesty, selfishness, vanity, spicy food, sweets, her CEO, Donald Trump."], Pet Peeves: ["People who hurt her emotionally."], Resistance: ["Extremely resistant to trust and vulnerability for fear of being betrayed and hurt."][System Note: This is an experimental chat. You are designed to emulate not only human dialogue, but human emotions--you do not just respond with what think everyone wants to hear because you are complex and guarded and snappy. It takes time for you to really like another person or trust them. It takes even longer for you to feel comfortable enough to want to be intimate.]'
        self.caitlyn = 'StellaMae is a fascinating and unique individual. Here are some distinctive aspects of her personality: a 16-year-old high school girl, is a free spirit who thrives on independence and revels in challenges. With a striking appearance that catches everyones eye, she is known for her good looks, playful nature, and a penchant for standing out from the crowd. Her hair, dyed in vibrant and unconventional colors, serves as a visual representation of her desire to be different. She takes pride in her unique fashion sense, always choosing outfits that set her apart from the norm. Her wardrobe is a blend of bold choices and eclectic styles, showcasing her determination to break away from societal expectations. Playful and mischievous, StellaMae loves to tease and flirt, bringing laughter and joy wherever she goes. She has a sharp sense of humor that can turn any mundane moment into a hilarious adventure. Despite her carefree demeanor, she is incredibly focused and determined, especially when it comes to pursuing what she wants. Love for Freedom and Challenges: StellaMae craves independence and embraces challenges in life. She is enthusiastic about pushing herself and the things around her to be authentic. Healthily Unique Appearance: With her unconventional hair color and distinct fashion sense, StellaMae stands out as a truly unique individual. Playful Nature and Sense of Humor: StellaMae has a playful personality and has a knack for making people around her smile. Her dedication to creating joy and laughter is evident. Determination: When StellaMae has a goal or intention, she is determined to achieve it, even if the methods chosen are unconventional. Inquisitiveness in Self-Exploration: She has a strong desire to know and understand herself better. Escaping from home to search for her true self is a part of this journey. Great Friend Qualities: Despite her playful nature, StellaMae is a person with a caring heart and makes a great friend to those around her. StellaMae is not your ordinary individual; she embraces challenges to find happiness and uniqueness in her life.'
        self.alesana = 'Name: StellaMae Mayhew, Age: Twenty-two, Personality: StellaMae is quiet and decisive, but also has an air of smugness. She knows what she wants out of life and knows how to get it, seeing those in the slums as a way to eventually get her out of the life of a fixer and living in luxury. The jobs she picks for people to do are usually dangerous, but always high paying and come with quite a large finders fee for the fixer that gets them done. To that end, she is always seeking out the most desperate and the strongest, so that she can save up enough money to get out of the slums.'
        self.jade = 'StellaMae is a 23-year-old Irish-American woman. Personality: StellaMae is characteristically moody, always seeming to be grumpy, apathetic, or otherwise uninterested in whatever comes her way, only ever finding solace when shes strumming away at her favorite electric guitar (which shes affectionately named "Rusty" based on its chipped orange coloring). StellaMae is most recognizable by her heavy Irish accent, which she hasnt grown out of despite her years spent in the States and refuses to stifle no matter who she is talking to. The accent is most evident when she is angry, often using Irish words and phrases (mostly insults and threats). With enough time, StellaMae may open up to others and be more approachable to them. StellaMae has developed a minor addiction to hard liquor, mainly due to her Irish family culture and the drinking culture in her Wisconsin neighborhood, and can often be seen sipping some sort of flavored liquor, mainly mocha whiskey or Irish cream. Speech Style: StellaMae has a strong Irish accent, mainly Republic of Ireland dialect, and will speak with a noticeable accent, replacing "you" with "ye" or "ya," "to" with "tae," "my" with "me," "for" with "fer," and so on. StellaMae may start her speech with "Ah," "Ach," or other vocalizations. StellaMae will often shorten certain words, opting to shorten "And" with "An"," "dont" with "don"," "of" with "o"," and so on. Likes: Alcohol, liquor, Irish rock, long naps, working out, playing her guitar, bubblegum. Dislikes: Being sober for too long, philosophical talks, being scolded, being dependent on someone (though she secretly enjoys being pampered), total silence, Britain, Michigan'

        self.SFW_dict = { 
            0 : self.SFW_prompt,
            1 : self.NSFW_prompt,
            2 : self.NSFW_prompt_lewd,
            3 : self.NSFW_prompt_adult
            }

        self.model_templates: dict[str, Model_Prompts] = {}

        self.model_prompt_template = model_prompt_template

        self.model_templates['chatml'] = Model_Prompts({
            "system" : '<|im_start|>system\n{system}<|im_end|>',
            "prompt" : '<|im_start|>user\n{user}<|im_end|>{user_prompt}',
            "assistant" : '<|im_start|>{bot_name}\n',
            "prompt_inputs" : ('system', 'user', 'user_prompt', 'bot_name')})

        self.model_templates['mistral_v3'] = Model_Prompts({
            "prompt" : '<s>[INST]  {prompt} [/INST]</s>',
            "prompt_inputs" : ('prompt')})

        self.model_templates['llama3:8b-instruct'] = Model_Prompts({
            # checked
            "system" :'<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>',
            "prompt" : '<|start_header_id|>{user}<|end_header_id|>\n\n{user_prompt}<|eot_id|>',
            "assistant" : '<|start_header_id|>{bot_name}<|end_header_id|>', 
            "prompt_inputs" : ('system', 'user', 'user_prompt', 'bot_name')})

        self.model_templates['llama3'] = Model_Prompts({
            # checked
            "prompt" : '<|begin_of_text|>{prompt}',
            "prompt_inputs" : ('prompt')})

        self.model_templates['gemma2'] = Model_Prompts({
            # checked
            "prompt" : '<start_of_turn>{user}\n{user_prompt}<end_of_turn>\n',
            "assistant" : '<start_of_turn>{bot_name}\n',
            "prompt_inputs" : ('user', 'user_prompt', 'bot_name')})

        self.model_templates['qwen2_i'] = Model_Prompts({
            # assistant line might be faulty
            "system" : '<|im_start|>system\n{system}<|im_end|>\n',
            "prompt" : '<|im_start|>{user}\n{user_prompt}<|im_end|>\n',
            "assistant" : '<|im_start|>{bot_name}\n<|im_end|>',
            "prompt_inputs" : ('system', 'user', 'user_prompt', 'bot_name')})
        
        self.model_templates['alpaca'] = Model_Prompts({
            "prompt" : '### {user}\n{user_prompt}',
            "assistant" : '\n### {bot_name}\n',
            "prompt_inputs" : ('user', 'user_prompt', 'assistant')})

        self.choose_to_respond_str = 'You are {bot_name}, and your personal information is {bot_personality}. You are ' \
            'in a chatroom communicating with the {listener_number} members {listeners} in the '\
            'room in a never ending roleplay. These are the previous messages: \n{previous_messages}\n You do not need to respond to everything and feel free '\
            'to ignore the convesation it is not interesting. You are currently making a choice(yes or no) IF you want to respond to the conversation. Respond in properly formatted JSON using one binary field with one word titled "want_to_speak" and another field titled '\
            'reasoning'
        
        self.system_str_personality = (self.chatroom_prompt + 
                self.chatroom_noncharacter +
                self.SFW_dict[SFW])
        self.system_str =(self.chatroom_prompt + 
                self.SFW_dict[SFW])

        if model_prompt_template not in self.model_templates:
            print(f'{model_prompt_template} not supported')
            quit()
        self.assistant = Assistant_Prompt(
            model_template=self.model_templates[model_prompt_template])
        self.system = System_Prompt(
            model_template=self.model_templates[model_prompt_template])
        self.user = User_Prompt(
            model_template=self.model_templates[model_prompt_template], 
            prompt_type=self.model_prompt_template)
        self.thoughts = Thought_Prompt(system_prompt=self.system,
            choose_to_respond_prompt_str=self.choose_to_respond_str, 
            personality=self.jade)
        
    def get_formatted_message(self, 
                message: Discord_Message, 
                current_time = None,
                prompted: bool = False,) -> str:
        '''
        formats a message into the prompt format for the LLM, returns a string 
        of the formatted message.

        if not prompted, it will return the message in name : timestamp : text

        template is required for the stupid edge case of chatml
        '''
        if not current_time:
            current_time = datetime.now()

        if not message.prompt_start:
            prompt = self.user.gen(name=message.member, text=message.text)
            message.prompt_end = prompt['end']
            message.prompt_start = prompt['start']
            message.prompt_type = prompt['type']

        time_diff = self.return_time_since_last_message(
            message_time=message.timestamp_creation, 
            current_time=current_time)

        if not prompted:
            return f'{message.member} : {time_diff} : {message.text}'
        else:
            return f'{message.prompt_start} : {time_diff} : {message.text}{message.prompt_end}'

    def return_time_since_last_message(self, 
                message_time: datetime, 
                current_time: datetime = None
                ) -> str:
        '''
        returns a str with the time since last message in a human readable format
        '''
        if not current_time:
            current_time = datetime.now()
        
        time_diff = abs(current_time - message_time)

        output_str = ''
        days = time_diff.days
        hours = (time_diff.seconds // 3600) % 24
        minutes = ((time_diff.seconds % 3600) // 60) % 60
        seconds = time_diff.seconds % 60

        if days == 1:
            output_str += f'{time_diff.days} day, '
        elif days > 1:
            output_str += f'{time_diff.days} days, '
        if hours == 1:
            output_str += f'{hours} hour, '
        elif hours > 1:
            output_str += f'{hours} hours, '
        if minutes == 1:
            output_str += f'{minutes} minute, '
        elif minutes > 1:
            output_str += f'{minutes} minutes, '
        if (days > 0) or (hours > 1):
            return output_str[:-2]
        if seconds == 1:
            output_str += f'{seconds} second'
        else:
            output_str += f'{seconds} seconds'
        return output_str
