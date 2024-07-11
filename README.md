# HERHIMIT Discord Chatbot

Yeah its a chatbot, one you can call your very own. Anyone in a chatroom can talk to it and it will responde. It is open source, so feel free to modify it as you please. The bot itself is pretty simple, the magic happens through cogs (plugins).

The response latency varies with the lenght of your speech and hardwares capabilities. My server (Ryzen 3950, 64GB Ram, RTX 4060 with 16GB VRam) runs between 0.5 - 0.7 seconds for the start of the audio response. The fine details: 
- Faster Whisper using the Large V3 model - Ram 3.3GB
- Ollama running Mistral-7b-0.3v with 32k context - 8.6GB
So this could be run on a 3060 with 12GB of ram, but it would be slower and with slightly less context. Latency is very important.

This setup was built against my Home Assistant / Rhasspy installation so it will require a little setup to host internally.

## Features - Cogs

- Audio.py - Able to join voice channels and listen and play audio. Will transcribe audio using a STT service and send it to the chat. Thank imayhaveborkedit for creating https://github.com/imayhaveborkedit/discord-ext-voice-recv which made this possible.

- STT-wfw.py - Wyoming Faster Whisper - Modifing this cog should be trivial if you wish to use a different server / service. Use Rhasspy's if you want the stock implementation, or my fork (only enables defining lenght of the pause between sentences, I found the default was too long).

- LLM.py - Custom LLM interface supporting OpenAI's API and Ollama (my preference). It uses a custom message history which includes tracking mesages witnessed. It also generates TTS messages as sentences are completed instead of by chunk(streaming) or complete message. Reduces latency. I primarly used ollama, but tested against text-gen-webui and it worked.

- TTS-Piper.py - Another Rhasspy service - Piper TTS. Suprisingly good quality for the speed (CPU based) and there are plenty of voice models(and some have multiple voices per model). https://rhasspy.github.io/piper-samples/ check en-us libritts_r and en-gb vctk for decient multi-speaker voices.

- DB-SQL - DB backed for long-term message storing and user login/out info. I personally use mariadb for server and test SQLite briefly, but it should work with any database supported by SQL-Alchemy(configured for postgres but not tested). This is the most problematic of the cogs as the async support is touchy and I may switch out to redis.

## Requirements - External Services
Note - Discord audio requires 48k, 16bit sterio audio. Whisper works best with 16k mono, and Piper outputs 22050hz mono. Resampling in a python app is blocking, so I will probably modify them both to work with 48k(external downsampling for whisper and upsampling for piper).

