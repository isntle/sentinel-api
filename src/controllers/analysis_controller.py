from fastapi import HTTPException  #asi se regresa errores http con codigo y mensaje                                                                     
from src.models.conversation import ConversationRequest                                               
from src.services.analysis_service import analyze_conversation

def handle_analyze(conversation: ConversationRequest):
      if not conversation.messages: # no le dices nada a gemini si no hay mensajes
          raise HTTPException(status_code=400, detail="La conversación no tiene mensajes") 
      #corta la ejecucion y regresa error al cliente antes de gastar tokens

      result = analyze_conversation(conversation) #llama al servicio de service ese con el promp bien insano
      return {"success": True, "analysis": result} # devuelve el resultado en una respuesta limpia el estado y el resultado