import asyncio
from contextlib import AsyncExitStack
import json
from dotenv import load_dotenv 
import os

from typing import Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from openai import AsyncAzureOpenAI


import azure.cognitiveservices.speech as speechsdk  

import time  

import json



 
load_dotenv("1.env")  
#client = OpenAI(api_key=os.environ["api_key"], base_url=os.environ["base_url"])
model="gpt-4o-mini"
#client = OpenAI(api_key="1", base_url="http://localhost:11434/v1") 
Azure_speech_key = os.environ["Azure_speech_key"]  
Azure_speech_region = os.environ["Azure_speech_region"]  
Azure_speech_speaker = os.environ["Azure_speech_speaker"]  
WakeupWord = os.environ["WakeupWord"]  
WakeupModelFile = os.environ["WakeupModelFile"]  

messages = []  

# Set up Azure Speech-to-Text and Text-to-Speech credentials  
speech_key = Azure_speech_key  
service_region = Azure_speech_region  
speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)  
# Set up Azure Text-to-Speech language  
speech_config.speech_synthesis_language = "zh-CN"  
# Set up Azure Speech-to-Text language recognition  
speech_config.speech_recognition_language = "zh-CN"  
lang = "zh-CN"  
# Set up the voice configuration  
speech_config.speech_synthesis_voice_name = Azure_speech_speaker  
speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)  
connection = speechsdk.Connection.from_speech_synthesizer(speech_synthesizer)  
connection.open(True)  
# Creates an instance of a keyword recognition model. Update this to  
# point to the location of your keyword recognition model.  
model = speechsdk.KeywordRecognitionModel(WakeupModelFile)  
# The phrase your keyword recognition model triggers on.  
keyword = WakeupWord  
# Set up the audio configuration  
audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)  
# Create a speech recognizer and start the recognition  
#speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)  
auto_detect_source_language_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=["ja-JP", "zh-CN"])  
speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config,  
                                               auto_detect_source_language_config=auto_detect_source_language_config)  
unknownCount = 0  
sysmesg = {"role": "system", "content": os.environ["sysprompt_zh-CN"]}  
tts_sentence_end = [ ".", "!", "?", ";", "。", "！", "？", "；", "\n" ]


isListenning=False


def display_text(s):
    print(s)
def speech_to_text():  
    global unknownCount  
    global lang,isListenning  
    print("Please say...")  
    result = speech_recognizer.recognize_once_async().get()  
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:  
        unknownCount = 0  
        isListenning=False
        return result.text  
    elif result.reason == speechsdk.ResultReason.NoMatch:  
        isListenning=False
        unknownCount += 1  
        error = os.environ["sorry_" + lang]  
        text_to_speech(error)  
        return '...'  
    elif result.reason == speechsdk.ResultReason.Canceled:  
        isListenning=False
        return "speech recognizer canceled." 
    

def getVoiceSpeed():  
    return 17  
  
def text_to_speech(text, _lang=None):  
    global lang  
    try:  
        result = buildSpeech(text).get()  
        #result = speech_synthesizer.speak_ssml_async(ssml_text).get()  
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:  
            print("Text-to-speech conversion successful.")  
            return "Done."  
        else:  
            print(f"Error synthesizing audio: {result}")  
            return "Failed."  
    except Exception as ex:  
        print(f"Error synthesizing audio: {ex}")  
        return "Error occured!"  
        
def buildSpeech(text, _lang=None):
    voice_lang = lang  
    voice_name = "zh-CN-XiaoxiaoMultilingualNeural"  
    ssml_text = f'''  
        <speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xmlns:emo="http://www.w3.org/2009/10/emotionml" version="1.0" xml:lang="{lang}"><voice name="{voice_name}"><lang xml:lang="{voice_lang}"><prosody rate="{getVoiceSpeed()}%">{text.replace('*', ' ').replace('#', ' ')}</prosody></lang></voice></speak>  
    '''  
    print(f"{voice_name} {voice_lang}!")  
    return speech_synthesizer.speak_ssml_async(ssml_text) 

