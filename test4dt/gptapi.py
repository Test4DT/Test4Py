import os
from openai import OpenAI
from dotenv import load_dotenv
from aiolimiter import AsyncLimiter
import asyncio
import logging


class MyGPT:
    count = 0

    def __init__(self, temperature=0.0, max_rate=300, time_period=20, model_type="gpt-4o"):
        load_dotenv()
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.openai_api_base = os.getenv('OPENAI_API_BASE')
        self.temperature = temperature
        self.limiter = AsyncLimiter(max_rate=max_rate, time_period=time_period)
        self.model_type = model_type

        self.client = OpenAI(
            api_key=self.openai_api_key,
            base_url=self.openai_api_base,
        )

        logging.basicConfig(
            filename='error.log',
            level=logging.ERROR,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filemode='w'
        )

    async def aask(self, system, user):
        async with self.limiter:
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            return await asyncio.to_thread(self.chat, messages)

    def chat(self, messages)->str:
        try:
            chat = self.client.chat.completions.create(
                model=self.model_type,
                messages=messages,
                temperature=self.temperature,
                stream=False
            )
            output = chat.choices[0].message.content
            logging.error(messages)
            logging.error(output)
            self.count += 1
        except BaseException as e:
            logging.error(e)
            return ""
        return output

model = MyGPT()
