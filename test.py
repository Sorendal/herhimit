from langchain.prompts import PipelinePromptTemplate, PromptTemplate

from utils.datatypes import LLM_Prompts

class Test():
    def __init__(self) -> None:
        self.intro_prompt: PromptTemplate = None
        self.character_prompt:PromptTemplate = None
        self.instruction_prompt:PromptTemplate = None
        self.history_prompt:PromptTemplate = None
        self.single_user_response:PromptTemplate = None
        self.multiple_user_response:PromptTemplate = None
        self.full_template: PromptTemplate = None
        self.prompt_single_message_response: PipelinePromptTemplate = None
        self.prompt_multiple_message_response: PipelinePromptTemplate = None    
        self.setup_prompts()

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


my_test = Test()
print(my_test.prompt_multiple_message_response.input_variables)
quit()
full_prompt = PromptTemplate.from_template(full_template)


introduction_template = LLM_Prompts.intro_template
introduction_prompt = PromptTemplate.from_template(introduction_template)

history_prompt = PromptTemplate.from_template(LLM_Prompts.history_template)
instruction_prompt = PromptTemplate.from_template(LLM_Prompts.instuction_template)
example_template = LLM_Prompts.character_template

example_prompt = PromptTemplate.from_template(example_template)

start_template = LLM_Prompts.single_message_template

input_prompt = PromptTemplate.from_template(start_template)

pipeline_prompt = PipelinePromptTemplate(
    final_prompt=full_prompt, pipeline_prompts=input_prompts
)

print(pipeline_prompt.input_variables)

