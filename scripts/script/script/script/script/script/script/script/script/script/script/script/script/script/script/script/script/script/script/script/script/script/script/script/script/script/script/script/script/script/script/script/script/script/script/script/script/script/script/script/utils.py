import re
from datetime import datetime

def time_diff(start: datetime, end: datetime) -> str:
        return f'{abs((end-start).total_seconds()):.3f}'

def strip_non_alphanum(input_string: str, suffix: str=False) -> str:
    '''
    Strip non-alphanumeric characters from the start and end of a string.
    Edge cases were LLMs sometimes return incorrectly formmated strings 
    of json with custom queries with leading or trailing non-alphanumeric 
    characters.

    if you want to keep the suffix, pass suffix the last char (it will strip 
    punctuation).
    '''
    if not suffix:
        suffix = ''
    output_str = re.sub(r'^[^a-zA-Z0-9]*|[^a-zA-Z0-9\n]*$', '', input_string)
    if len(output_str) > 1:
        if output_str[-2].isalpha():
            return output_str + suffix
    output = re.sub(r'^[^a-zA-Z0-9]*|[^a-zA-Z0-9\n]*$', '', output_str[:-1].rstrip()) + suffix
    return output

