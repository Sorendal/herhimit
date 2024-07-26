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
import json, requests, logging
from time import perf_counter
import aiohttp

from scripts.datatypes import CTR_Reasoning
from scripts.LLM_prompts import Prompt_SUA

logger = logging.getLogger(__name__)

# servers that use the openai api
servers_openai_api = ['openai', 'text-gen-webui'] 

# server variants that can select model to load
servers_selectable_models = ['ollama', 'text-gen-webui']

class LLM_Interface():
    def __init__ (self, config: dict):
        self.llm_uri = f'http://{config["LLM_host"]}:{int(config["LLM_port"])}'
        self.llm_server_type = config['LLM_server_type']
        self.llm_model_list: list[str] = self.get_model_list()
        self.llm_model:str = self.set_model(config['LLM_model'])
        self.temperature: float = float(config['LLM_temperature'])

        self.token_chat_max_response = int(config['LLM_token_response'])
        self.token_thought_max_response = self.token_chat_max_response // 2

        self.session: aiohttp.ClientSession = aiohttp.ClientSession()
        self.session_last = 0.0

        self.stop_generation: float = False

        self.request_data = {
            'model':self.llm_model,
            'prompt':'',
            'stream':False,
            'raw': False,
            'format':'json',
            "options" : {
                "num_predict": 100,
                "temperature": self.temperature
                }
            }

    async def get_num_tokens(self, prompt: str) -> int:
        '''
        Get the number of tokens in a string. Set to 1 
        token prediction to avoid wasting resources.
        '''
        self.session_last = perf_counter()

        request_data = self.request_data.copy()
        request_data['options'] = self.request_data['options'].copy()
        request_data['prompt'] = prompt
        request_data["options"]["num_predict"] = 1

        output_json = ''

        async with self.session.post(f'{self.llm_uri}/api/generate', json=request_data) as response:
            if response.status == 200:
                async for chunk in response.content.iter_any():
                    output_json += chunk.decode('utf-8')
            else:
                print(f'Error: {response.status}')
        output_dict = json.loads(output_json)
        output = 0
        try:
            output = int(output_dict['prompt_eval_count'])
        except KeyError as e:
            print(e, output_dict)
        return int(output_dict['prompt_eval_count'])

        async with self.session.post(
                        f'{self.llm_uri}/api/generate', 
                        json=(request_data)) as response:
            if response.status == 200:
                async for chunk in response.content.iter_any():
                    output_json += chunk.decode('utf-8')
            else:
                logger.info(f'Error {response.status}: {await response.text()}')
        output_dict = json.loads(output_json)
        return int(output_dict['prompt_eval_count'])

    async def generate(self, prompts: Prompt_SUA, output_class, 
                raw: bool = True, temp: float = 0.7, not_json: bool = False) -> any:
        '''
        Generate a non streaming response from the LLM server. 

        The 2nd parameter is the class of the output object.
        '''
        request_data = self.request_data.copy()
        request_data['options'] = self.request_data['options'].copy()
        self.session_last = perf_counter()

        response = ''

        if raw:
            request_data['raw'] = True
            request_data['prompt']=  f'{prompts["system"]}\n{prompts["user"]}\n{prompts["assistant"]}'
        else:
            request_data['raw'] = False
            request_data['system']= prompts['system']
            request_data['prompt']= prompts['user']
            request_data['assistant'] = prompts['assistant']
        request_data['stream'] = False
        if not_json:
            request_data['output'] = ''
        else:
            request_data['output'] = 'json'
        request_data["options"]["temperature"] = temp

        output_json = ''
                
        async with self.session.post(f'{self.llm_uri}/api/generate', json=request_data) as response:
            if response.status == 200:
                async for chunk in response.content.iter_any():
                    output_json += chunk.decode('utf-8')
            else:
                print(f'Error: {response.status}')

        return output_class(output_json)

    async def stream(self, prompts: Prompt_SUA, temp: float = .7 ,raw: bool = True):
        '''
        Simple streaming client for the LLM API. It uses raw mode to override whatever the
        llm server is doing to the prompts
        '''
        self.session_last = perf_counter()
        request_data = self.request_data.copy()
        request_data['options'] = self.request_data['options'].copy()

        print(f'{prompts["system"]}\n{prompts["user"]}\n{prompts["assistant"]}')

        

        if raw:
            request_data['raw'] = True
            request_data['prompt']=  f'{prompts["system"]}\n{prompts["user"]}\n{prompts["assistant"]}'
        else:
            request_data['raw'] = False
            request_data['system']= prompts['system']
            request_data['prompt']= prompts['user']
            request_data['assistant'] = prompts['assistant']
        request_data['stream'] = True
        request_data['output'] = 'json'

        request_data["options"]["temperature"] = temp
        request_data["options"]["num_predict"] = self.token_thought_max_response

        async with self.session.post(f'{self.llm_uri}/api/chat', json=self.request_data) as response:
            if not response.status == 200:
                raise Exception(f'Error: {response.status}')
            else:
                async for chunk in response.content.iter_any():
                    print(chunk)
                    try:
                        output_chunk = json.loads(chunk.decode('utf-8', errors='ignore'))['response']
                        print(output_chunk, end="", flush=True)
                        yield output_chunk
                    except Exception as e:
                        _ = chunk.decode('utf-8')
                        # sometimes chunks are concatinated
                        if _.find('}\n{') > -1:
                            split_chunk = _.split('\n')
                            split_chunk[1] = "'b'" + split_chunk[1]
                            split_chunk[0] = split_chunk[0] + "\n"
                            for c in split_chunk:
                                try:
                                    #end of stream
                                    if not c.find("done_reason") == -1:
                                        continue
                                    yield json.loads(c)['response']
                                except Exception as e1:
                                    logger.info(f'Error note quite handled correctly json decode: {c}\n\n {e1}\n')
                        # check to see if we care
                        elif not (_.find('"done"') - _.find('"response"')) == len('"response":""","'):
                            logger.info(f'Error json decode: {chunk}\n {e}')
        
    def get_model_list(self) -> list:
        '''
        Get the list of models from the LLM API
        '''
        model_list = []
        if self.llm_server_type == 'text-gen-webui':
            response = requests.get(url=f'{self.llm_uri}/v1/internal/model/list')
            for item in response.json()['model_names']:
                model_list.append(item)
            return model_list
        elif self.llm_server_type == 'ollama':
            response = requests.get(url=f'{self.llm_uri}/api/tags')
            response_json = response.json()
            for item in response_json['models']:
                model_list.append(item['name'])
            return model_list

    def set_model(self, model_name: str)-> str:
        if self.llm_server_type in servers_selectable_models:
            try:
                for item in self.llm_model_list:
                    if item.lower().startswith(model_name.lower()):
                        return item
            except Exception as e:
                self.current_model = None

if __name__ == '__main__':
    quit()