modelName="gpt-4o-mini"
class MCPClient:
    def __init__(self):
        self.playing=False
        self.session: Optional[ClientSession] = None
        self.sessions={}
        self.exit_stack = AsyncExitStack()
        self.tools=[]
        self.messages=[]

        self.client = AsyncAzureOpenAI(  
            azure_endpoint=os.environ["URL"],  
            api_key=os.environ["key"],  
            api_version="2024-05-01-preview",
        )

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()

    async def connect_to_server(self):
        with open("mcp_server_config.json", "r") as f:
            config = json.load(f)
            print(config["mcpServers"])  
        conf=config["mcpServers"]
        print(conf.keys())
        for key in conf.keys():
            v = conf[key]
            command = v['command']
            args=v['args']
            print(command)
            print(args)
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=None
            )
            
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            stdio1, write1 = stdio_transport
            session = await self.exit_stack.enter_async_context(ClientSession(stdio1, write1))
            
            await session.initialize()
            
            # 列出可用工具
            response = await session.list_tools()
            tools = response.tools
            print("\nConnected to server with tools:", [tool.name for tool in tools])
            for tool in tools:
                self.sessions[tool.name]=session
            self.tools=self.tools+tools
            print(self.sessions)

    async def process_query(self, query: str) -> str:
        """使用 LLM 和 MCP 服务器提供的工具处理查询"""
        self.messages=self.messages+[
            {
                "role": "user",
                "content": query
            }
        ]
        messages =self.messages[-20:]

        available_tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema
            }
        } for tool in self.tools]

        # 初始化 LLM API 调用
        response = await self.client.chat.completions.create(
            model=modelName,
            messages=messages,
            tools=available_tools
        )

    
        final_text = []
        message = response.choices[0].message
        final_text.append(message.content or "")

        # 处理响应并处理工具调用
        while message.tool_calls:
            # 处理每个工具调用
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                # 执行工具调用
                result = await self.sessions[tool_name].call_tool(tool_name, tool_args)
                #final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")
                
                print(f"MCP: [Calling tool {tool_name} with args {tool_args}]")

                # 将工具调用和结果添加到消息历史
                messages.append({
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args)
                            }
                        }
                    ]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result.content)
                })

            # 将工具调用的结果交给 LLM
            response = await self.client.chat.completions.create(
                model=modelName,
                messages=messages,
                tools=available_tools
            )
            
            message = response.choices[0].message
            if message.content:
                final_text.append(message.content)

        answer="\n".join(final_text)
        self.messages=self.messages+[{"role": "assistant","content":answer}]
        return answer
    
    async def getPlayerStatus(self):
        result = await self.sessions["isPlaying"].call_tool("isPlaying", {})
        print(f"getPlayerStatus:{result.content[0].text}")
        if result.content[0].text=="true":
            return "playing"
        else:
            return ""
    async def pauseplay(self):
        await self.sessions["pauseplay"].call_tool("pauseplay", {})

    def recognized_cb(self,evt):  
        result = evt.result  
        if result.reason == speechsdk.ResultReason.RecognizedKeyword:  
            print("RECOGNIZED KEYWORD: {}".format(result.text))  
        global done  
        done = True  

    def canceled_cb(self,evt):  
        result = evt.result  
        if result.reason == speechsdk.ResultReason.Canceled:  
            print('CANCELED: {}'.format(result.cancellation_details.reason))  
        global done  
        done = True  
               
    async def chat_loop(self):
        """运行交互式聊天循环"""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")
        
        global unknownCount ,isListenning 
        while True:  
            keyword_recognizer = speechsdk.KeywordRecognizer()  
            keyword_recognizer.recognized.connect(self.recognized_cb)  
            keyword_recognizer.canceled.connect(self.canceled_cb) 
            first=os.environ["welcome_" + lang]
            display_text(first) 
            if await self.getPlayerStatus()!='playing':
                text_to_speech(first)  
            isListenning=True
            result_future = keyword_recognizer.recognize_once_async(model)  
            while True:  
                result = result_future.get()
                # Read result audio (incl. the keyword).
                if result.reason == speechsdk.ResultReason.RecognizedKeyword:
                    print("Keyword recognized")
                    isListenning=False
                    if await self.getPlayerStatus()=='playing':
                        await self.pauseplay() #被唤醒后，如果有音乐播放则暂停播放
                    break
                time.sleep(0.1)  
                
            display_text("很高兴为您服务，我在听请讲。")  
            text_to_speech("很高兴为您服务，我在听请讲。")  
            
            
            while unknownCount < 2:
                isListenning=True
                user_input = speech_to_text()
                if user_input=='...':
                    continue
                
                display_text(f"You: {user_input}")  
                response = await self.process_query(user_input)
                display_text(f"AI: {response}")  
                
                if await self.getPlayerStatus()=='playing':
                    break
                
                text_to_speech(f"{response}")  
                
            
            bye_text = os.environ["bye_" + lang]  
            display_text(bye_text) 
            if await self.getPlayerStatus()!='playing':
                text_to_speech(bye_text)  
            
            unknownCount = 0  
            time.sleep(0.1)  

async def main():
    client = MCPClient()
    try:
        await client.connect_to_server()
        await client.chat_loop()
    finally:
        await client.cleanup()
        print("AI: Bye! See you next time!")

if __name__ == "__main__":
    asyncio.run(main())

#uv run voice.py 启动客户端

  



