from pydantic import BaseModel #valida los datos de entrada                                                                         
from typing import List                                                                               

#modelo de datos generico, luego lo cambias said xd

class Message(BaseModel):
      sender: str
      text: str

class ConversationRequest(BaseModel):
      platform: str
      minor_id: str
      messages: List[Message]