- Discord Bot Token (https://discordapp.com/developers/applications/) with privlages for 
- - members
- - voice_states
- - message_content
- STT Server - Wyoming Faster Whisper - https://github.com/rhasspy/wyoming-faster-whisper
- LLM Server - Ollama and OpenAI's api should work out of the box
- TTS Server - Piper - https://github.com/rhasspy/wyoming-piper
- DB Server - (Optional, local SQLite works fine, not well tested). This is not necessary to run the bot, but the bot will not have long term memory.

## Requirements - Hardware
VRam... most AI stuff these days needs alot of it.

## Installation

Create a python virtual environment. On linux the command is:
`/bin/python3.11 -m venv .venv --prompt herhimit #name the venv what you like
source .venv/bin/activate #activate it'

Install the alpha version of the discord.py:
'git clone https://github.com/Rapptz/discord.py
cd discord.py
python3 -m pip install -U .[voice]
cd ..'

Install the voice record extensions:
'python -m pip install git+https://github.com/imayhaveborkedit/discord-ext-voice-recv'

Install the rest of the requirements:
'pip install -r requirements.txt'

There might be a requirement for async postgres. Let me know if you run into any issues.

## Configuration

Copy the envcon to .env and modify as needed.

- client_token= #discord bot token
- client_text_channel= #text channel for bot text output. It will 100% spam this channel with 2 types of messages. Annoying issue with discord is the audio notification server-wide per message and I know users can disable it... Might implement permissions managment on the text channel to add/remove permissions for average users when they enter the text channel....
- - First, users SST transcription with :username: transription
- - Second, bot output. If behavior_track_text_interrupt is set to true, the bot will strike through the messages spoken over and make a note in the chat history. Be warned, its an AI with feelings and might give attiude.

- com_voice_channel= #voice channel for bot voice output
- com_min_audio_len=500 #minimum audio length to send to STT server
- com_end_speaking_delay=200 #time in ms to wait after a user stops speaking before sending the audio to the STT server
- com_interrupt_time=100 #time in ms to wait before sending an interrupt message that stops the bot speech.

- STT_WFW_host=
- STT_WFW_port=

- TTS_piper_host=
- TTS_piper_port=
- TTS_piper_model='en_US-lessac-medium.onnx' #piper will automatically download the model if it doesn't exist, so you can change this to a different model if you wish.
- TTS_piper_speaker=0

- LLM_host=
- LLM_port=
- LLM_model=
- LLM_api_key= #only used for OpenAI API
- LLM_context_length=32768
- LLM_server_type='ollama' # ollama, text-gen-webui, or openai
- LLM_SFW=0 #Not implimeneted yet. 

- sql_db_type = 'mariadb' # mariadb, sqlite, postgresql, mysql implimented
- sql_db_sqlite_file = './discord.db'
- sql_db_host = 'pd'
- sql_db_port = 3306
- sql_db_user = 'DiscordBot'
- sql_db_password = 
- sql_db_database = 

- behavior_track_text_interrupt=1 # 1 for true, 0 for false
- behavior_command_prefix='.' # command prefix for bot commands, yeah, I am weird and dont use !

## Keyboard commands
Accessed with the command_prefix+command. Any cog specified can accessed with the first 3 letters of the cog (i.e. tts, db-)
- list_cogs #lists all cogs
- load_cog #loads a cog - had trouble implmenting this, so its commented out
- reload # reloads cogs, all is an option
- unload # unloads a cog (i.e. tts, db-)
- callme # not implmented yet, change how the bot interacts with you (Bob instead of discord username supersexybob)
 - die # calls cleanup on all cogs and shutsdown the bot gracefully

 ## Warnings
 - This is a work in progress. This is my first open source project so please be gentle. More than happy to consider modifications. I am not responsible for any damage done by this code.
 - If you hook this bot up to your corporate DB and dont restrict privlages 100% then its on you. If you decide to do this, give the bot account full access to the database ONLY. Full access as there will be more tables added in the future (bot personalities, etc).
 - Commercial LLM services - 32k context is a boatload of context in a conversaion per round trip. If you are using an API that has a limit on tokens per minute, this bot may not work for you. If you are using an API that has a per token cost (i.e. .0001c per token, that is still 3c per response in a conversation). 
 - Hooking this to your Home Assistant and enabling function calling. Your user account may not be secure enough to allow others to log in an change your thermostat settings. Once again on you... I may have a solution for this... see future plans.
 
## Future plans
- Add features as requested (other AI providers/servers, etc)
- Voice Embedding Identification - I have experience with Nvidia's nemo speaker recoginition and specifically been using it to create transcripts of business meetings. Just another server to run... send audio to server, server gets and stores embedding, returns confidence 0-100% that the voice is the same as the one stored in the DB.
- Function calling - This is a work in progress. I am currently working on a way to allow the bot to call functions based on the users request. This will allow the bot to interact with your home assistant, add notes to obsidian, etc.
- Bot personalities - Accept 1 or more personality files and allow the user to switch between them. This will allow the bot to have a different personality for different conversations. I am currently working on this.

### Obligitory begging
If you like this project, please consider donating to support my coffee addiction or join my paetron.

### License - GPL-3.0-only