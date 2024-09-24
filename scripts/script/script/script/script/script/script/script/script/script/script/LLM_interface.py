'''
Simple interface to communicate with LLMs.

choice_bin - a method that returns a True or False value based on the prompt
    provided. This is a little more interesting than at first glance because
    it allows the model to choose to do an action from a prompt based on the 
    context of the conversation. The current setup uses a prompt to choose if 
    to respond in a conversation.

aiohttp session closure is responsibilty of the cog to watch the session_last
and close it 30 seconds after last use.
'''
import json, logging, asyncio
from time import perf_counter

from typing import Type, Any

#import aiohttp
#from langchain_openai import OpenAI
#from langchain_community.llms.ollama import Ollama
#from openai import AsyncOpenAI
import httpx

from scripts.datatypes import Prompt_SUA

logger = logging.getLogger(__name__)

# servers that use the openai api
servers_openai_api = ['openai', 'text-gen-webui'] 

class LLM_Interface():
    def __init__ (self, config: dict):
        self.llm_uri = f'http://{config["LLM_host"]}:{int(config["LLM_port"])}'
        self.llm_server_type = config['LLM_server_type']
        self.llm_model:str = config['LLM_model']
        self.llm_token_max: int = int(config['LLM_context_length'])
        self.llm_temperature: float = float(config['LLM_temperature'])
        self.llm_api_key: str = config['LLM_api_key']
        self.llm_token_chat_max = int(config['LLM_token_response'])

        self.prompt_type = config['LLM_prompt_format']
        self.prompts: Prompt_SUA = config['PROMPTS']['PROMPTS'][self.prompt_type]

        self.spit_prompts()

        self.prompt_assistant: str = self.prompts['assistant']
        self.assistant_tokens: int = 0

        self.llm: httpx.AsyncClient = httpx.AsyncClient(base_url=self.llm_uri)
        #self.session: aiohttp.ClientSession = aiohttp.ClientSession()
        #self.session_last = 0.0

        self.stop_generation: float = False

    def spit_prompts(self):
        _ =self.prompts['system'].split('{system_prompt}')
        self.prompts['system_b'] =_[0]
        if len(_) > 1:
            self.prompts['system_e'] =_[-1]
        else:
            self.prompts['system_e'] =''
        _ =self.prompts['user'].split('{user_prompt}')
        self.prompts['user_b'] =_[0]
        if len(_) > 1:
            self.prompts['user_e'] =_[-1]
        else:
            self.prompts['user_e'] =''
    
    ''''
    def setup_server(self) -> AsyncOpenAI:
        if self.llm_server_type in servers_openai_api:
            return AsyncOpenAI(
                api_key=self.llm_api_key,
                base_url=f'{self.llm_uri}/v1')
        elif self.llm_server_type == 'ollama':
            return AsyncOpenAI(
                api_key=self.llm_api_key,
                base_url=f'{self.llm_uri}')    

        if self.llm_server_type in servers_openai_api:
            return OpenAI(base_url=f'{self.llm_uri}/v1',
                        model=self.llm_model,
                        temperature=self.llm_temperature,
                        api_key=self.llm_api_key)
        elif self.llm_server_type == 'ollama':
            return Ollama(base_url=self.llm_uri,
                        model=self.llm_model,
                        temperature=self.llm_temperature,
                        keep_alive=-1,
                        num_ctx=self.llm_token_max)
    '''
    def get_request_data(self, 
                system_str: str, 
                user_str: str, 
                stream=False, 
                num_predict=256, 
                raw=True,
                output_json=False) -> dict:
        
        if self.llm_server_type == "ollama":
            request_data = {
                "model":self.llm_model,
                "raw" : True,
                "stream" : stream,
                "options" : {
                    "num_predict" : num_predict,
                    "temperature": self.llm_temperature
                    }
                }
            if raw:
                p = self.prompts
                request_data["prompt"] = f'{p["system_b"]}{system_str}{p["system_e"]}{p["user_b"]}{user_str}{p["user_e"]}{p["assistant"]}'
            else:
                request_data["system"] = system_str
                request_data["prompt"] = user_str
            if output_json:
                request_data["format"] = "json"

        return request_data

    async def get_num_tokens(self, prompt: str) -> int:
        '''
        Get the number of tokens in a string. Set to 1 
        token prediction to avoid wasting resources.
        '''
        request_data = self.get_request_data(
                    system_str='', 
                    user_str=prompt, 
                    stream=False, 
                    raw=False,
                    num_predict=1)
        response = None
        async with httpx.AsyncClient() as client:
            r = await client.post(
                    url=f'{self.llm_uri}/api/generate', 
                    data=json.dumps(request_data))
            response = json.loads(r.content)
            await client.aclose()
            await asyncio.sleep(0)
        return response['prompt_eval_count']
        '''
        self.session_last = perf_counter()

        request_data = self.get_request_data(system_str='Token Count', user_str=prompt, num_predict=1)

        output_json = ''
        if self.session.closed:
            self.session = aiohttp.ClientSession()
        async with aiohttp.ClientSession() as session:
        #async with self.session.post(f'{self.llm_uri}/api/generate', json=request_data) as response:
            async with session.post(f'{self.llm_uri}/api/generate', json=request_data) as response:
                if response.status == 200:
                    async for chunk in response.content.iter_any():
                        output_json += chunk.decode('utf-8')
                else:
                    print(f'Error: {response.status}')
            await session.close()
            await asyncio.sleep(0)

            output_dict = json.loads(output_json)
        
        try:
            output = int(output_dict['prompt_eval_count'])
        except KeyError as e:
            print(e, output_dict)
        return int(output_dict['prompt_eval_count'])
        '''
    async def generate_factory(self, prompts: Prompt_SUA, output_class: Type[Any], 
                raw: bool = True, temp: float = 0.7, format_json: bool = True) -> any:
        '''
        Generate a non streaming response from the LLM server and puts the results
        into the output_class. The output class is responsble for parsing the data.
        '''
        request_data = self.get_request_data(
                system_str=prompts['system'], 
                user_str=prompts['user'], 
                raw=raw,
                stream=False,
                output_json = format_json)
        output = ''
        async with httpx.AsyncClient() as client:
            r = await client.post(
                    url=f'{self.llm_uri}/api/generate', 
                    data = json.dumps(request_data))
            output = r.content.decode('utf-8')
            await client.aclose()
            await asyncio.sleep(0)
        return output_class(output)

    async def stream(self, prompts: Prompt_SUA, raw: bool = True):
        '''
        Simple streaming client for the LLM API. It uses raw mode to override whatever the
        llm server is doing to the prompts
        '''
        request_data = self.get_request_data(system_str=prompts['system'], user_str=prompts['user'], raw=raw, stream=True)
        async with httpx.AsyncClient() as client:
            async with client.stream('POST', f"{self.llm_uri}/api/generate", json=request_data) as response:
                async for chunk in response.aiter_bytes():
                    obj = json.loads(chunk)
                    yield obj['response']
            await client.aclose()
            await asyncio.sleep(0)
    #async with self.llm.agenerate()
        
        '''aiohttp
        request_data = self.get_request_data(
            system_str=prompts['system'], 
            user_str=prompts['user'], 
            raw=raw,
            stream=True,
            json=False
            )
        async with aiohttp.ClientSession() as session:
            async with session.post(f'{self.llm_uri}/api/generate', json=request_data) as response:
        #async with self.session.post(f'{self.llm_uri}/api/generate', json=request_data) as response:
                if response.status == 200:
                    async for chunk in response.content.iter_any():
                        output_json = chunk.decode('utf-8')
                        output = json.loads(output_json)['response']
                        yield output
                else:
                    print(f'Error: {response.status}')
            await session.close()
            await asyncio.sleep(0)
        '''


if __name__ == '__main__':
    quit()