'''
Simple interface to communicate with LLMs.

choice_bin - a method that returns a True or False value based on the prompt
    provided. This is a little more interesting than at first glance because
    it allows the model to choose to do an action from a prompt based on the 
    context of the conversation. The current setup uses a prompt to choose if 
    to respond in a conversation.
'''
import json, requests, logging, asyncio
import aiohttp

from .datatypes import Discord_Message, positive_responses, negative_responses, RResponse

logger = logging.getLogger(__name__)

# servers that use the openai api
servers_openai_api = ['openai', 'text-gen-webui'] 

# server variants that can select model to load
servers_selectable_models = ['ollama', 'text-gen-webui']

class LLM_Interface():
    def __init__ (self, llm_uri: str, llm_model: 
                  str, server_type: str, 
                  temperature: float = 0.7, 
                  max_response_tokens: int = 200, 
                  context_length: int = 16768):

        self.llm_uri = llm_uri
        self.llm_server_type = server_type
        self.llm_model_list: list[str] = self.get_model_list()
        self.llm_model:str = self.set_model(llm_model)
        self.stop_generation: bool = False
        self.context_length: int = context_length
        #self.llm_client = ollama.AsyncClient(self.llm_uri)
        
        self.session: aiohttp.ClientSession = aiohttp.ClientSession()
        self.session_count: int = 0

        self.data_get_tokens= {
            'model':self.llm_model,
            'prompt':'',
            'stream':False,
            'raw': False,
            'format':'json',
            "options" : {"num_predict": 1}
            }

        self.data_thoughts = {
            'model':self.llm_model,
            'stream':False,
            'format':'json',
            'context': None,
            'raw': False,
            "options" : {
                "num_predict": 100,
                "temperature": temperature}
            }

        self.data_stream = {
            'model':self.llm_model,
            'stream':True,
#            'format':'',
            'context': None,
            'raw': True,
            "options" : {
                "num_predict": max_response_tokens,
                "temperature": temperature
                }
            }
        
    def session_start(self):
        self.session_count += 1

    async def session_end(self):
        self.session_count -= 1
        #if self.session_count == 0:
        #    await asyncio.sleep(5)
        #    if self.session_count == 0:
        #        await self.session.close()
                
    async def get_num_tokens(self, prompt: str) -> int:
        '''
        Get the number of tokens in a string. Set to 1 
        token prediction to avoid wasting resources.
        '''
        output_json = ''
        self.data_get_tokens['prompt'] = prompt
        self.session_start()
        async with self.session.post(f'{self.llm_uri}/api/generate', json=(self.data_get_tokens)) as response:
            if response.status == 200:
                async for chunk in response.content.iter_any():
                    output_json += chunk.decode('utf-8')
            else:
                print(f'Error {response.status}: {await response.text()}')
        output_dict = json.loads(output_json)
        await self.session_end()
        return output_dict['prompt_eval_count']

    async def choice_bin(self, ctr_system_prompt: str, 
                    messages: str = None, 
                    raw: bool = True) -> RResponse:
        '''
        JSON request to the LLM to have the bot make a binary choice. Originally  
        designed to have the bot choose to respond to the conversation, but a different
        prompt would allow for different choices.
        The resoning dictionary is used to provide context for the decision.
            choice - if it choose to respond or not
            reasoning - why it chose that option... sometimes it responds with garbage...
        '''
        self.session_start()
        response = ''
        if raw:
            self.data_thoughts['raw'] = True
            self.data_thoughts['prompt']=  ctr_system_prompt + '\n' + messages
            if 'system'in self.data_thoughts.keys():
                self.data_thoughts.pop('system')
        else:
            self.data_thoughts['raw'] = False
            self.data_thoughts['prompt']= '\n' + messages
            self.data_thoughts['system']=ctr_system_prompt

        output_json = ''
                
        async with self.session.post(f'{self.llm_uri}/api/generate', json=self.data_thoughts) as response:
            if response.status == 200:
                async for chunk in response.content.iter_any():
                    output_json += chunk.decode('utf-8')
            else:
                print(f'Error: {response.status}')

        rresponse = RResponse(response_data=output_json)

        await self.session_end()
        return rresponse

    async def stream(self, user:str, system: str, assistant: str, raw: bool = True):#, system: str):
        '''
        Simple streaming client for the LLM API. It uses raw mode to override whatever the
        llm server is doing to the prompts
        '''
        self.session_start()
        if raw:
            self.data_stream['raw'] = True
            self.data_stream['prompt']=  system + '\n' + user + '\n' + assistant
            if 'system'in self.data_thoughts.keys():
                self.data_stream.pop('system')
            if 'assistant'in self.data_thoughts.keys():
                self.data_stream.pop('assistant')
        else:
            self.data_stream['raw'] = False
            self.data_stream['prompt']= '\n' + user
            self.data_stream['system']= system
            self.data_stream['assistant'] = assistant

        #async with self.session.post(f'{self.llm_uri}/api/generate', json=self.data_thoughts) as response:
        async with self.session.post(f'{self.llm_uri}/api/generate', json=self.data_stream) as response:
            if response.status == 200:
                async for chunk in response.content.iter_any():
                    try:
                        yield json.loads(chunk.decode('utf-8', errors='ignore'))['response']
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
                                    print(f'Error note quite handled correctly json decode: {c}\n {e1}')
                        # check to see if we care
                        elif not (_.find('"done"') - _.find('"response"')) == len('"response":""","'):
                            print(f'Error json decode: {chunk}\n {e}')
        
        await self.session_end()

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