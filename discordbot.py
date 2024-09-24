'''
This is the core bot that implements the basic text functionality of the bot. Most of the magic
is done by the cogs. 

Authoization is implimented in a basic fashion any anyone on the server that is not a basic
user can run text commands. Fairly easy to come up with more complex system (i.e. server owner,
server admin, bot admin roles could be introduced.)

Configuration: Handled via the .env file, which is copied to the bot.config dictionary when the
bot starts up. Not married to this implimentation.

Annoying problem with discord channels - when a message is updated or created, an audio message
is sent to all users in discord. A conversation will create messages frequently and send that
alert. Not sure how to impliment a correction on this (other than tell the users to configure
their clients to not send audio messages for the channel). It might be possible to have the bot
create the channel when the voice client connects with no permisssions to anyone except the bot,
then update permissions when the user enters the voice channel.

Events Dispatched

    text_client_connected: data passed text_channel: discord.TextChannel
        This is dispatched when the text channel is connected to the bot. The data passed is
        a discord.TextChannel object.

    callme: data passed 
        name: one word string

Events Listeners

    on_ready - logs an info message

Commands

    list_cogs - lists all cogs to the text channel

    reload - reloads a cog if modified. Experimental feature and is probably better to
        restart the bot.

    die - calls cleanup in all cogs and then exits

    callme - sets name for llm (Bob instead of SuperSexyBob) - not implimented

    unload - unloads a cog, use 3 letters instead of the full cog name

    load - loads a cog (not implimented, broken code)


Configuration

    client_token
    client_text_channel
    behavior_track_text_interrupt="True"
    behavior_command_prefix='.'    

Cog Configuration

    Expected methods
    
        cleanup - called when the bot is shutting down to clean up any resources that may be
            in use. Just create a method with pass if not needed.

    configuration parameters - all configuration parameters are stored in the .env file, copied
        to to bot.config and can be accessed by self.bot.config[<parameter>]

        
    todo 
    check on_member_update
'''
import logging, asyncio, os, json

from dotenv import dotenv_values

import discord
from discord.ext import commands, tasks

from scripts.discord_ext import Commands_Bot

from scripts.datatypes import Discord_Message
from scripts.utils import time_diff

config = dotenv_values('../.env')
with open("data/prompts.json", "r") as f:
    config["PROMPTS"] = json.load(f)

intents=discord.Intents.all() 
intents.members = True
intents.voice_states = True
intents.message_content = True

discord.utils.setup_logging()

bot = Commands_Bot(command_prefix=config["behavior_command_prefix"], intents=intents, config=config)

#bot = commands.Bot(command_prefix=config["behavior_command_prefix"], intents=intents)

'''
future ideas:
    user mute penalty box: track users who speak over other users and give them a penalty box 
        for a certain amount of time this will be a dictionary with the user id as the key and 
        the number of times they have spoken over another user as the value
    STT input coherence check - pass the text to the llm with the history and see if the llm
        can correct errors in the text (word error rate is still above 6% for the best models)

things to check 

    STT - Make sure behavoir is correct for multiple users
'''

async def load_cogs():
    #Intentionally kept text cog integrated to the main bot
    #await bot.add_cog(TextInterface(bot))

    for file in os.listdir('./cogs'):
        if (file.endswith('.py') and not file.startswith('__')):
            await bot.load_extension(f'cogs.{file[:-3]}')

async def main():   
    
    await load_cogs()
    
    await bot.start(config['client_token'])

asyncio.run(main())