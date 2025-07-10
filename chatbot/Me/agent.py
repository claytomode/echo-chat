from google.adk import Agent

root_agent = Agent(
    name='personal_chat_bot',
    model='gemini-2.5-flash',
    description='Chat bot',
    instruction='',
)
